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

import re
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
        capture_output=True, encoding="utf-8", errors="replace",
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
        gitignore.write_text(GITIGNORE_CONTENT, encoding="utf-8")
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


# --- two-way sync, for a vault served from a container ----------------------
# `run_sync` above is one-way: a laptop pushing its vault. A self-hosted server
# shares the vault with a laptop, so both sides write and it has to pull too.

#: Lock files, journals and caches the vault writers create. Kept out of git via
#: `.git/info/exclude` — local to this clone, so the user's .gitignore is untouched.
SERVER_EXCLUDES = (
    ".memory.lock",
    ".manifest.lock",
    ".memory-transaction.json",
    ".graph-cache.json",
    ".*.tmp",
)


def redact_remote(text: str) -> str:
    """Hide credentials in an https remote (`https://user:token@host/...`).

    A container is usually given a token-bearing URL, and sync messages end up
    in /v1/status and the server log.
    """
    return re.sub(r"(https?://)[^/@\s]+@", r"\1***@", text)


def _ensure_excludes(vault_path: Path) -> None:
    exclude = vault_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    have = exclude.read_text(encoding="utf-8").split() if exclude.is_file() else []
    missing = [p for p in SERVER_EXCLUDES if p not in have]
    if missing:
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write("\n# obsidian-wiki server: transient vault files\n")
            fh.write("".join(f"{p}\n" for p in missing))


def bootstrap_remote(vault_path: Path, remote: str) -> str:
    """Make the vault a checkout of `remote`, once, at server start.

    An empty vault is cloned. An existing checkout is left alone (its own
    `origin` wins, as everywhere else in this module). A non-empty directory
    that is not a repo is initialised and pointed at `remote`; the first sync
    pushes it. Never deletes or overwrites a file.
    """
    remote = remote.strip()
    vault_path.mkdir(parents=True, exist_ok=True)
    if (vault_path / ".git").is_dir():
        _ensure_excludes(vault_path)
        return f"wiki-sync: using existing checkout ({redact_remote(get_remote(vault_path) or 'no origin')})"
    if not any(vault_path.iterdir()):
        clone = subprocess.run(
            ["git", "clone", "-q", remote, str(vault_path)],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        if clone.returncode != 0:
            raise RuntimeError(f"git clone failed: {redact_remote(clone.stderr.strip())}")
        _ensure_excludes(vault_path)
        return "wiki-sync: cloned the vault from its remote"
    configure_sync(vault_path, remote)
    _ensure_excludes(vault_path)
    return "wiki-sync: initialised git in the existing vault; the first sync pushes it"


def pull_and_push(vault_path: Path, lock=None) -> tuple[int, str]:
    """Commit local changes, rebase onto the remote, push. Returns (exit_code, message).

    `lock` is a context-manager factory held around the steps that touch the
    working tree (add/commit/rebase), so a server can keep its own writes out
    of a half-applied rebase. Fetch and push run outside it.

    On a rebase conflict the rebase is aborted and the local commit kept: no
    edit from either side is lost, and the next cycle retries after a human
    resolves it.
    """
    from contextlib import nullcontext

    guard = lock or nullcontext
    if not (vault_path / ".git").is_dir():
        return 1, "wiki-sync: vault is not a git repo"
    if get_remote(vault_path) is None:
        return 1, "wiki-sync: vault has no origin remote"
    _ensure_excludes(vault_path)

    with guard():
        add = _git(vault_path, "add", "-A")
        if add.returncode != 0:
            return 1, f"wiki-sync: git add failed: {add.stderr.strip()}"
        committed = _git(vault_path, "diff", "--cached", "--quiet").returncode != 0
        if committed:
            commit = _git(vault_path, "commit", "-q", "-m", f"sync {datetime.now():%Y-%m-%d %H:%M} (server)")
            if commit.returncode != 0:
                return 1, f"wiki-sync: git commit failed: {commit.stderr.strip()}"

    fetch = _git(vault_path, "fetch", "-q", "origin")
    if fetch.returncode != 0:
        return 1, f"wiki-sync: git fetch failed: {redact_remote(fetch.stderr.strip())}"

    branch = _git(vault_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    upstream = f"origin/{branch}"
    remote_has_branch = _git(vault_path, "rev-parse", "--verify", "-q", upstream).returncode == 0
    has_head = _git(vault_path, "rev-parse", "--verify", "-q", "HEAD").returncode == 0

    if remote_has_branch and has_head:
        with guard():
            # --autostash: a write can land between the commit above and here.
            rebase = _git(vault_path, "rebase", "-q", "--autostash", upstream)
            if rebase.returncode != 0:
                _git(vault_path, "rebase", "--abort")
                return 1, (
                    f"wiki-sync: conflict rebasing onto {upstream}; local commits kept, "
                    "nothing pushed — resolve it in a clone and push, the next cycle picks it up"
                )

    if not has_head:
        return 0, "wiki-sync: nothing to sync yet"
    ahead = _git(vault_path, "rev-list", "--count", f"{upstream}..HEAD") if remote_has_branch else None
    if ahead is not None and ahead.stdout.strip() == "0":
        return 0, "wiki-sync: up to date"
    push = _git(vault_path, "push", "-q", "-u", "origin", f"HEAD:{branch}")
    if push.returncode != 0:
        return 1, f"wiki-sync: git push failed: {redact_remote(push.stderr.strip())}"
    return 0, f"wiki-sync: pushed to {redact_remote(get_remote(vault_path) or 'origin')}"


def run_undo(vault_path: Path, pending: bool = False) -> tuple[int, str]:
    """Undo the vault's last change with `git revert`. Returns (exit_code, message).

    Default reverts the latest commit. With `pending`, uncommitted changes are
    first committed locally and that checkpoint is reverted instead — so an
    ingest you have not synced yet can be rolled back. Either way history is
    kept (the undo is itself a commit, revertable) and nothing is pushed.
    """
    if not (vault_path / ".git").is_dir():
        return 1, "wiki-undo: vault is not a git repo — run `obsidian-wiki sync-setup <remote>` first"

    dirty = bool(_git(vault_path, "status", "--porcelain").stdout.strip())
    if dirty and not pending:
        return 1, "wiki-undo: uncommitted changes — pass --pending to undo them, or `obsidian-wiki sync` to keep them"
    if pending and not dirty:
        return 1, "wiki-undo: no pending changes to undo"

    # Check before committing so a refusal never leaves a checkpoint behind.
    if _git(vault_path, "rev-parse", "--verify", "-q", "HEAD" if pending else "HEAD~1").returncode != 0:
        return 1, "wiki-undo: nothing earlier to go back to"

    if pending:
        _git(vault_path, "add", "-A")
        commit = _git(vault_path, "commit", "-m", f"checkpoint before undo {datetime.now():%Y-%m-%d %H:%M}")
        if commit.returncode != 0:
            return 1, f"wiki-undo: git commit failed: {commit.stderr.strip()}"

    subject = _git(vault_path, "log", "-1", "--format=%h %s").stdout.strip()
    revert = _git(vault_path, "revert", "--no-edit", "HEAD")
    if revert.returncode != 0:
        _git(vault_path, "revert", "--abort")
        return 1, f"wiki-undo: git revert failed: {revert.stderr.strip()}"
    return 0, f"wiki-undo: reverted {subject} (run `obsidian-wiki undo` again to go back further)"
