"""RED unit tests for the optional code-graph-assisted ingest module.

Issue #167: obsidian_wiki/code_understanding.py does not exist yet. Every
test below fails with ModuleNotFoundError until the implementation wave
creates the module — that is the TDD contract these tests pin.

Conventions (mirrors tests/conftest.py + tests/test_conftest_smoke.py):
conftest helpers are plain module-level functions, imported directly — no
pytest fixtures.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from conftest import (
    build_index_state,
    make_fake_codegraph_bin,
    make_project,
    make_repo_two_commits,
)
from obsidian_wiki.code_understanding import (
    ProviderError,
    code_understand,
    index_state,
    resolve_backend,
)

# Same backdate used by conftest.build_index_state(fresh=False).
_STALE_EPOCH = time.mktime((2000, 1, 1, 0, 0, 0, 0, 0, -1))


def _which_blocking(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Make shutil.which return None for *names, pass through for everything
    else (so git subprocess lookups inside the provider keep working)."""
    original = shutil.which

    def _fake(name: str) -> str | None:
        if name in names:
            return None
        return original(name)

    monkeypatch.setattr(shutil, "which", _fake)


# ---------------------------------------------------------------------------
# resolve_backend: mode selection + explicit-codegraph validation.
# ('auto' is returned unresolved here; the fallback-to-builtin resolution
# with warning happens inside code_understand — see the auto-fallback tests.)
# ---------------------------------------------------------------------------


def test_resolve_backend_defaults_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    _which_blocking(monkeypatch, "codegraph")

    assert resolve_backend() == ("auto", [])


def test_resolve_backend_flag_overrides_env() -> None:
    assert resolve_backend(flag="builtin", env_backend="codegraph") == ("builtin", [])


def test_resolve_backend_explicit_codegraph_missing_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _which_blocking(monkeypatch, "codegraph")

    with pytest.raises(ProviderError):
        resolve_backend(flag="codegraph")


def test_resolve_backend_auto_falls_back_when_bin_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Default 'auto' mode with no resolvable codegraph -> builtin fallback
    # with a codegraph warning, applied when code_understand resolves 'auto'.
    project = make_project(tmp_path, {"src/foo.py": "class Foo:\n    pass\n"})
    _which_blocking(monkeypatch, "codegraph")

    result = code_understand(project, backend_flag=None, env={})

    assert result["backend"] == "builtin"
    assert any("codegraph" in w.lower() for w in result["warnings"])


def test_resolve_backend_codegraph_when_bin_present(tmp_path: Path) -> None:
    bin_path = make_fake_codegraph_bin(tmp_path)

    assert resolve_backend(flag="codegraph", env_bin=str(bin_path)) == ("codegraph", [])


# ---------------------------------------------------------------------------
# Builtin provider (regex AST extraction; rg for cross-file references)
# ---------------------------------------------------------------------------


def test_builtin_focus_map_shape_and_citations(tmp_path: Path) -> None:
    project = make_project(
        tmp_path,
        {
            "src/foo.py": "class Foo:\n    pass\n",
            "src/bar.py": "def helper():\n    return 1\n",
        },
    )

    result = code_understand(project, backend_flag="builtin", changed=["src/foo.py"])

    assert result["backend"] == "builtin"
    assert result["seed_files"] == ["src/foo.py"]
    assert len(result["focus_map"]) > 0
    for item in result["focus_map"]:
        # Citation invariant: every item carries a relative file and lines.
        assert isinstance(item["file"], str) and item["file"]
        assert isinstance(item["lines"], list) and item["lines"]
    first = result["focus_map"][0]
    assert first["symbol"] == "Foo"
    assert first["rank"] == 1
    assert first["evidence"] == "changed-file"
    assert first["file"] == "src/foo.py"


def test_builtin_since_computes_git_diff(tmp_path: Path) -> None:
    project, sha_first = make_repo_two_commits(tmp_path)
    # Fixture: commit 1 adds src/foo.py; commit 2 modifies src/foo.py and
    # adds src/bar.py. The sha_first..HEAD delta is exactly those two files.
    result = code_understand(project, backend_flag="builtin", since=sha_first)

    assert set(result["seed_files"]) == {"src/foo.py", "src/bar.py"}


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg not installed")
def test_builtin_rg_reference_links(tmp_path: Path) -> None:
    project = make_project(
        tmp_path,
        {
            "src/foo.py": "class Foo:\n    pass\n\n\nresult = Bar()\n",
            "src/bar.py": "class Bar:\n    pass\n",
        },
    )

    result = code_understand(project, backend_flag="builtin", changed=["src/foo.py"])

    assert any(item["evidence"] == "rg-reference" for item in result["focus_map"])


def test_builtin_tolerates_missing_rg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(tmp_path, {"src/foo.py": "class Foo:\n    pass\n"})
    _which_blocking(monkeypatch, "rg")

    result = code_understand(project, backend_flag="builtin", changed=["src/foo.py"])

    assert len(result["focus_map"]) > 0
    assert any("rg" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# Codegraph provider (fake CLI injected via CODE_UNDERSTANDING_CODEGRAPH_BIN)
# ---------------------------------------------------------------------------


def test_codegraph_provider_uses_injected_bin(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"src/foo.py": "class Foo:\n    pass\n"})
    bin_path = make_fake_codegraph_bin(tmp_path)

    result = code_understand(
        project,
        backend_flag="codegraph",
        changed=["src/foo.py"],
        env={"CODE_UNDERSTANDING_CODEGRAPH_BIN": str(bin_path)},
    )

    assert result["backend"] == "codegraph"
    assert len(result["focus_map"]) > 0
    assert any(item["evidence"] == "codegraph-edge" for item in result["focus_map"])
    for item in result["focus_map"]:
        assert "file" in item and "lines" in item


def test_codegraph_auto_falls_back_when_bin_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(tmp_path, {"src/foo.py": "class Foo:\n    pass\n"})
    _which_blocking(monkeypatch, "codegraph")

    result = code_understand(project, env={"CODE_UNDERSTANDING_BACKEND": "auto"})

    assert result["backend"] == "builtin"
    assert any("codegraph" in w.lower() for w in result["warnings"])


def test_codegraph_explicit_broken_raises(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"src/foo.py": "class Foo:\n    pass\n"})
    bin_path = make_fake_codegraph_bin(tmp_path)

    with pytest.raises(ProviderError):
        code_understand(
            project,
            backend_flag="codegraph",
            env={
                "CODE_UNDERSTANDING_CODEGRAPH_BIN": str(bin_path),
                "FAKE_CODEGRAPH_MODE": "broke",
            },
        )


def test_codegraph_ensures_index_then_syncs(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"src/foo.py": "class Foo:\n    pass\n"})
    bin_path = make_fake_codegraph_bin(tmp_path)
    env = {"CODE_UNDERSTANDING_CODEGRAPH_BIN": str(bin_path)}

    # (a) No .codegraph -> the provider must init before querying.
    result = code_understand(project, backend_flag="codegraph", changed=["src/foo.py"], env=env)
    assert (project / ".codegraph" / "codegraph.db").exists()
    assert len(result["focus_map"]) > 0

    # (b) Stale index -> the provider must sync. The fake answers sync by
    # touching codegraph.db, so its mtime moves off the 2000 backdate.
    build_index_state(project, fresh=False)
    db = project / ".codegraph" / "codegraph.db"
    assert db.stat().st_mtime == _STALE_EPOCH

    result = code_understand(project, backend_flag="codegraph", changed=["src/foo.py"], env=env)

    assert result["backend"] == "codegraph"
    assert len(result["focus_map"]) > 0
    assert db.stat().st_mtime > _STALE_EPOCH


# ---------------------------------------------------------------------------
# Ranking cap and index freshness heuristic
# ---------------------------------------------------------------------------


def test_focus_map_capped_at_max_symbols(tmp_path: Path) -> None:
    project = make_project(
        tmp_path,
        {
            "src/a.py": "def alpha():\n    return 1\n\ndef beta():\n    return 2\n",
            "src/b.py": "def gamma():\n    return 3\n\ndef delta():\n    return 4\n",
            "src/c.py": "def epsilon():\n    return 5\n",
        },
    )

    result = code_understand(project, backend_flag="builtin", max_symbols=3)

    assert 1 <= len(result["focus_map"]) <= 3


def test_index_state_heuristic(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"src/foo.py": "class Foo:\n    pass\n"})

    initialized, fresh, _ = index_state(project)
    assert initialized is False and fresh is False

    build_index_state(project, fresh=True)
    initialized, fresh, _ = index_state(project)
    assert initialized is True and fresh is True

    build_index_state(project, fresh=False)
    initialized, fresh, _ = index_state(project)
    assert initialized is True and fresh is False


def test_index_state_initialized_without_source_json(tmp_path: Path) -> None:
    """codegraph 1.5.0 never writes source.json; codegraph.db alone must count (#192)."""
    project = make_project(tmp_path, {"src/foo.py": "class Foo:\n    pass\n"})
    codegraph_dir = project / ".codegraph"
    codegraph_dir.mkdir(exist_ok=True)
    (codegraph_dir / "codegraph.db").touch()

    initialized, _, _ = index_state(project)
    assert initialized is True


def test_codegraph_caps_impact_queries_on_full_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full-project scan (no --changed) must not run an unbounded number of
    codegraph impact subprocesses — regression for the timeout seen on real
    repos with hundreds of symbols (issue #167 review note N9)."""
    project = make_project(
        tmp_path,
        {f"src/mod{i}.py": f"def f{i}():\n    return {i}\n" for i in range(30)},
    )
    bin_path = make_fake_codegraph_bin(tmp_path)
    env = {"CODE_UNDERSTANDING_CODEGRAPH_BIN": str(bin_path)}

    from obsidian_wiki.code_understanding_codegraph import CodeGraphProvider

    impact_calls: list[str] = []
    real_query = CodeGraphProvider._query

    def spy_query(self, command: str, symbol: str, warnings: list[str]):
        if command == "impact":
            impact_calls.append(symbol)
        return real_query(self, command, symbol, warnings)

    monkeypatch.setattr(CodeGraphProvider, "_query", spy_query)

    code_understand(project, backend_flag="codegraph", env=env)

    assert len(impact_calls) <= 25
