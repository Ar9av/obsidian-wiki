"""Tests for GitHub vault sync (obsidian_wiki/sync.py).

Regression coverage for issue #153: setup.sh had a git-sync flow the pip/uv
CLI (`obsidian-wiki setup`) never got, so pip/uv installs silently skipped it.
sync.py is now the single implementation both entrypoints call into.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from obsidian_wiki.sync import configure_sync, get_remote, run_sync


def _git(repo_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo_dir), *args], check=True,
                           capture_output=True, text=True)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    return v


@pytest.fixture
def remote_repo(tmp_path):
    """A bare repo to act as a real push target."""
    r = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(r)], check=True)
    return r


class TestGetRemote:
    def test_not_a_git_repo(self, vault):
        assert get_remote(vault) is None

    def test_no_origin_set(self, vault):
        _git(vault, "init", "-q")
        assert get_remote(vault) is None

    def test_returns_configured_remote(self, vault):
        _git(vault, "init", "-q")
        _git(vault, "remote", "add", "origin", "https://example.com/x.git")
        assert get_remote(vault) == "https://example.com/x.git"


class TestConfigureSync:
    def test_missing_vault_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            configure_sync(tmp_path / "nope", "https://example.com/x.git")

    def test_blank_remote_raises(self, vault):
        with pytest.raises(ValueError):
            configure_sync(vault, "   ")

    def test_inits_git_repo(self, vault):
        configure_sync(vault, "https://example.com/x.git")
        assert (vault / ".git").is_dir()

    def test_does_not_reinit_existing_repo(self, vault):
        _git(vault, "init", "-q")
        (vault / "existing.md").write_text("keep me")
        _git(vault, "add", "-A")
        _git(vault, "commit", "-q", "-m", "seed")
        configure_sync(vault, "https://example.com/x.git")
        log = _git(vault, "log", "--oneline").stdout
        assert "seed" in log

    def test_writes_gitignore(self, vault):
        configure_sync(vault, "https://example.com/x.git")
        content = (vault / ".gitignore").read_text()
        assert ".obsidian/workspace.json" in content
        assert ".trash/" in content

    def test_does_not_overwrite_existing_gitignore(self, vault):
        vault.mkdir(exist_ok=True)
        (vault / ".gitignore").write_text("custom-rule/\n")
        configure_sync(vault, "https://example.com/x.git")
        assert (vault / ".gitignore").read_text() == "custom-rule/\n"

    def test_sets_remote(self, vault):
        configure_sync(vault, "https://example.com/x.git")
        assert get_remote(vault) == "https://example.com/x.git"

    def test_updates_existing_remote(self, vault):
        configure_sync(vault, "https://example.com/old.git")
        configure_sync(vault, "https://example.com/new.git")
        assert get_remote(vault) == "https://example.com/new.git"

    def test_returns_confirmation_messages(self, vault):
        messages = configure_sync(vault, "https://example.com/x.git")
        joined = " ".join(messages)
        assert "Initialized git repo" in joined
        assert "https://example.com/x.git" in joined


class TestRunSync:
    def test_vault_missing(self, tmp_path):
        code, message = run_sync(tmp_path / "nope")
        assert code == 1
        assert "not found" in message

    def test_not_a_git_repo(self, vault):
        code, message = run_sync(vault)
        assert code == 1
        assert "sync-setup" in message

    def test_nothing_to_commit(self, vault):
        _git(vault, "init", "-q")
        code, message = run_sync(vault)
        assert code == 0
        assert "nothing to commit" in message

    def test_commits_and_pushes(self, vault, remote_repo):
        configure_sync(vault, str(remote_repo))
        _git(vault, "config", "user.email", "test@example.com")
        _git(vault, "config", "user.name", "Test")
        (vault / "note.md").write_text("hello")
        code, message = run_sync(vault)
        assert code == 0
        assert "pushed to" in message
        log = _git(vault, "log", "--oneline").stdout
        assert "sync " in log

    def test_second_run_with_no_changes_is_clean(self, vault, remote_repo):
        configure_sync(vault, str(remote_repo))
        _git(vault, "config", "user.email", "test@example.com")
        _git(vault, "config", "user.name", "Test")
        (vault / "note.md").write_text("hello")
        run_sync(vault)
        code, message = run_sync(vault)
        assert code == 0
        assert "nothing to commit" in message
