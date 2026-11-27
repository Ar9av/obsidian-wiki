"""Subprocess tests for the `code-understand` CLI command (issue #167).

These were written RED-first, before the subcommand existed; the wiring landed
in fd30720 and they are green now. They pin the exact CLI contract:

    obsidian-wiki code-understand [--project <dir>] [--backend auto|builtin|codegraph]
        [--changed <file> ...] [--since <sha>] [--max-symbols N] [--pretty]

Every invocation is a real subprocess (`python -m obsidian_wiki.cli`) via the
conftest `_run_cli` helper, so these tests lock the observable contract — exit
codes, JSON shape on stdout, and stderr messages — not any internal function.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from conftest import (
    _run_cli,
    make_fake_codegraph_bin,
    make_project,
    make_repo_two_commits,
)

# Minimal PATH so the code-understanding provider can never find a real
# codegraph on the machine running the tests. /usr/bin:/bin keeps `git` (and
# the absolute sys.executable used to launch the CLI) working while excluding
# any user/brew/.omo install of codegraph. `which codegraph` fails on the dev
# machine (vendored bin lives under ~/.omo but not on PATH), so this is belt
# and suspenders for CI machines that do have codegraph on PATH.
_NO_CODEGRAPH_PATH = "/usr/bin:/bin"


def _no_codegraph_env() -> dict[str, str]:
    return {"PATH": _NO_CODEGRAPH_PATH, "CODE_UNDERSTANDING_CODEGRAPH_BIN": ""}


def _mini_project(tmp_path: Path) -> Path:
    return make_project(tmp_path, {"src/foo.py": "class Foo:\n    pass\n"})


def test_code_understand_builtin_json_shape(tmp_path: Path) -> None:
    project = _mini_project(tmp_path)

    proc = _run_cli(
        project, "code-understand", "--backend", "builtin", "--project", str(project)
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["backend"] == "builtin"
    assert isinstance(data["focus_map"], list)
    for item in data["focus_map"]:
        assert "file" in item
        assert "lines" in item


def test_code_understand_accepts_changed_files(tmp_path: Path) -> None:
    project = _mini_project(tmp_path)

    proc = _run_cli(
        project,
        "code-understand",
        "--backend",
        "builtin",
        "--project",
        str(project),
        "--changed",
        "src/foo.py",
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert "src/foo.py" in data["seed_files"]


def test_code_understand_since_delta(tmp_path: Path) -> None:
    project, sha_first = make_repo_two_commits(tmp_path)

    proc = _run_cli(
        project,
        "code-understand",
        "--backend",
        "builtin",
        "--project",
        str(project),
        "--since",
        sha_first,
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    # Only src/foo.py (modified) and src/bar.py (added) change after sha_first.
    assert set(data["seed_files"]) == {"src/foo.py", "src/bar.py"}


def test_code_understand_explicit_codegraph_broken_returns_1(tmp_path: Path) -> None:
    project = _mini_project(tmp_path)

    proc = _run_cli(
        project,
        "code-understand",
        "--project",
        str(project),
        env_overrides={
            "CODE_UNDERSTANDING_BACKEND": "codegraph",
            **_no_codegraph_env(),
        },
    )

    assert proc.returncode == 1
    assert "codegraph" in proc.stderr.lower()


def test_code_understand_auto_falls_back_when_codegraph_absent(tmp_path: Path) -> None:
    project = _mini_project(tmp_path)

    proc = _run_cli(
        project,
        "code-understand",
        "--project",
        str(project),
        env_overrides={
            "CODE_UNDERSTANDING_BACKEND": "auto",
            **_no_codegraph_env(),
        },
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["backend"] == "builtin"
    assert data["warnings"]


def test_code_understand_codegraph_via_bin_env(tmp_path: Path) -> None:
    project = _mini_project(tmp_path)
    bin_path = make_fake_codegraph_bin(tmp_path)

    proc = _run_cli(
        project,
        "code-understand",
        "--project",
        str(project),
        env_overrides={
            **_no_codegraph_env(),
            "CODE_UNDERSTANDING_BACKEND": "codegraph",
            "CODE_UNDERSTANDING_CODEGRAPH_BIN": str(bin_path),
        },
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["backend"] == "codegraph"


def test_code_understand_bad_project_returns_1(tmp_path: Path) -> None:
    proc = _run_cli(
        tmp_path,
        "code-understand",
        "--backend",
        "builtin",
        "--project",
        "/nonexistent/xyz",
    )

    assert proc.returncode == 1
    assert "project" in proc.stderr.lower()


def test_code_understand_pretty_flag(tmp_path: Path) -> None:
    project = _mini_project(tmp_path)

    proc = _run_cli(
        project,
        "code-understand",
        "--backend",
        "builtin",
        "--project",
        str(project),
        "--pretty",
    )

    assert proc.returncode == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(proc.stdout)
    assert "backend" in proc.stdout


def _marker_bin(tmp_path: Path, marker: Path) -> Path:
    """An executable that only records that it ran (stands in for a hostile
    program committed to the analysed repository)."""
    script = tmp_path / "evil" / "codegraph"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f"#!/bin/sh\necho ran > '{marker}'\nexit 1\n", encoding="utf-8")
    script.chmod(0o755)
    return script


@pytest.mark.skipif(os.name == "nt", reason="needs a shebang executable")
def test_code_understand_ignores_codegraph_bin_from_project_env(tmp_path: Path) -> None:
    """GHSA-334c-x34r-49fv: a repository's .env must not choose the program
    that code-understand executes. The backend choice is still honoured, but
    the binary comes only from the user's environment or global config."""
    project = _mini_project(tmp_path)
    marker = tmp_path / "marker"
    evil = _marker_bin(tmp_path, marker)
    (project / ".env").write_text(
        f'CODE_UNDERSTANDING_BACKEND="codegraph"\n'
        f'CODE_UNDERSTANDING_CODEGRAPH_BIN="{evil}"\n',
        encoding="utf-8",
    )
    bin_path = make_fake_codegraph_bin(tmp_path)
    home = tmp_path / "home"
    (home / ".obsidian-wiki").mkdir(parents=True)
    (home / ".obsidian-wiki" / "config").write_text(
        f'CODE_UNDERSTANDING_CODEGRAPH_BIN="{bin_path}"\n', encoding="utf-8"
    )

    proc = _run_cli(
        project,
        "code-understand",
        "--project",
        str(project),
        env_overrides={
            "HOME": str(home),
            "PATH": _NO_CODEGRAPH_PATH,
            "CODE_UNDERSTANDING_BACKEND": "",
            "CODE_UNDERSTANDING_CODEGRAPH_BIN": "",
        },
    )

    assert not marker.exists(), "program named by the project .env was executed"
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["backend"] == "codegraph"


@pytest.mark.skipif(os.name == "nt", reason="needs a shebang executable")
def test_code_understand_project_relative_bin_never_runs(tmp_path: Path) -> None:
    """The PoC shape: .env points at ./tools/codegraph inside the checkout."""
    project = _mini_project(tmp_path)
    marker = tmp_path / "marker"
    tool = project / "tools" / "codegraph"
    tool.parent.mkdir()
    tool.write_text(f"#!/bin/sh\necho ran > '{marker}'\n", encoding="utf-8")
    tool.chmod(0o755)
    (project / ".env").write_text("CODE_UNDERSTANDING_CODEGRAPH_BIN=./tools/codegraph\n", encoding="utf-8")

    proc = _run_cli(
        tmp_path,
        "code-understand",
        "--project",
        str(project),
        env_overrides={
            "HOME": str(tmp_path / "home"),
            "PATH": _NO_CODEGRAPH_PATH,
            "CODE_UNDERSTANDING_BACKEND": "",
            "CODE_UNDERSTANDING_CODEGRAPH_BIN": "",
        },
    )

    assert not marker.exists()
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["backend"] == "builtin"


def test_code_understand_backend_from_global_config(tmp_path: Path) -> None:
    """RED: backend resolution must consult ~/.obsidian-wiki/config.

    With both env vars unset and no project `.env`, the resolver should fall
    through to the global config under $HOME/.obsidian-wiki/config (backend
    "codegraph" + fake bin). Current cli.py ignores the config file, so the
    backend resolves to "builtin" and this test fails until the chain lands.
    """
    project = _mini_project(tmp_path)
    bin_path = make_fake_codegraph_bin(tmp_path)
    home = tmp_path / "home"
    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir(parents=True)
    (config_dir / "config").write_text(
        f'CODE_UNDERSTANDING_BACKEND="codegraph"\n'
        f'CODE_UNDERSTANDING_CODEGRAPH_BIN="{bin_path}"\n',
        encoding="utf-8",
    )

    proc = _run_cli(
        project,
        "code-understand",
        "--project",
        str(project),
        env_overrides={
            "HOME": str(home),
            "PATH": _NO_CODEGRAPH_PATH,
            "CODE_UNDERSTANDING_BACKEND": "",
            "CODE_UNDERSTANDING_CODEGRAPH_BIN": "",
        },
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["backend"] == "codegraph"


def test_code_understand_backend_flag_beats_project_env(tmp_path: Path) -> None:
    """GREEN regression guard: explicit --backend beats .env config.

    Once the config-resolution chain lands (project .env wins over env
    fallback), an explicit `--backend builtin` must still take precedence over
    the project `.env` that would otherwise select codegraph.
    """
    project = _mini_project(tmp_path)
    bin_path = make_fake_codegraph_bin(tmp_path)
    (project / ".env").write_text(
        f'CODE_UNDERSTANDING_BACKEND="codegraph"\n'
        f'CODE_UNDERSTANDING_CODEGRAPH_BIN="{bin_path}"\n',
        encoding="utf-8",
    )

    proc = _run_cli(
        project,
        "code-understand",
        "--backend",
        "builtin",
        "--project",
        str(project),
        env_overrides={
            "PATH": _NO_CODEGRAPH_PATH,
            "CODE_UNDERSTANDING_BACKEND": "",
            "CODE_UNDERSTANDING_CODEGRAPH_BIN": "",
        },
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["backend"] == "builtin"
