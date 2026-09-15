"""Tests for doctor's versions.latest check (no live network, ever).

Upstream responses are simulated with committed fixtures under
tests/fixtures/doctor/ (via OBSIDIAN_WIKI_LATEST_FIXTURE for CLI-level
tests) or an injected version_fetcher for in-process tests.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import obsidian_wiki.cli as cli
from obsidian_wiki import __version__ as installed_version
from obsidian_wiki.cli import list_skills, run_doctor

FIXTURES = Path(__file__).parent / "fixtures" / "doctor"


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _run_env(
    home: Path, env_overrides: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _write_config(home: Path, vault: Path) -> None:
    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(f'OBSIDIAN_VAULT_PATH="{vault}"\n', encoding="utf-8")


def _make_vault(vault: Path) -> None:
    vault.mkdir(parents=True, exist_ok=True)
    for name in ("index.md", "log.md", "hot.md"):
        (vault / name).write_text(f"# {name}\n", encoding="utf-8")
    (vault / ".manifest.json").write_text('{"sources": {}}', encoding="utf-8")


def _install_all_skills(home: Path) -> None:
    target = home / ".claude" / "skills"
    target.mkdir(parents=True, exist_ok=True)
    for name in list_skills():
        skill_dir = target / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")


def _setup(home: Path, vault: Path) -> None:
    _make_vault(vault)
    _write_config(home, vault)
    _install_all_skills(home)


def _latest_check(data: dict) -> dict:
    return next(c for c in data["checks"] if c["name"] == "versions.latest")


# ── CLI-level tests (fixture override) ──────────────────────────────────────


def test_meta_nullable_without_flag(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _setup(home, tmp_path / "vault")

    proc = _run(home, "doctor", "--json")

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["meta"]["latest_version"] is None
    assert data["meta"]["latest_checked_at"] is None
    assert data["meta"]["latest_source"] is None
    check = _latest_check(data)
    assert check["status"] == "info"


def test_human_output_suppresses_unchecked_line(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _setup(home, tmp_path / "vault")

    proc = _run(home, "doctor")

    assert proc.returncode == 0
    assert "versions.latest" not in proc.stdout


def test_behind_via_fixture_warns_but_exits_zero(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _setup(home, tmp_path / "vault")
    env = {"OBSIDIAN_WIKI_LATEST_FIXTURE": str(FIXTURES / "pypi-behind.json")}

    proc = _run_env(home, env, "doctor", "--json", "--check-updates")

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    check = _latest_check(data)
    assert check["status"] == "warn"
    assert "behind latest 2999.1.1" in check["detail"]
    assert "pip install -U" in check["hint"]
    assert data["meta"]["latest_version"] == "2999.1.1"
    assert data["meta"]["latest_source"] == "fixture"
    assert data["meta"]["latest_checked_at"]


def test_behind_strict_exits_nonzero(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _setup(home, tmp_path / "vault")
    env = {"OBSIDIAN_WIKI_LATEST_FIXTURE": str(FIXTURES / "pypi-behind.json")}

    proc = _run_env(home, env, "doctor", "--json", "--check-updates", "--strict")

    assert proc.returncode == 1


def test_behind_human_output_shows_warn_line(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _setup(home, tmp_path / "vault")
    env = {"OBSIDIAN_WIKI_LATEST_FIXTURE": str(FIXTURES / "pypi-behind.json")}

    proc = _run_env(home, env, "doctor", "--check-updates")

    assert proc.returncode == 0
    assert "versions.latest" in proc.stdout
    assert "pip install -U" in proc.stdout


def test_fresh_cache_used_without_flag_or_network(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _setup(home, tmp_path / "vault")
    env = {"OBSIDIAN_WIKI_LATEST_FIXTURE": str(FIXTURES / "pypi-behind.json")}
    first = _run_env(home, env, "doctor", "--json", "--check-updates")
    assert first.returncode == 0
    assert (home / ".obsidian-wiki" / "version-check.json").is_file()

    # No fixture, no flag: must report behind from the fresh cache alone.
    second = _run(home, "doctor", "--json")

    assert second.returncode == 0
    data = json.loads(second.stdout)
    check = _latest_check(data)
    assert check["status"] == "warn"
    assert data["meta"]["latest_version"] == "2999.1.1"


def test_current_via_fixture_is_info(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _setup(home, tmp_path / "vault")
    fixture = tmp_path / "pypi-current.json"
    fixture.write_text(json.dumps({"info": {"version": installed_version}}), encoding="utf-8")

    proc = _run_env(
        home,
        {"OBSIDIAN_WIKI_LATEST_FIXTURE": str(fixture)},
        "doctor",
        "--json",
        "--check-updates",
        "--strict",
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    check = _latest_check(data)
    assert check["status"] == "info"
    assert "matches latest" in check["detail"]


def test_malformed_fixture_fails_open(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _setup(home, tmp_path / "vault")
    env = {"OBSIDIAN_WIKI_LATEST_FIXTURE": str(FIXTURES / "pypi-malformed.json")}

    proc = _run_env(home, env, "doctor", "--json", "--check-updates", "--strict")

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    check = _latest_check(data)
    assert check["status"] == "info"
    assert "unavailable" in check["detail"]
    assert "fail" not in {c["status"] for c in data["checks"]}
    assert data["meta"]["latest_version"] is None


# ── In-process tests (injected fetcher) ─────────────────────────────────────


def test_no_fetch_without_flag(tmp_path: Path) -> None:
    calls: list[str] = []

    def _recorder() -> str:
        calls.append("fetch")
        return "2999.1.1"

    report = run_doctor(
        check_updates=False,
        version_fetcher=_recorder,
        version_cache_path=tmp_path / "version-check.json",
    )

    assert calls == []
    assert report["meta"]["latest_version"] is None
    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert check["status"] == "info"


def test_fetcher_timeout_fails_open(tmp_path: Path) -> None:
    def _timeout() -> str:
        raise TimeoutError("timed out")

    report = run_doctor(
        check_updates=True,
        version_fetcher=_timeout,
        version_cache_path=tmp_path / "version-check.json",
    )

    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert check["status"] == "info"
    assert "unavailable" in check["detail"]
    assert "fail" not in {c["status"] for c in report["checks"] if c["name"] == "versions.latest"}
    assert report["meta"]["latest_version"] is None


def test_fetcher_garbage_fails_open(tmp_path: Path) -> None:
    report = run_doctor(
        check_updates=True,
        version_fetcher=lambda: "not a version!!!",
        version_cache_path=tmp_path / "version-check.json",
    )

    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert check["status"] == "info"
    assert report["meta"]["latest_version"] is None


def test_v_prefix_and_calver_normalize_equal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "__version__", "2026.9.1")

    report = run_doctor(
        check_updates=True,
        version_fetcher=lambda: "v2026.09.1",
        version_cache_path=tmp_path / "version-check.json",
    )

    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert check["status"] == "info"
    assert "matches latest" in check["detail"]


def test_newer_than_upstream_is_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "__version__", "2030.1.1")

    report = run_doctor(
        check_updates=True,
        version_fetcher=lambda: "2026.9.1",
        version_cache_path=tmp_path / "version-check.json",
    )

    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert check["status"] == "info"
    assert "newer than latest" in check["detail"]


def test_github_fallback_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    monkeypatch.setattr(cli, "__version__", "2026.9.1")

    def _fake_get(url: str, _timeout: float) -> object:
        if "pypi.org" in url:
            raise urllib.error.URLError("connection refused")
        return {"tag_name": "v2026.10.5"}

    monkeypatch.setattr(cli, "_http_get_json", _fake_get)

    report = run_doctor(
        check_updates=True,
        version_cache_path=tmp_path / "version-check.json",
    )

    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert check["status"] == "warn"
    assert report["meta"]["latest_source"] == "github"
    assert report["meta"]["latest_version"] == "v2026.10.5"


def test_stale_cache_triggers_refetch(tmp_path: Path) -> None:
    cache = tmp_path / "version-check.json"
    cache.write_text(
        json.dumps({
            "latest": "2000.1.1",
            "fetched_at": "2000-01-01T00:00:00+00:00",
            "source": "pypi",
        }),
        encoding="utf-8",
    )
    calls: list[str] = []

    def _fetcher() -> str:
        calls.append("fetch")
        return "2999.1.1"

    report = run_doctor(
        check_updates=True, version_fetcher=_fetcher, version_cache_path=cache
    )

    assert calls == ["fetch"]
    assert report["meta"]["latest_version"] == "2999.1.1"


def test_fresh_cache_skips_fetcher(tmp_path: Path) -> None:
    cache = tmp_path / "version-check.json"
    report = run_doctor(
        check_updates=True,
        version_fetcher=lambda: "2999.1.1",
        version_cache_path=cache,
    )
    assert report["meta"]["latest_version"] == "2999.1.1"

    calls: list[str] = []

    def _recorder() -> str:
        calls.append("fetch")
        return "2999.1.1"

    second = run_doctor(
        check_updates=True, version_fetcher=_recorder, version_cache_path=cache
    )

    assert calls == []
    assert second["meta"]["latest_version"] == "2999.1.1"


def _write_fresh_garbage_cache(cache: Path) -> None:
    from datetime import datetime, timezone

    cache.write_text(
        json.dumps({
            "latest": "not a version!!!",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "pypi",
        }),
        encoding="utf-8",
    )


def test_fresh_garbage_cache_fails_open_without_flag(tmp_path: Path) -> None:
    cache = tmp_path / "version-check.json"
    _write_fresh_garbage_cache(cache)
    calls: list[str] = []

    def _recorder() -> str:
        calls.append("fetch")
        return "2999.1.1"

    report = run_doctor(
        check_updates=False, version_fetcher=_recorder, version_cache_path=cache
    )

    assert calls == []
    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert check["status"] == "info"
    assert "unavailable" in check["detail"]
    assert report["meta"]["latest_version"] is None


def test_fresh_garbage_cache_fails_open_with_flag(tmp_path: Path) -> None:
    cache = tmp_path / "version-check.json"
    _write_fresh_garbage_cache(cache)

    def _failing() -> str:
        raise TimeoutError("timed out")

    report = run_doctor(
        check_updates=True, version_fetcher=_failing, version_cache_path=cache
    )

    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert check["status"] == "info"
    assert "unavailable" in check["detail"]
    assert "not a version" not in check["detail"]
    assert report["meta"]["latest_version"] is None


def test_fresh_garbage_cache_refetches_with_flag(tmp_path: Path) -> None:
    cache = tmp_path / "version-check.json"
    _write_fresh_garbage_cache(cache)

    report = run_doctor(
        check_updates=True,
        version_fetcher=lambda: "2999.1.1",
        version_cache_path=cache,
    )

    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert report["meta"]["latest_version"] == "2999.1.1"
    assert check["status"] in {"info", "warn"}


def test_tags_fallback_when_pypi_and_releases_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.error

    monkeypatch.setattr(cli, "__version__", "2026.9.1")

    def _fake_get(url: str, _timeout: float) -> object:
        if "pypi.org" in url or "releases/latest" in url:
            raise urllib.error.URLError("connection refused")
        return [{"name": "v2026.10.5"}]

    monkeypatch.setattr(cli, "_http_get_json", _fake_get)

    report = run_doctor(
        check_updates=True,
        version_cache_path=tmp_path / "version-check.json",
    )

    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert check["status"] == "warn"
    assert report["meta"]["latest_source"] == "github"
    assert report["meta"]["latest_version"] == "v2026.10.5"


def test_stale_cache_fallback_surfaces_on_fetch_failure(tmp_path: Path) -> None:
    cache = tmp_path / "version-check.json"
    cache.write_text(
        json.dumps({
            "latest": "2000.1.1",
            "fetched_at": "2000-01-01T00:00:00+00:00",
            "source": "pypi",
        }),
        encoding="utf-8",
    )

    def _failing() -> str:
        raise TimeoutError("timed out")

    report = run_doctor(
        check_updates=True, version_fetcher=_failing, version_cache_path=cache
    )

    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert check["status"] == "info"
    assert "last known latest 2000.1.1" in check["detail"]
    assert report["meta"]["latest_version"] == "2000.1.1"
    assert report["meta"]["latest_source"] == "pypi"


def test_cache_write_failure_still_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "__version__", "2026.9.1")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache = cache_dir / "version-check.json"
    os.chmod(cache_dir, 0o555)
    try:
        report = run_doctor(
            check_updates=True,
            version_fetcher=lambda: "2999.1.1",
            version_cache_path=cache,
        )
    finally:
        os.chmod(cache_dir, 0o755)

    check = next(c for c in report["checks"] if c["name"] == "versions.latest")
    assert check["status"] == "warn"
    assert report["meta"]["latest_version"] == "2999.1.1"
