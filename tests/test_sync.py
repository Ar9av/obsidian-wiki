"""Tests for GitHub vault sync (obsidian_wiki/sync.py).

Regression coverage for issue #153: setup.sh had a git-sync flow the pip/uv
CLI (`obsidian-wiki setup`) never got, so pip/uv installs silently skipped it.
sync.py is now the single implementation both entrypoints call into.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from obsidian_wiki.sync import configure_sync, get_remote, run_sync, run_undo


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
        _git(vault, "config", "user.email", "test@example.com")  # a bare machine has no identity
        _git(vault, "config", "user.name", "Test")
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

    def test_never_commits_env_or_plugin_keys(self, vault, remote_repo):
        configure_sync(vault, str(remote_repo))
        (vault / ".gitignore").write_text("# the user's own, without secret rules\n")
        _git(vault, "config", "user.email", "test@example.com")
        _git(vault, "config", "user.name", "Test")
        (vault / "note.md").write_text("hello")
        (vault / ".env").write_text("ANTHROPIC_API_KEY=sk-test")
        (vault / "sub").mkdir()
        (vault / "sub" / ".env.local").write_text("TOKEN=x")
        plugin = vault / ".obsidian" / "plugins" / "copilot"
        plugin.mkdir(parents=True)
        (plugin / "data.json").write_text('{"openAIApiKey": "sk-test"}')
        assert run_sync(vault)[0] == 0
        tracked = _git(vault, "ls-files").stdout.split()
        assert "note.md" in tracked
        assert not {".env", "sub/.env.local", ".obsidian/plugins/copilot/data.json"} & set(tracked)

    def test_never_commits_staged_uppercase_or_nested_secrets(self, vault, remote_repo):
        configure_sync(vault, str(remote_repo))
        (vault / ".gitignore").write_text("# no secret rules\n")
        _git(vault, "config", "user.email", "test@example.com")
        _git(vault, "config", "user.name", "Test")
        nested = "sub/.obsidian/plugins/x/data.json"
        (vault / nested).parent.mkdir(parents=True)
        for name in (".env", ".ENV.prod", nested):
            (vault / name).write_text("TOKEN=x")
        _git(vault, "add", ".env")
        (vault / "note.md").write_text("hello")
        assert run_sync(vault)[0] == 0
        tracked = _git(vault, "ls-files").stdout.split()
        assert "note.md" in tracked
        assert not {".env", ".ENV.prod", nested} & set(tracked)

    def test_staged_removal_of_a_tracked_env_still_goes_through(self, vault, remote_repo):
        configure_sync(vault, str(remote_repo))
        (vault / ".gitignore").write_text("# no secret rules\n")
        _git(vault, "config", "user.email", "test@example.com")
        _git(vault, "config", "user.name", "Test")
        (vault / ".env").write_text("TOKEN=x")
        _git(vault, "add", "-A")
        _git(vault, "commit", "-qm", "old")
        _git(vault, "rm", "-q", "--cached", ".env")
        assert run_sync(vault)[0] == 0
        assert ".env" not in _git(vault, "ls-files").stdout.split()
        assert (vault / ".env").exists()

    def test_undo_pending_leaves_env_alone(self, vault, remote_repo):
        configure_sync(vault, str(remote_repo))
        (vault / ".gitignore").write_text("# no secret rules\n")
        _git(vault, "config", "user.email", "test@example.com")
        _git(vault, "config", "user.name", "Test")
        assert run_sync(vault)[0] == 0
        (vault / ".env").write_text("TOKEN=x")
        assert run_undo(vault, pending=True)[0] == 1  # only a secret is dirty
        (vault / "note.md").write_text("hello")
        assert run_undo(vault, pending=True)[0] == 0
        assert (vault / ".env").read_text() == "TOKEN=x"
        assert not (vault / "note.md").exists()
        assert ".env" not in _git(vault, "log", "--all", "--name-only").stdout.split()

    def test_second_run_with_no_changes_is_clean(self, vault, remote_repo):
        configure_sync(vault, str(remote_repo))
        _git(vault, "config", "user.email", "test@example.com")
        _git(vault, "config", "user.name", "Test")
        (vault / "note.md").write_text("hello")
        run_sync(vault)
        code, message = run_sync(vault)
        assert code == 0
        assert "nothing to commit" in message


class TestRunUndo:
    @pytest.fixture
    def repo(self, vault):
        _git(vault, "init", "-q")
        _git(vault, "config", "user.email", "test@example.com")
        _git(vault, "config", "user.name", "Test")
        (vault / "a.md").write_text("one")
        _git(vault, "add", "-A")
        _git(vault, "commit", "-qm", "first")
        return vault

    def test_not_a_git_repo(self, vault):
        assert run_undo(vault)[0] == 1

    def test_reverts_last_commit_and_keeps_history(self, repo):
        (repo / "b.md").write_text("two")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "second")
        code, message = run_undo(repo)
        assert code == 0 and "second" in message
        assert not (repo / "b.md").exists()
        assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "3"

    def test_dirty_tree_refused_without_pending(self, repo):
        (repo / "b.md").write_text("two")
        code, message = run_undo(repo)
        assert code == 1 and "--pending" in message
        assert (repo / "b.md").exists()

    def test_pending_rolls_back_uncommitted_ingest(self, repo):
        (repo / "a.md").write_text("changed")
        (repo / "new.md").write_text("new")
        assert run_undo(repo, pending=True)[0] == 0
        assert (repo / "a.md").read_text() == "one"
        assert not (repo / "new.md").exists()

    def test_pending_with_clean_tree(self, repo):
        assert run_undo(repo, pending=True)[0] == 1

    def test_root_commit_cannot_be_undone(self, repo):
        assert run_undo(repo)[0] == 1

    def test_pending_without_history_leaves_no_checkpoint(self, vault):
        _git(vault, "init", "-q")
        (vault / "a.md").write_text("one")
        assert run_undo(vault, pending=True)[0] == 1
        assert _git(vault, "rev-list", "--all", "--count").stdout.strip() == "0"
