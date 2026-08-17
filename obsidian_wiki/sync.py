"""GitHub sync for an Obsidian vault.

Single implementation of the git-sync flow, shared by `obsidian-wiki setup` /
`obsidian-wiki sync-setup` (pip/uv installs) and `setup.sh` (source/curl
installs) — see issue #153. Both entrypoints call into this module instead of
each maintaining their own copy of the git plumbing.

The vault's own `git remote` is the source of truth for "is sync configured
and where does it push" — nothing here caches the remote URL elsewhere, so
there's nothing to go stale if the user changes it with plain git commands.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

GITIGNORE_CONTENT = (
    ".obsidian/workspace.json\n"
    ".obsidian/workspace-mobile.json\n"
    ".obsidian/cache\n"
    ".trash/\n"
    ".graph-cache.json\n"
)

#: Derived files that should never be committed — they are regenerable and
#: churn on every graph change. Backfilled into vaults whose .gitignore
#: predates them.
_DERIVED_IGNORES = (".graph-cache.json",)


def _git(vault_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(vault_path), *args],
        capture_output=True, text=True,
    )


def get_remote(vault_path: Path) -> str | None:
    """Return the vault's `origin` remote URL, or None if unset/not a git repo."""
    if not (vault_path / ".git").is_dir():
        return None
    proc = _git(vault_path, "remote", "get-url", "origin")
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def configure_sync(vault_path: Path, remote: str) -> list[str]:
    """Init git in the vault (if needed), write a default .gitignore, and wire
    `origin` at `remote`. Returns human-readable confirmation lines.

    Raises FileNotFoundError if vault_path doesn't exist, ValueError if remote
    is blank.
    """
    if not vault_path.is_dir():
        raise FileNotFoundError(f"vault not found: {vault_path}")
    remote = remote.strip()
    if not remote:
        raise ValueError("remote URL must not be blank")

    messages = []

    if not (vault_path / ".git").is_dir():
        proc = _git(vault_path, "init", "-q")
        if proc.returncode != 0:
            raise RuntimeError(f"git init failed: {proc.stderr.strip()}")
        messages.append("Initialized git repo in vault")

    gitignore = vault_path / ".gitignore"
    if not gitignore.is_file():
        gitignore.write_text(GITIGNORE_CONTENT)
        messages.append("Created .gitignore in vault")
    else:
        # An existing .gitignore is the user's file — never edit it. Just point
        # out regenerable files that would otherwise be committed.
        existing = gitignore.read_text(encoding="utf-8", errors="replace").split()
        missing = [p for p in _DERIVED_IGNORES if p not in existing]
        if missing:
            messages.append(
                "Tip: add "
                + ", ".join(missing)
                + " to .gitignore — regenerable, and it churns on every graph change"
            )

    has_origin = _git(vault_path, "remote", "get-url", "origin").returncode == 0
    verb = "set-url" if has_origin else "add"
    proc = _git(vault_path, "remote", verb, "origin", remote)
    if proc.returncode != 0:
        raise RuntimeError(f"git remote {verb} failed: {proc.stderr.strip()}")
    messages.append(f"Git remote → {remote}")

    return messages


def run_sync(vault_path: Path) -> tuple[int, str]:
    """Commit and push any pending vault changes. Returns (exit_code, message)."""
    if not vault_path.is_dir():
        return 1, f"wiki-sync: vault not found at '{vault_path}'"
    if not (vault_path / ".git").is_dir():
        return 1, "wiki-sync: vault is not a git repo — run `obsidian-wiki sync-setup <remote>` first"

    add = _git(vault_path, "add", "-A")
    if add.returncode != 0:
        return 1, f"wiki-sync: git add failed: {add.stderr.strip()}"

    diff = _git(vault_path, "diff", "--cached", "--quiet")
    if diff.returncode == 0:
        return 0, "wiki-sync: nothing to commit"

    commit_msg = f"sync {datetime.now():%Y-%m-%d %H:%M}"
    commit = _git(vault_path, "commit", "-m", commit_msg)
    if commit.returncode != 0:
        return 1, f"wiki-sync: git commit failed: {commit.stderr.strip()}"

    has_upstream = _git(vault_path, "rev-parse", "--abbrev-ref", "@{u}").returncode == 0
    push_args = ("push",) if has_upstream else ("push", "-u", "origin", "HEAD")
    push = _git(vault_path, *push_args)
    if push.returncode != 0:
        return 1, f"wiki-sync: git push failed: {push.stderr.strip()}"

    remote = get_remote(vault_path) or "origin"
    return 0, f"wiki-sync: pushed to {remote}"
