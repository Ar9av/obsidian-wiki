"""Profile-scoped native Hermes installs; never touch real agent profiles."""
from pathlib import Path
import subprocess

import pytest

import obsidian_wiki.cli as cli
from obsidian_wiki import hermes_install


def test_hermes_native_install_uses_target_env_and_fork(tmp_path, monkeypatch):
    home = tmp_path / "profile with spaces"
    home.mkdir()
    calls = []
    monkeypatch.setattr(hermes_install.shutil, "which", lambda name: "C:/Program Files/Hermes/hermes.exe")
    def run(command, **kwargs):
        calls.append((command, kwargs))
        target = home / "skills" / "wiki-query"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("installed by Hermes", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(hermes_install.subprocess, "run", run)
    assert cli.main(["install-hermes", "--hermes-home", str(home), "--source", "forgegod/Ar9av-obsidian-wiki", "--skill", "wiki-query"]) == 0
    command, options = calls[0]
    assert command == ["C:/Program Files/Hermes/hermes.exe", "skills", "install", "https://raw.githubusercontent.com/forgegod/Ar9av-obsidian-wiki/HEAD/skills/wiki-query/SKILL.md", "--name", "wiki-query"]
    assert options["env"]["HERMES_HOME"] == str(home.resolve())
    assert options["env"]["HERMES_PROFILE"] == ""
    assert options.get("shell", False) is False
    assert sorted(p.name for p in home.iterdir()) == ["skills"]


def test_hermes_dry_run_is_profile_scoped(tmp_path, monkeypatch, capsys):
    home = tmp_path / "Hermes profile with spaces"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    result = cli.main(["install-hermes", "--dry-run", "--skill", "wiki-query"])
    assert result == 0
    output = capsys.readouterr().out
    assert str(home) in output
    assert "Ar9av/obsidian-wiki/HEAD/skills/wiki-query/SKILL.md" in output
    assert list(home.iterdir()) == []


@pytest.mark.parametrize("source", ["../repo", "owner/repo/branch", "https://github.com/a/b", "a/-bad", "a/.."])
def test_invalid_source_is_rejected_before_execution(tmp_path, monkeypatch, source):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert cli.main(["install-hermes", "--source", source, "--dry-run"]) == 1


@pytest.mark.parametrize("target", ["", "relative/profile", "missing"])
def test_explicit_existing_absolute_home_required(tmp_path, monkeypatch, target):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    argv = ["install-hermes", "--dry-run"]
    if target:
        argv += ["--hermes-home", str(tmp_path / "absent") if target == "missing" else target]
    assert cli.main(argv) == 1


def test_existing_copy_is_not_overwritten(tmp_path, monkeypatch):
    skill = tmp_path / "skills" / "wiki-query"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("my edits", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert cli.main(["install-hermes", "--skill", "wiki-query"]) == 1
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == "my edits"


def test_missing_cli_is_actionable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(hermes_install.shutil, "which", lambda name: None)
    assert cli.main(["install-hermes", "--skill", "wiki-query"]) == 1
    assert "PATH" in capsys.readouterr().err


def test_failed_skill_does_not_stop_batch(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(hermes_install.shutil, "which", lambda name: "hermes")
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        name = command[5]
        if name == "wiki-update":  # Hermes blocks a scan verdict but exits 0
            target = tmp_path / "skills" / name
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("installed", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0 if name == "wiki-update" else 7)
    monkeypatch.setattr(hermes_install.subprocess, "run", run)
    assert cli.main(["install-hermes", "--skill", "wiki-query", "--skill", "wiki-update", "--skill", "wiki-lint"]) == 1
    assert [c[5] for c in calls] == ["wiki-query", "wiki-update", "wiki-lint"]
    captured = capsys.readouterr()
    assert "Installed 1/3" in captured.out
    assert "--skill wiki-query --skill wiki-lint" in captured.err


def test_launch_error_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(hermes_install.shutil, "which", lambda name: "hermes")
    def run(*args, **kwargs):
        raise OSError("cannot start")
    monkeypatch.setattr(hermes_install.subprocess, "run", run)
    assert cli.main(["install-hermes", "--skill", "wiki-query"]) == 1


def test_vault_only_setup_skips_agent_installs_hooks_and_sync(tmp_path, monkeypatch):
    config_dir = tmp_path / "wiki config"
    monkeypatch.setattr(cli, "GLOBAL_CONFIG_DIR", config_dir)
    monkeypatch.setattr(cli, "GLOBAL_CONFIG", config_dir / "config")
    def forbidden(*args, **kwargs):
        pytest.fail("vault-only setup touched an agent or sync")
    monkeypatch.setattr(cli, "install_global_skills", forbidden)
    monkeypatch.setattr(cli, "install_project", forbidden)
    monkeypatch.setattr(cli, "_maybe_configure_sync", forbidden)
    from obsidian_wiki import hooks
    monkeypatch.setattr(hooks, "install", forbidden)
    vault = tmp_path / "vault"
    assert cli.main(["setup", "--vault-only", "--vault", str(vault)]) == 0
    assert (vault / "index.md").is_file()
    assert "OBSIDIAN_WIKI_REPO=" in (config_dir / "config").read_text(encoding="utf-8")


def test_vault_only_rejects_project_flags_before_writes(tmp_path, monkeypatch):
    config_dir = tmp_path / "wiki config"
    monkeypatch.setattr(cli, "GLOBAL_CONFIG_DIR", config_dir)
    assert cli.main(["setup", "--vault-only", "--project", str(tmp_path)]) == 1
    assert not config_dir.exists()


@pytest.mark.parametrize("name", ["../escape", "not-a-wiki-skill"])
def test_unknown_skill_is_rejected(tmp_path, monkeypatch, name):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert cli.main(["install-hermes", "--skill", name, "--dry-run"]) == 1


def test_success_requires_installed_skill_readback(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(hermes_install.shutil, "which", lambda name: "hermes")
    monkeypatch.setattr(hermes_install.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0))
    assert cli.main(["install-hermes", "--skill", "wiki-query"]) == 1


def test_yes_preserves_native_scan_without_force(tmp_path, monkeypatch):
    home = tmp_path
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(hermes_install.shutil, "which", lambda name: "hermes")
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        target = home / "skills" / "wiki-query"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("installed", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(hermes_install.subprocess, "run", run)
    assert cli.main(["install-hermes", "--skill", "wiki-query", "--yes"]) == 0
    assert calls[0][-1] == "--yes"
    assert calls[0][4:6] == ["--name", "wiki-query"]
    assert "--force" not in calls[0]


def test_full_batch_preflight_catches_later_collision(tmp_path, monkeypatch):
    (tmp_path / "skills" / "wiki-update").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    def forbidden(*args, **kwargs):
        pytest.fail("batch executed before preflight completed")
    monkeypatch.setattr(hermes_install.subprocess, "run", forbidden)
    assert cli.main(["install-hermes", "--skill", "wiki-query", "--skill", "wiki-update"]) == 1
