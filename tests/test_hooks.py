"""Tests for the session-hook installer (`obsidian_wiki.hooks`).

The property that matters: a normal install must actually get both hooks,
without ever damaging a user's own Claude Code settings. Every test runs
against a throwaway HOME.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from obsidian_wiki import hooks as hk


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def _settings(home: Path) -> dict:
    return json.loads(hk.settings_path(home).read_text(encoding="utf-8"))


def _commands(home: Path, event: str) -> list:
    return hk._registered_commands(_settings(home), event)


def test_both_hooks_are_bundled_and_executable() -> None:
    for _event, name in hk.HOOKS:
        script = hk.hook_script(name)
        assert script is not None, f"{name} not found in the package or checkout"
        assert script.stat().st_mode & 0o111, f"{name} is not executable"


def test_install_registers_both_hooks_on_a_fresh_home(home: Path) -> None:
    result = hk.install(home)
    assert sorted(result["added"]) == sorted(name for _, name in hk.HOOKS)
    assert result["missing"] == []
    for event, name in hk.HOOKS:
        assert any(name in command for command in _commands(home, event))


def test_install_is_idempotent(home: Path) -> None:
    hk.install(home)
    before = _settings(home)
    result = hk.install(home)
    assert result["added"] == []
    assert sorted(result["already"]) == sorted(name for _, name in hk.HOOKS)
    assert _settings(home) == before


def test_install_appends_and_never_clobbers_a_users_own_hook(home: Path) -> None:
    path = hk.settings_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "permissions": {"allow": ["Bash(ls)"]},
        "hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "echo mine"}]}]},
    }), encoding="utf-8")

    hk.install(home)
    data = _settings(home)
    assert data["permissions"] == {"allow": ["Bash(ls)"]}, "unrelated settings must survive"
    stop = _commands(home, "Stop")
    assert any("echo mine" in command for command in stop)
    assert sum("wiki-stop-capture" in command for command in stop) == 1


def test_a_hook_registered_under_another_path_counts_as_registered(home: Path) -> None:
    """The repo's own settings.json uses a relative path; don't double-register."""
    path = hk.settings_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"hooks": {"SessionStart": [
        {"matcher": "", "hooks": [{"type": "command", "command": "bash .claude/hooks/wiki-session-recap.sh"}]}
    ]}}), encoding="utf-8")
    result = hk.install(home)
    assert "wiki-session-recap.sh" in result["already"]
    assert sum("wiki-session-recap" in c for c in _commands(home, "SessionStart")) == 1


def test_uninstall_removes_only_ours(home: Path) -> None:
    hk.install(home)
    path = hk.settings_path(home)
    data = _settings(home)
    data["hooks"]["Stop"].append({"matcher": "", "hooks": [{"type": "command", "command": "echo mine"}]})
    path.write_text(json.dumps(data), encoding="utf-8")

    result = hk.uninstall(home)
    assert sorted(result["removed"]) == sorted(name for _, name in hk.HOOKS)
    data = _settings(home)
    assert "SessionStart" not in data["hooks"]
    assert _commands(home, "Stop") == ["echo mine"]


def test_uninstall_on_a_clean_home_is_a_noop(home: Path) -> None:
    assert hk.uninstall(home)["removed"] == []
    assert not hk.settings_path(home).exists()


def test_only_limits_the_action_to_one_event(home: Path) -> None:
    result = hk.install(home, only="SessionStart")
    assert result["added"] == ["wiki-session-recap.sh"]
    assert "Stop" not in _settings(home)["hooks"]


def test_malformed_settings_are_refused_not_overwritten(home: Path) -> None:
    path = hk.settings_path(home)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        hk.install(home)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_status_reports_each_hook(home: Path) -> None:
    assert [e.registered for e in hk.status(home)] == [False, False]
    hk.install(home)
    entries = hk.status(home)
    assert all(e.registered and e.bundled and e.executable for e in entries)
    assert [e.event for e in entries] == ["SessionStart", "Stop"]


def test_reachability_reports_a_path_the_hook_can_use() -> None:
    reach = hk.reachability()
    # In the test interpreter the package is importable by definition; the
    # contract is that the dict says how, not that it is always true.
    assert set(reach) >= {"console_script", "python3_can_import", "reachable", "hint"}
    assert isinstance(reach["reachable"], bool)
    assert (reach["hint"] == "") == reach["reachable"]


def test_cli_status_exits_nonzero_until_installed(home: Path) -> None:
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    before = subprocess.run([sys.executable, "-m", "obsidian_wiki.cli", "hooks", "status"],
                            capture_output=True, text=True, env=env)
    assert before.returncode == 1
    assert "NOT registered" in before.stdout

    installed = subprocess.run([sys.executable, "-m", "obsidian_wiki.cli", "hooks", "install", "--json"],
                               capture_output=True, text=True, env=env)
    assert installed.returncode == 0, installed.stderr
    assert json.loads(installed.stdout)["added"]

    after = subprocess.run([sys.executable, "-m", "obsidian_wiki.cli", "hooks", "status", "--json"],
                           capture_output=True, text=True, env=env)
    data = json.loads(after.stdout)
    assert all(entry["registered"] for entry in data["hooks"])


def test_memory_and_hooks_commands_do_not_print_the_stale_install_nag(home: Path, tmp_path: Path) -> None:
    """Those commands run from the SessionStart hook and from every write
    skill; a two-line warning on each call was noise, not signal."""
    vault = tmp_path / "vault"
    vault.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    for args in (["memory", "status", "--vault", str(vault)], ["hooks", "status"]):
        proc = subprocess.run([sys.executable, "-m", "obsidian_wiki.cli", *args],
                              capture_output=True, text=True, env=env)
        assert "setup has never been run" not in proc.stderr, args
        assert "Run: obsidian-wiki setup" not in proc.stderr, args


def test_setup_registers_the_hooks_by_default(tmp_path: Path) -> None:
    """Registration used to be a separate step people did not know about."""
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    proc = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "setup",
         "--vault", str(tmp_path / "brain"), "--project-only"],
        capture_output=True, text=True, env=env, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Session hooks:" in proc.stdout
    assert all(entry.registered for entry in hk.status(home))


def test_setup_honours_no_hooks(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    proc = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "setup",
         "--vault", str(tmp_path / "brain"), "--project-only", "--no-hooks"],
        capture_output=True, text=True, env=env, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert "skipped (--no-hooks)" in proc.stdout
    assert not any(entry.registered for entry in hk.status(home))
