# Git Project Manifest Identity MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Git-backed wiki projects a portable remote-based identity while refusing to distill a dirty worktree or a checkout that differs from the canonical remote branch.

**Architecture:** Add one pure-stdlib `obsidian_wiki.git_project` module for remote normalization, branch safety, delta classification, legacy/V2 project entry handling, and atomic manifest writes. Expose it through `project-state` and `project-record` CLI commands; update the agent skills to call those commands while leaving generic manifest sources unchanged.

**Tech Stack:** Python 3.9+, standard library (`subprocess`, `urllib.parse`, `dataclasses`, `tempfile`, `json`, `os`), pytest, Git CLI, Markdown agent skills.

## Global Constraints

- Python remains `>=3.9`; add no runtime dependency.
- Do not call provider APIs, `git fetch`, `git pull`, `git push`, or any other network operation.
- Generic `.manifest.json["sources"]`, `stats`, and unknown top-level fields must remain unchanged.
- A V2 project entry must never store `source_cwd`, `source_path`, or a clone-local remote alias.
- Shared refs use `refs/heads/<branch>`; clone-local refs use `refs/remotes/<alias>/<branch>` only in process memory and CLI output.
- `wiki-update` may read a Git worktree only when `git status --porcelain` is empty and `HEAD` equals the selected remote-tracking commit.
- `project-record` must receive the full preflight commit and refuse to record if the rechecked `HEAD` differs.
- Store full 40-character commit SHAs.
- Repositories without a remote retain the legacy path-based workflow.
- Do not implement snapshots, persistent locators, bulk migration, relinking, compare-and-swap, locking, LFS/submodule materialization, or `wiki-status` changes.
- Follow TDD: every behavior change begins with a failing focused test.

---

## File Map

- Create `obsidian_wiki/git_project.py` — Git identity, safety, delta, V1/V2 adapter, and atomic project recording.
- Modify `obsidian_wiki/cli.py` — `project-state` and `project-record` handlers and parser definitions.
- Create `tests/test_git_project.py` — module tests plus temporary bare-repository integration tests and CLI smoke tests.
- Create `tests/test_git_project_docs.py` — deterministic assertions for skill/bootstrap/README contracts.
- Modify `.skills/wiki-update/SKILL.md` — use `project-state`, enforce the safety gate, and call `project-record` after page writes.
- Modify `.skills/wiki-query/SKILL.md` — resolve V2 code paths only from a matching current Git repository; retain legacy fallback.
- Modify `.skills/llm-wiki/SKILL.md` — document the V2 project exception to generic absolute source paths.
- Modify `AGENTS.md` — update the always-on cross-project workflow summary.
- Modify `README.md` — document portable Git identity and the safe checkout requirement.
- Modify `README_TW.md` — mirror the README behavior in Traditional Chinese.

---

### Task 1: Normalize Git remotes and select a canonical identity

**Files:**
- Create: `obsidian_wiki/git_project.py`
- Create: `tests/test_git_project.py`

**Interfaces:**
- Produces: `ProjectError(code: str, message: str, exit_code: int)`
- Produces: `RemoteIdentity(local_name: str, repo_id: str, canonical_url: str)`
- Produces: `normalize_remote_url(url: str) -> tuple[str, str]`
- Produces: `list_remotes(repo: Path) -> list[RemoteIdentity]`
- Produces: `select_remote(repo: Path, *, override: str | None = None, expected_repo_id: str | None = None) -> RemoteIdentity | None`

- [ ] **Step 1: Write normalization tests**

Create `tests/test_git_project.py` with the test imports and exact URL expectations:

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from obsidian_wiki.git_project import (
    ProjectError,
    normalize_remote_url,
    select_remote,
)


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("url", "repo_id", "canonical_url"),
    [
        (
            "git@github.com:Acme/payment-service.git",
            "github.com/acme/payment-service",
            "https://github.com/acme/payment-service.git",
        ),
        (
            "ssh://git@github.com/Acme/payment-service.git",
            "github.com/acme/payment-service",
            "https://github.com/acme/payment-service.git",
        ),
        (
            "https://token@github.com/Acme/payment-service.git/",
            "github.com/acme/payment-service",
            "https://github.com/acme/payment-service.git",
        ),
        (
            "ssh://git@github.com:22/Acme/payment-service.git",
            "github.com/acme/payment-service",
            "https://github.com/acme/payment-service.git",
        ),
        (
            "ssh://git@example.internal:2222/Team/Repo.git",
            "example.internal:2222/Team/Repo",
            "https://example.internal:2222/Team/Repo.git",
        ),
    ],
)
def test_normalize_remote_url(url: str, repo_id: str, canonical_url: str) -> None:
    assert normalize_remote_url(url) == (repo_id, canonical_url)


@pytest.mark.parametrize(
    "url",
    ["", "/tmp/local-repo", "file:///tmp/repo", "not a remote", "ssh://host:bad/repo"],
)
def test_normalize_remote_url_rejects_local_or_malformed_values(url: str) -> None:
    with pytest.raises(ProjectError, match="unsupported Git remote"):
        normalize_remote_url(url)
```

- [ ] **Step 2: Run the normalization tests and confirm the module is missing**

Run:

```bash
pytest -q tests/test_git_project.py
```

Expected: collection fails with `ModuleNotFoundError: No module named 'obsidian_wiki.git_project'`.

- [ ] **Step 3: Implement error and remote normalization primitives**

Create `obsidian_wiki/git_project.py` with:

```python
"""Deterministic Git project identity and safe manifest recording."""

from __future__ import annotations

import json
import os
import posixpath
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class ProjectError(RuntimeError):
    def __init__(self, code: str, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "error",
            "error": self.code,
            "message": str(self),
            "exit_code": self.exit_code,
        }


@dataclass(frozen=True)
class RemoteIdentity:
    local_name: str
    repo_id: str
    canonical_url: str


_SCP_REMOTE = re.compile(
    r"^(?:[^@/\s]+@)?(?P<host>[^:/\s]+):(?P<path>\S+)$"
)
_CASE_INSENSITIVE_REPO_HOSTS = {"github.com"}


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=check,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "Git command failed").strip()
        raise ProjectError("git_command_failed", detail, 3) from exc


def normalize_remote_url(url: str) -> tuple[str, str]:
    raw = url.strip()
    host = ""
    path = ""
    port: int | None = None

    if "://" in raw:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https", "ssh", "git"} or not parsed.hostname:
            raise ProjectError("unsupported_remote", f"unsupported Git remote: {url}", 3)
        host = parsed.hostname.lower()
        try:
            port = parsed.port
        except ValueError as exc:
            raise ProjectError(
                "unsupported_remote",
                f"unsupported Git remote: {url}",
                3,
            ) from exc
        default_ports = {"http": 80, "https": 443, "ssh": 22, "git": 9418}
        if port == default_ports.get(parsed.scheme):
            port = None
        path = parsed.path
    else:
        match = _SCP_REMOTE.fullmatch(raw)
        if not match:
            raise ProjectError("unsupported_remote", f"unsupported Git remote: {url}", 3)
        host = match.group("host").lower()
        path = match.group("path")

    clean_path = posixpath.normpath("/" + path).lstrip("/")
    if clean_path in {"", "."}:
        raise ProjectError("unsupported_remote", f"unsupported Git remote: {url}", 3)
    if clean_path.endswith(".git"):
        clean_path = clean_path[:-4]
    if not clean_path:
        raise ProjectError("unsupported_remote", f"unsupported Git remote: {url}", 3)
    if host in _CASE_INSENSITIVE_REPO_HOSTS:
        clean_path = clean_path.lower()

    authority = f"{host}:{port}" if port is not None else host
    repo_id = f"{authority}/{clean_path}"
    canonical_url = f"https://{repo_id}.git"
    return repo_id, canonical_url
```

- [ ] **Step 4: Run normalization tests**

Run:

```bash
pytest -q tests/test_git_project.py
```

Expected: all normalization tests pass.

- [ ] **Step 5: Add canonical remote selection tests**

Append:

```python
def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    return repo


def test_select_remote_prefers_upstream_then_origin(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    git(repo, "remote", "add", "origin", "git@github.com:alice/payment-service.git")
    git(repo, "remote", "add", "upstream", "https://github.com/acme/payment-service.git")

    selected = select_remote(repo)

    assert selected is not None
    assert selected.local_name == "upstream"
    assert selected.repo_id == "github.com/acme/payment-service"


def test_select_remote_honors_explicit_override(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    git(repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    git(repo, "remote", "add", "mirror", "ssh://git@example.internal/team/repo.git")

    assert select_remote(repo, override="mirror").local_name == "mirror"


def test_select_remote_matches_expected_identity_regardless_of_alias(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    git(repo, "remote", "add", "company", "git@github.com:acme/payment-service.git")

    selected = select_remote(repo, expected_repo_id="git:github.com/acme/payment-service")

    assert selected is not None
    assert selected.local_name == "company"


def test_select_remote_returns_none_when_repo_has_no_remote(tmp_path: Path) -> None:
    assert select_remote(make_repo(tmp_path)) is None


def test_select_remote_ignores_unrelated_local_path_remote(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    git(repo, "remote", "add", "backup", str(tmp_path / "backup.git"))
    git(repo, "remote", "add", "origin", "https://github.com/acme/repo.git")

    assert select_remote(repo).repo_id == "github.com/acme/repo"


def test_invalid_explicit_remote_is_a_configuration_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    git(repo, "remote", "add", "origin", "https://github.com/acme/repo.git")

    with pytest.raises(ProjectError) as caught:
        select_remote(repo, override="missing")

    assert caught.value.code == "remote_not_found"
    assert caught.value.exit_code == 2
```

- [ ] **Step 6: Run selection tests and confirm failure**

Run:

```bash
pytest -q tests/test_git_project.py
```

Expected: failures report that `select_remote` is not defined.

- [ ] **Step 7: Implement remote listing and selection**

Append to `obsidian_wiki/git_project.py`:

```python
def _remote_names(repo: Path) -> list[str]:
    return [name for name in _git(repo, "remote").stdout.splitlines() if name]


def _remote_identity(repo: Path, name: str) -> RemoteIdentity:
    url = _git(repo, "remote", "get-url", name).stdout.strip()
    repo_id, canonical_url = normalize_remote_url(url)
    return RemoteIdentity(name, repo_id, canonical_url)


def list_remotes(repo: Path) -> list[RemoteIdentity]:
    result: list[RemoteIdentity] = []
    for name in _remote_names(repo):
        try:
            result.append(_remote_identity(repo, name))
        except ProjectError as exc:
            if exc.code != "unsupported_remote":
                raise
    return result


def select_remote(
    repo: Path,
    *,
    override: str | None = None,
    expected_repo_id: str | None = None,
) -> RemoteIdentity | None:
    names = _remote_names(repo)
    if override is not None:
        if override not in names:
            raise ProjectError(
                "remote_not_found",
                f"explicit Git remote does not exist: {override}",
                2,
            )
        return _remote_identity(repo, override)

    if expected_repo_id is not None:
        expected = expected_repo_id.removeprefix("git:")
        remotes = list_remotes(repo)
        matches = [remote for remote in remotes if remote.repo_id == expected]
        if not matches:
            raise ProjectError(
                "canonical_remote_missing",
                f"no local remote matches git:{expected}",
                3,
            )
        rank = {"upstream": 0, "origin": 1}
        return sorted(matches, key=lambda item: (rank.get(item.local_name, 2), item.local_name))[0]

    for preferred in ("upstream", "origin"):
        if preferred in names:
            return _remote_identity(repo, preferred)
    return None
```

- [ ] **Step 8: Run the focused tests**

Run:

```bash
pytest -q tests/test_git_project.py
```

Expected: all tests pass.

- [ ] **Step 9: Commit Task 1**

```bash
git add obsidian_wiki/git_project.py tests/test_git_project.py
git commit -m "feat: add portable Git project identity"
```

---

### Task 2: Resolve the shared branch and enforce the safe worktree gate

**Files:**
- Modify: `obsidian_wiki/git_project.py`
- Modify: `tests/test_git_project.py`

**Interfaces:**
- Consumes: `RemoteIdentity`, `select_remote`
- Produces: `ProjectState`
- Produces: `inspect_project(repo: Path, *, expected_repo_id: str | None = None, remote_override: str | None = None, branch_override: str | None = None, since: str | None = None) -> ProjectState`
- `ProjectState.to_dict() -> dict[str, object]` is the stable CLI JSON contract.

- [ ] **Step 1: Add a temporary remote/clone fixture**

Append to `tests/test_git_project.py`:

```python
def make_remote_clone(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "clone"
    git(tmp_path, "init", "--bare", "-q", str(bare))
    git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    git(tmp_path, "init", "-q", "-b", "main", str(seed))
    git(seed, "config", "user.name", "Test User")
    git(seed, "config", "user.email", "test@example.com")
    (seed / "README.md").write_text("# Project\n", encoding="utf-8")
    git(seed, "add", "README.md")
    git(seed, "commit", "-q", "-m", "initial")
    git(seed, "remote", "add", "origin", str(bare))
    git(seed, "push", "-q", "-u", "origin", "main")
    git(tmp_path, "clone", "-q", str(bare), str(clone))
    git(clone, "config", "user.name", "Test User")
    git(clone, "config", "user.email", "test@example.com")
    return bare, clone
```

Update `normalize_remote_url` only for this fixture by assigning a network-style
remote after cloning in each test:

```python
git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
```

The remote-tracking refs created by clone remain available after changing the URL.

- [ ] **Step 2: Add clean/aligned state tests**

Extend the imports with `inspect_project`, then append:

```python
def test_project_state_accepts_clean_aligned_default_branch(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")

    state = inspect_project(clone)

    assert state.mode == "git_v2"
    assert state.safe is True
    assert state.repo_id == "github.com/acme/project"
    assert state.tracked_ref == "refs/heads/main"
    assert state.head_commit == state.tracked_commit
    assert len(state.head_commit or "") == 40


def test_project_state_rejects_dirty_and_untracked_content(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    (clone / "README.md").write_text("# Changed\n", encoding="utf-8")
    (clone / "scratch.txt").write_text("untracked\n", encoding="utf-8")

    state = inspect_project(clone)

    assert state.safe is False
    assert state.safety_error == "dirty_worktree"


def test_project_state_rejects_feature_commit(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    git(clone, "switch", "-q", "-c", "feature")
    (clone / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(clone, "add", "feature.txt")
    git(clone, "commit", "-q", "-m", "feature")

    state = inspect_project(clone)

    assert state.safe is False
    assert state.safety_error == "head_not_tracked"


def test_project_state_keeps_local_only_repository_in_legacy_mode(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    state = inspect_project(repo)

    assert state.mode == "legacy_local_only"
    assert state.project_id is None


def test_different_clone_paths_and_remote_aliases_share_identity(tmp_path: Path) -> None:
    bare, first = make_remote_clone(tmp_path)
    second = tmp_path / "second-clone"
    git(tmp_path, "clone", "-q", str(bare), str(second))
    git(second, "remote", "rename", "origin", "company")
    git(first, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    git(second, "remote", "set-url", "company", "git@github.com:acme/project.git")

    first_state = inspect_project(first)
    second_state = inspect_project(second, expected_repo_id=first_state.project_id)

    assert first_state.project_id == second_state.project_id
```

- [ ] **Step 3: Add branch and delta tests**

Append:

```python
def test_project_state_requires_branch_when_remote_head_is_missing(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    git(clone, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")

    with pytest.raises(ProjectError) as caught:
        inspect_project(clone)

    assert caught.value.code == "default_branch_unknown"


def test_project_state_rejects_invalid_explicit_branch(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")

    with pytest.raises(ProjectError) as caught:
        inspect_project(clone, branch_override="bad branch")

    assert caught.value.code == "invalid_branch"


def test_project_state_classifies_all_cursor_relationships(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    parent = git(clone, "rev-parse", "HEAD").stdout.strip()
    (clone / "README.md").write_text("# Project v2\n", encoding="utf-8")
    git(clone, "add", "README.md")
    git(clone, "commit", "-q", "-m", "second")
    git(clone, "update-ref", "refs/remotes/origin/main", "HEAD")

    target = git(clone, "rev-parse", "HEAD").stdout.strip()
    divergent = git(
        clone,
        "commit-tree",
        "HEAD^{tree}",
        "-m",
        "divergent",
    ).stdout.strip()

    same = inspect_project(clone, since=target)
    incremental = inspect_project(clone, since=parent)
    unrelated = inspect_project(clone, since=divergent)
    missing = inspect_project(clone, since="0" * 40)

    assert same.delta_mode == "same"
    assert incremental.delta_mode == "incremental"
    assert unrelated.delta_mode == "full"
    assert missing.delta_mode == "full"
```

- [ ] **Step 4: Run state tests and confirm missing interfaces**

Run:

```bash
pytest -q tests/test_git_project.py
```

Expected: failures report missing `inspect_project` and `ProjectState`.

- [ ] **Step 5: Implement `ProjectState`, branch resolution, safety, and delta**

Append to `obsidian_wiki/git_project.py`:

```python
@dataclass(frozen=True)
class ProjectState:
    mode: str
    repo_root: str
    project_id: str | None
    repo_id: str | None
    canonical_url: str | None
    remote_name: str | None
    tracked_ref: str | None
    local_ref: str | None
    head_commit: str | None
    tracked_commit: str | None
    clean: bool
    safe: bool
    safety_error: str | None
    previous_commit: str | None
    delta_mode: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _repo_root(repo: Path) -> Path:
    result = _git(repo, "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).resolve()


def _shared_branch(
    repo: Path,
    remote_name: str,
    override: str | None,
) -> tuple[str, str]:
    if override:
        branch = override.removeprefix("refs/heads/")
    else:
        result = _git(
            repo,
            "symbolic-ref",
            "--quiet",
            "--short",
            f"refs/remotes/{remote_name}/HEAD",
            check=False,
        )
        if result.returncode != 0:
            raise ProjectError(
                "default_branch_unknown",
                f"default branch for remote {remote_name!r} is unavailable; pass --branch",
                3,
            )
        prefix = f"{remote_name}/"
        short = result.stdout.strip()
        if not short.startswith(prefix):
            raise ProjectError("default_branch_unknown", f"invalid remote HEAD: {short}", 3)
        branch = short[len(prefix):]
    valid = _git(repo, "check-ref-format", "--branch", branch, check=False)
    if valid.returncode != 0:
        raise ProjectError("invalid_branch", f"invalid branch: {branch}", 2)
    return f"refs/heads/{branch}", f"refs/remotes/{remote_name}/{branch}"


def _commit(repo: Path, revision: str) -> str:
    result = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}", check=False)
    if result.returncode != 0:
        raise ProjectError("tracked_ref_missing", f"Git revision is unavailable: {revision}", 3)
    return result.stdout.strip()


def _delta_mode(repo: Path, since: str | None, target: str) -> str:
    if since is None:
        return "full"
    prior = _git(repo, "rev-parse", "--verify", f"{since}^{{commit}}", check=False)
    if prior.returncode != 0:
        return "full"
    prior_commit = prior.stdout.strip()
    if prior_commit == target:
        return "same"
    ancestor = _git(repo, "merge-base", "--is-ancestor", prior_commit, target, check=False)
    return "incremental" if ancestor.returncode == 0 else "full"


def inspect_project(
    repo: Path,
    *,
    expected_repo_id: str | None = None,
    remote_override: str | None = None,
    branch_override: str | None = None,
    since: str | None = None,
) -> ProjectState:
    root = _repo_root(repo)
    remote = select_remote(
        root,
        override=remote_override,
        expected_repo_id=expected_repo_id,
    )
    if remote is None:
        return ProjectState(
            "legacy_local_only", str(root), None, None, None, None, None, None,
            None, None, False, False, "no_remote", since, None,
        )

    tracked_ref, local_ref = _shared_branch(root, remote.local_name, branch_override)
    head = _commit(root, "HEAD")
    tracked = _commit(root, local_ref)
    clean = not _git(root, "status", "--porcelain").stdout.strip()
    safety_error = None
    if not clean:
        safety_error = "dirty_worktree"
    elif head != tracked:
        safety_error = "head_not_tracked"
    return ProjectState(
        mode="git_v2",
        repo_root=str(root),
        project_id=f"git:{remote.repo_id}",
        repo_id=remote.repo_id,
        canonical_url=remote.canonical_url,
        remote_name=remote.local_name,
        tracked_ref=tracked_ref,
        local_ref=local_ref,
        head_commit=head,
        tracked_commit=tracked,
        clean=clean,
        safe=safety_error is None,
        safety_error=safety_error,
        previous_commit=since,
        delta_mode=_delta_mode(root, since, tracked),
    )
```

During implementation, preserve the field names and JSON values above. Refactor
line layout as needed to satisfy formatting, but do not change the interface.

- [ ] **Step 6: Run state and identity tests**

Run:

```bash
pytest -q tests/test_git_project.py
```

Expected: all tests pass.

- [ ] **Step 7: Run the existing cache/manifest regression tests**

Run:

```bash
pytest -q tests/test_cache.py tests/test_manifest_delta.py
```

Expected: all tests pass, proving generic source behavior is unchanged.

- [ ] **Step 8: Commit Task 2**

```bash
git add obsidian_wiki/git_project.py tests/test_git_project.py
git commit -m "feat: enforce safe canonical project state"
```

---

### Task 3: Record V2 projects with lazy legacy conversion and atomic writes

**Files:**
- Modify: `obsidian_wiki/git_project.py`
- Modify: `tests/test_git_project.py`

**Interfaces:**
- Consumes: a safe `ProjectState`
- Produces: `record_project(vault: Path, state: ProjectState, *, expected_commit: str, slug: str, pages: list[str], now: datetime | None = None) -> dict[str, object]`
- Produces: V2 entries keyed by `git:<repo_id>`

- [ ] **Step 1: Add V2 record and unrelated-field preservation tests**

Append:

```python
from datetime import datetime, timezone

from obsidian_wiki.git_project import record_project


def test_record_project_writes_v2_and_preserves_generic_sources(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    state = inspect_project(clone)
    vault = tmp_path / "vault"
    vault.mkdir()
    manifest = {
        "version": 1,
        "sources": {"/docs/a.md": {"content_hash": "abc"}},
        "projects": {},
        "stats": {"total": 1},
        "custom": {"keep": True},
    }
    (vault / ".manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = record_project(
        vault,
        state,
        expected_commit=state.head_commit,
        slug="project",
        pages=["projects/project/project.md"],
        now=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )

    saved = json.loads((vault / ".manifest.json").read_text(encoding="utf-8"))
    entry = saved["projects"]["git:github.com/acme/project"]
    assert entry["project_schema"] == 2
    assert entry["tracked_ref"] == "refs/heads/main"
    assert entry["cursor"]["commit"] == state.head_commit
    assert "source_cwd" not in entry
    assert "remote_name" not in entry
    assert saved["sources"] == manifest["sources"]
    assert saved["stats"] == manifest["stats"]
    assert saved["custom"] == manifest["custom"]
    assert result["project_id"] == "git:github.com/acme/project"
```

- [ ] **Step 2: Add lazy migration and collision tests**

Append:

```python
def test_record_project_lazily_replaces_matching_legacy_entry(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    state = inspect_project(clone)
    vault = tmp_path / "vault"
    vault.mkdir()
    legacy = {
        "projects": {
            "project": {
                "source_cwd": str(clone),
                "last_synced": "2026-07-25T00:00:00+00:00",
                "last_commit_synced": state.head_commit[:7],
                "pages_in_vault": ["projects/project/old.md"],
            }
        }
    }
    (vault / ".manifest.json").write_text(json.dumps(legacy), encoding="utf-8")

    record_project(
        vault,
        state,
        expected_commit=state.head_commit,
        slug="project",
        pages=["projects/project/new.md"],
        now=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )

    projects = json.loads((vault / ".manifest.json").read_text())["projects"]
    assert "project" not in projects
    assert projects["git:github.com/acme/project"]["pages_in_vault"] == [
        "projects/project/old.md",
        "projects/project/new.md",
    ]
    assert projects["git:github.com/acme/project"]["cursor"]["synced_at"] == (
        "2026-07-25T00:00:00+00:00"
    )


def test_record_project_rejects_slug_owned_by_another_repo(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    state = inspect_project(clone)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".manifest.json").write_text(
        json.dumps({
            "projects": {
                "git:github.com/other/project": {
                    "project_schema": 2,
                    "kind": "git",
                    "repo_id": "github.com/other/project",
                    "project_slug": "project",
                }
            }
        }),
        encoding="utf-8",
    )

    with pytest.raises(ProjectError) as caught:
        record_project(
            vault,
            state,
            expected_commit=state.head_commit,
            slug="project",
            pages=[],
        )

    assert caught.value.code == "project_slug_collision"


def test_record_project_rejects_multiple_matching_legacy_entries(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    state = inspect_project(clone)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".manifest.json").write_text(
        json.dumps({
            "projects": {
                "old-a": {"source_cwd": str(clone)},
                "old-b": {"source_cwd": str(clone)},
            }
        }),
        encoding="utf-8",
    )

    with pytest.raises(ProjectError) as caught:
        record_project(
            vault,
            state,
            expected_commit=state.head_commit,
            slug="project",
            pages=[],
        )

    assert caught.value.code == "project_identity_collision"


def test_record_project_rejects_legacy_slug_owned_by_another_path(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    state = inspect_project(clone)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".manifest.json").write_text(
        json.dumps({
            "projects": {
                "project": {
                    "source_cwd": str(tmp_path / "different-project"),
                }
            }
        }),
        encoding="utf-8",
    )

    with pytest.raises(ProjectError) as caught:
        record_project(
            vault,
            state,
            expected_commit=state.head_commit,
            slug="project",
            pages=[],
        )

    assert caught.value.code == "project_slug_collision"
```

- [ ] **Step 3: Add malformed/unsafe/atomic failure tests**

Append:

```python
def test_record_project_rejects_malformed_manifest(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".manifest.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(ProjectError) as caught:
        state = inspect_project(clone)
        record_project(
            vault,
            state,
            expected_commit=state.head_commit,
            slug="project",
            pages=[],
        )

    assert caught.value.code == "manifest_invalid"
    assert (vault / ".manifest.json").read_text() == "{broken"


def test_record_project_rejects_unsafe_state(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    (clone / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(ProjectError) as caught:
        state = inspect_project(clone)
        record_project(
            tmp_path / "vault",
            state,
            expected_commit=state.head_commit,
            slug="project",
            pages=[],
        )

    assert caught.value.code == "unsafe_project_state"


def test_record_project_rejects_commit_changed_since_preflight(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    state = inspect_project(clone)

    with pytest.raises(ProjectError) as caught:
        record_project(
            tmp_path / "vault",
            state,
            expected_commit="0" * 40,
            slug="project",
            pages=[],
        )

    assert caught.value.code == "project_state_changed"
    assert caught.value.exit_code == 4


def test_atomic_replace_failure_keeps_original_manifest(tmp_path: Path, monkeypatch) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    vault = tmp_path / "vault"
    vault.mkdir()
    original = '{"sources": {"keep": true}, "projects": {}}\n'
    (vault / ".manifest.json").write_text(original, encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr("obsidian_wiki.git_project.os.replace", fail_replace)
    with pytest.raises(ProjectError, match="replace failed"):
        state = inspect_project(clone)
        record_project(
            vault,
            state,
            expected_commit=state.head_commit,
            slug="project",
            pages=[],
        )

    assert (vault / ".manifest.json").read_text(encoding="utf-8") == original
```

- [ ] **Step 4: Run the new tests and confirm failure**

Run:

```bash
pytest -q tests/test_git_project.py
```

Expected: failures report missing `record_project`.

- [ ] **Step 5: Implement manifest loading, entry conversion, and atomic replacement**

Append to `obsidian_wiki/git_project.py`:

```python
def _load_manifest(vault: Path) -> dict[str, object]:
    path = vault / ".manifest.json"
    if not path.exists():
        return {"version": 1, "sources": {}, "projects": {}, "stats": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise ProjectError("manifest_invalid", f"invalid manifest: {exc}", 5) from exc
    if not isinstance(data, dict) or not isinstance(data.get("projects", {}), dict):
        raise ProjectError("manifest_invalid", "manifest projects must be an object", 5)
    return data


def _atomic_write_manifest(vault: Path, manifest: dict[str, object]) -> None:
    path = vault / ".manifest.json"
    vault.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".manifest.", suffix=".tmp", dir=vault)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(vault, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
            finally:
                try:
                    os.close(directory_fd)
                except OSError:
                    pass
    except OSError as exc:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise ProjectError("manifest_write_failed", f"manifest write failed: {exc}", 5) from exc


def _legacy_candidates(
    projects: dict[str, object],
    state: ProjectState,
    slug: str,
) -> list[str]:
    root = Path(state.repo_root)
    matches: list[str] = []
    for key, raw in projects.items():
        if not isinstance(raw, dict) or raw.get("project_schema") == 2:
            continue
        source_cwd = raw.get("source_cwd")
        path_matches = False
        if isinstance(source_cwd, str):
            path_matches = Path(source_cwd).expanduser().resolve() == root
        if path_matches or (key == slug and source_cwd is None):
            matches.append(key)
    return matches


def _newest_sync_timestamp(
    prior: dict[str, object],
    current: datetime,
) -> str:
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    candidate: object = prior.get("last_synced")
    cursor = prior.get("cursor")
    if isinstance(cursor, dict) and isinstance(cursor.get("synced_at"), str):
        candidate = cursor["synced_at"]
    if isinstance(candidate, str):
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed > current:
                return candidate
        except ValueError:
            pass
    return current.isoformat()


def record_project(
    vault: Path,
    state: ProjectState,
    *,
    expected_commit: str,
    slug: str,
    pages: list[str],
    now: datetime | None = None,
) -> dict[str, object]:
    if state.mode != "git_v2" or not state.safe or not state.project_id:
        raise ProjectError("unsafe_project_state", "project state is not safe to record", 4)
    if not state.repo_id or not state.canonical_url or not state.tracked_ref or not state.head_commit:
        raise ProjectError("unsafe_project_state", "project identity is incomplete", 4)
    if state.head_commit != expected_commit:
        raise ProjectError(
            "project_state_changed",
            "HEAD changed after project preflight; cursor was not advanced",
            4,
        )

    manifest = _load_manifest(vault)
    projects = manifest.setdefault("projects", {})
    if not isinstance(projects, dict):
        raise ProjectError("manifest_invalid", "manifest projects must be an object", 5)

    for key, raw in projects.items():
        if (
            isinstance(raw, dict)
            and raw.get("project_schema") == 2
            and raw.get("project_slug") == slug
            and key != state.project_id
        ):
            raise ProjectError(
                "project_slug_collision",
                f"project slug {slug!r} already belongs to {key}",
                5,
            )
        if (
            key == slug
            and isinstance(raw, dict)
            and raw.get("project_schema") != 2
            and isinstance(raw.get("source_cwd"), str)
            and Path(raw["source_cwd"]).expanduser().resolve()
            != Path(state.repo_root)
        ):
            raise ProjectError(
                "project_slug_collision",
                f"project slug {slug!r} belongs to another legacy path",
                5,
            )

    legacy_keys = _legacy_candidates(projects, state, slug)
    if len(legacy_keys) > 1:
        raise ProjectError("project_identity_collision", "multiple legacy entries match", 5)

    prior: dict[str, object] = {}
    if isinstance(projects.get(state.project_id), dict):
        prior = dict(projects[state.project_id])
    elif legacy_keys and isinstance(projects.get(legacy_keys[0]), dict):
        prior = dict(projects[legacy_keys[0]])

    prior_pages = prior.get("pages_in_vault", [])
    if not isinstance(prior_pages, list):
        prior_pages = []
    all_pages = list(dict.fromkeys(
        [str(page) for page in prior_pages] + [str(page) for page in pages]
    ))
    timestamp = _newest_sync_timestamp(
        prior,
        now or datetime.now(timezone.utc),
    )
    entry = {
        "project_schema": 2,
        "kind": "git",
        "repo_id": state.repo_id,
        "project_slug": slug,
        "remote": {"canonical_url": state.canonical_url},
        "tracked_ref": state.tracked_ref,
        "cursor": {"commit": state.head_commit, "synced_at": timestamp},
        "pages_in_vault": all_pages,
    }
    for legacy_key in legacy_keys:
        projects.pop(legacy_key, None)
    projects[state.project_id] = entry
    _atomic_write_manifest(vault, manifest)
    return {
        "status": "recorded",
        "project_id": state.project_id,
        "cursor": state.head_commit,
        "pages_in_vault": all_pages,
    }
```

- [ ] **Step 6: Run module tests**

Run:

```bash
pytest -q tests/test_git_project.py
```

Expected: all tests pass.

- [ ] **Step 7: Run all manifest-sensitive regression tests**

Run:

```bash
pytest -q tests/test_cache.py tests/test_manifest_delta.py tests/test_doctor.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 3**

```bash
git add obsidian_wiki/git_project.py tests/test_git_project.py
git commit -m "feat: record portable project manifest entries"
```

---

### Task 4: Expose `project-state` and `project-record` through the CLI

**Files:**
- Modify: `obsidian_wiki/cli.py:620-716`
- Modify: `obsidian_wiki/cli.py:922-1073`
- Modify: `tests/test_git_project.py`

**Interfaces:**
- Consumes: `inspect_project`, `record_project`, `ProjectError`
- Produces: `obsidian-wiki project-state`
- Produces: `obsidian-wiki project-record`
- Exit codes remain `0`, `2`, `3`, `4`, or `5` as defined by `ProjectError`.

- [ ] **Step 1: Add CLI test helper and state command test**

Append:

```python
def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
    )


def test_project_state_cli_emits_json(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")

    proc = run_cli("project-state", str(clone), "--json")

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["project_id"] == "git:github.com/acme/project"
    assert data["safe"] is True
    assert data["tracked_ref"] == "refs/heads/main"
```

- [ ] **Step 2: Add unsafe and record CLI tests**

Append:

```python
def test_project_state_cli_uses_unsafe_exit_code(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    (clone / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    proc = run_cli("project-state", str(clone), "--json")

    assert proc.returncode == 4
    data = json.loads(proc.stdout)
    assert data["safe"] is False
    assert data["safety_error"] == "dirty_worktree"


def test_project_record_cli_writes_manifest(tmp_path: Path) -> None:
    _bare, clone = make_remote_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "https://github.com/acme/project.git")
    vault = tmp_path / "vault"
    vault.mkdir()

    proc = run_cli(
        "project-record",
        str(vault),
        "--repo",
        str(clone),
        "--slug",
        "project",
        "--expected-commit",
        git(clone, "rev-parse", "HEAD").stdout.strip(),
        "--page",
        "projects/project/project.md",
        "--json",
    )

    assert proc.returncode == 0
    assert json.loads(proc.stdout)["status"] == "recorded"
    saved = json.loads((vault / ".manifest.json").read_text())
    assert "git:github.com/acme/project" in saved["projects"]
```

- [ ] **Step 3: Run CLI tests and confirm parser failure**

Run:

```bash
pytest -q tests/test_git_project.py -k "cli"
```

Expected: commands fail with `invalid choice: 'project-state'` or `invalid choice: 'project-record'`.

- [ ] **Step 4: Add CLI handlers**

Insert near the other command handlers in `obsidian_wiki/cli.py`:

```python
def _print_project_output(result: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result))
        return
    for key in (
        "status", "project_id", "tracked_ref", "head_commit",
        "safe", "safety_error", "delta_mode",
    ):
        if key in result:
            print(f"{key}: {result[key]}")


def cmd_project_state(args: argparse.Namespace) -> int:
    from obsidian_wiki.git_project import ProjectError, inspect_project

    try:
        state = inspect_project(
            Path(args.repo).expanduser().resolve(),
            expected_repo_id=args.expected_repo_id,
            remote_override=args.remote,
            branch_override=args.branch,
            since=args.since,
        )
    except ProjectError as exc:
        _print_project_output(exc.as_dict(), as_json=args.json)
        return exc.exit_code
    result = state.to_dict()
    result["status"] = "safe" if state.safe else state.mode
    _print_project_output(result, as_json=args.json)
    if state.mode == "legacy_local_only":
        return 0
    return 0 if state.safe else 4


def cmd_project_record(args: argparse.Namespace) -> int:
    from obsidian_wiki.git_project import ProjectError, inspect_project, record_project

    try:
        state = inspect_project(
            Path(args.repo).expanduser().resolve(),
            expected_repo_id=args.expected_repo_id,
            remote_override=args.remote,
            branch_override=args.branch,
        )
        result = record_project(
            Path(args.vault).expanduser().resolve(),
            state,
            expected_commit=args.expected_commit,
            slug=args.slug,
            pages=args.page or [],
        )
    except ProjectError as exc:
        _print_project_output(exc.as_dict(), as_json=args.json)
        return exc.exit_code
    _print_project_output(result, as_json=args.json)
    return 0
```

- [ ] **Step 5: Add parser definitions**

Insert before `return p` in `build_parser()`:

```python
    ps = sub.add_parser(
        "project-state",
        help="identify a Git project and verify it matches its canonical remote branch",
    )
    ps.add_argument("repo", help="path inside the Git repository")
    ps.add_argument("--expected-repo-id", help="require this git:<host/path> identity")
    ps.add_argument("--remote", help="explicit remote name for a new project")
    ps.add_argument("--branch", help="shared branch name or refs/heads/<name>")
    ps.add_argument("--since", help="previous full or abbreviated commit cursor")
    ps.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ps.set_defaults(func=cmd_project_state)

    pr = sub.add_parser(
        "project-record",
        help="record a safely aligned Git project in the vault manifest",
    )
    pr.add_argument("vault", help="path to the Obsidian vault")
    pr.add_argument("--repo", required=True, help="path inside the Git repository")
    pr.add_argument("--slug", required=True, help="vault project directory slug")
    pr.add_argument(
        "--expected-commit",
        required=True,
        help="preflight HEAD commit; refuse to record if repository state changed",
    )
    pr.add_argument("--expected-repo-id", help="require this git:<host/path> identity")
    pr.add_argument("--remote", help="explicit remote name for a new project")
    pr.add_argument("--branch", help="shared branch name or refs/heads/<name>")
    pr.add_argument("--page", action="append", help="vault-relative project page (repeatable)")
    pr.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    pr.set_defaults(func=cmd_project_record)
```

- [ ] **Step 6: Run focused CLI tests**

Run:

```bash
pytest -q tests/test_git_project.py -k "cli"
```

Expected: all CLI tests pass.

- [ ] **Step 7: Run all project tests**

Run:

```bash
pytest -q tests/test_git_project.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add obsidian_wiki/cli.py tests/test_git_project.py
git commit -m "feat: expose safe project manifest commands"
```

---

### Task 5: Update skills and public documentation to use the safe MVP

**Files:**
- Create: `tests/test_git_project_docs.py`
- Modify: `.skills/wiki-update/SKILL.md`
- Modify: `.skills/wiki-query/SKILL.md`
- Modify: `.skills/llm-wiki/SKILL.md`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `README_TW.md`

**Interfaces:**
- Consumes: `obsidian-wiki project-state ... --json`
- Consumes: `obsidian-wiki project-record ... --json`
- Produces: one consistent documented V2 schema and safety workflow.

- [ ] **Step 1: Add failing documentation contract tests**

Create `tests/test_git_project_docs.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_wiki_update_uses_safe_cli_and_v2_frontmatter() -> None:
    text = read(".skills/wiki-update/SKILL.md")
    assert "obsidian-wiki project-state" in text
    assert "obsidian-wiki project-record" in text
    assert "--expected-commit" in text
    assert "source_repo:" in text
    assert "source_ref:" in text
    assert '"source_cwd": "/absolute/path/to/project"' not in text


def test_wiki_query_does_not_treat_v2_manifest_as_local_path_storage() -> None:
    text = read(".skills/wiki-query/SKILL.md")
    assert "source_repo" in text
    assert "matching `repo_id`" in text
    assert "`.projects.<name>.source_cwd` — this is the authoritative path" not in text


def test_llm_wiki_distinguishes_generic_sources_from_git_projects() -> None:
    text = read(".skills/llm-wiki/SKILL.md")
    assert "Git project identity" in text
    assert '"project_schema": 2' in text
    assert "refs/heads/main" in text


def test_bootstrap_and_readmes_document_the_safety_gate() -> None:
    assert "project-state" in read("AGENTS.md")
    assert "clean worktree" in read("README.md")
    assert "乾淨的 worktree" in read("README_TW.md")
```

- [ ] **Step 2: Run documentation tests and confirm failure**

Run:

```bash
pytest -q tests/test_git_project_docs.py
```

Expected: four tests fail because the current docs still describe
`source_cwd`/`last_commit_synced`.

- [ ] **Step 3: Rewrite the `wiki-update` Git preflight and tracking sections**

In `.skills/wiki-update/SKILL.md`, replace the current manifest/delta preflight
with this exact workflow:

````markdown
### Git project preflight

For a Git project, read the matching manifest entry before scanning source:

1. Determine the intended project slug.
2. If a V2 entry with that `project_slug` exists, pass its `repo_id` as
   `--expected-repo-id`, its `tracked_ref` as `--branch`, and its
   `cursor.commit` as `--since`.
3. Otherwise call the command without those V2 arguments:

```bash
obsidian-wiki project-state "$PWD" --since "<previous-commit-if-any>" --json
```

Stop before reading project content unless the JSON reports `"safe": true`.
The command requires a clean worktree and `HEAD` equal to the canonical
remote-tracking commit. It never fetches. If it reports
`legacy_local_only`, preserve the existing personal path-based workflow.

Use `delta_mode` as follows:
- `same` — skip content distillation, but allow a safe legacy entry upgrade.
- `incremental` — inspect `git log <previous>..HEAD` and changed files.
- `full` — scan the verified current worktree.
````

Update the project page frontmatter template to include:

```yaml
source_repo: git:<repo-id>
source_ref: refs/heads/<branch>
```

Remove `source_path` from the Git project template. Replace the manifest JSON
example with the V2 example from the approved spec.

After all page, index, log, and hot-cache writes succeed, add:

````markdown
Record the cursor last:

```bash
obsidian-wiki project-record "$OBSIDIAN_VAULT_PATH" \
  --repo "$PWD" \
  --slug "<project-slug>" \
  --expected-commit "<preflight-head-commit>" \
  --expected-repo-id "git:<repo-id>" \
  --branch "refs/heads/<branch>" \
  --page "projects/<project-slug>/<page>.md" \
  --json
```

Repeat `--page` for every project page produced or retained. If the command
fails because repository state changed during the wiki write, keep the pages,
report that the cursor did not advance, and do not retry automatically.
````

Change the log example so it records `source_repo=git:<repo-id>` and
`cursor=<full-sha>` instead of `source_cwd`.

- [ ] **Step 4: Rewrite `wiki-query` project source resolution**

Replace `.skills/wiki-query/SKILL.md`'s `source_cwd`-authoritative block with:

````markdown
**Surface a project source path only when it is locally verified.**

For a V2 project page, read `source_repo` or find the manifest entry by
`project_slug`. Inspect the current working directory's Git root with:

```bash
obsidian-wiki project-state "$PWD" \
  --expected-repo-id "<source_repo>" \
  --branch "<source_ref>" \
  --json
```

Include `Source code:` only when the command resolves the matching `repo_id`.
The query remains read-only and may use the matching repository root even when
the safety result is false; safety controls `wiki-update`, not code-path
display. If CWD is not the matching repository, answer from wiki content and
omit `Source code:`.

For a legacy project only, fall back to `source_cwd` after verifying that the
path exists. Label this internally as legacy behavior.
````

Update the answer-format note to refer to a verified project root rather than
`source_cwd`.

- [ ] **Step 5: Add the V2 Git project exception to `llm-wiki`**

Immediately after the generic canonical source-key rule in
`.skills/llm-wiki/SKILL.md`, add:

````markdown
### Git project identity

The absolute-path rule above applies to generic `sources`, not to
`manifest.projects` entries created by `wiki-update`. Remotely identified Git
projects use portable V2 keys:

```json
{
  "projects": {
    "git:github.com/acme/project": {
      "project_schema": 2,
      "kind": "git",
      "repo_id": "github.com/acme/project",
      "project_slug": "project",
      "remote": {
        "canonical_url": "https://github.com/acme/project.git"
      },
      "tracked_ref": "refs/heads/main",
      "cursor": {
        "commit": "<full-40-character-sha>",
        "synced_at": "<ISO-8601>"
      },
      "pages_in_vault": ["projects/project/project.md"]
    }
  }
}
```

V2 project entries and generated project pages never store an absolute clone
path. New/updated project pages use `source_repo` and `source_ref`. Generic
file/history sources keep their existing canonical absolute path rules.
````

- [ ] **Step 6: Update the always-on bootstrap summary**

Replace the repeat-run sentence in `AGENTS.md` with:

```markdown
For a remotely identified Git project, run `obsidian-wiki project-state`
before scanning. V2 manifest entries use `git:<host/path>` plus a shared
`refs/heads/<branch>` and full commit cursor. Only distill a clean worktree
whose `HEAD` matches that branch's remote-tracking commit; call
`project-record` only after all wiki writes succeed. Repositories without a
remote retain the legacy `source_cwd` workflow.
```

- [ ] **Step 7: Update English and Traditional Chinese README project-sync text**

After the `/wiki-update` paragraph near the end of `README.md`, add:

```markdown
For Git projects with a remote, project identity is portable across clones:
SSH and HTTPS URLs normalize to the same `git:<host/path>` manifest key.
Shared updates are intentionally strict — `/wiki-update` requires a clean
worktree whose `HEAD` matches the canonical remote branch. It never fetches or
ingests feature-branch/uncommitted state automatically. Local-only repositories
continue using the legacy path workflow.
```

Add the corresponding paragraph to `README_TW.md`:

```markdown
對有 remote 的 Git project，project identity 可跨不同 clone 使用：SSH 與
HTTPS URL 會正規化成相同的 `git:<host/path>` manifest key。共享更新刻意採
嚴格模式：`/wiki-update` 只接受乾淨的 worktree，而且 `HEAD` 必須與
canonical remote branch 相同。它不會自動 fetch，也不會 ingest feature
branch 或未 commit 的狀態。只有本機、沒有 remote 的 repository 會繼續使用
legacy path workflow。
```

- [ ] **Step 8: Run documentation contract tests**

Run:

```bash
pytest -q tests/test_git_project_docs.py
```

Expected: all four tests pass.

- [ ] **Step 9: Run focused implementation tests**

Run:

```bash
pytest -q tests/test_git_project.py tests/test_git_project_docs.py
```

Expected: all tests pass.

- [ ] **Step 10: Run the full test suite**

Run:

```bash
pytest -q
```

Expected: all repository tests pass with zero failures.

- [ ] **Step 11: Run CLI smoke checks**

Run:

```bash
python -m obsidian_wiki.cli project-state . --json
python -m obsidian_wiki.cli --help
```

Expected:

- The first command emits valid JSON. It may exit `4` in this development
  checkout if local `HEAD` does not equal `origin/main`; that is correct.
- Help output lists `project-state` and `project-record`.

- [ ] **Step 12: Commit Task 5**

```bash
git add \
  tests/test_git_project_docs.py \
  .skills/wiki-update/SKILL.md \
  .skills/wiki-query/SKILL.md \
  .skills/llm-wiki/SKILL.md \
  AGENTS.md README.md README_TW.md
git commit -m "docs: adopt safe portable Git project workflow"
```

---

## Final Verification Checklist

- [ ] `pytest -q` passes.
- [ ] `git diff --check` reports no whitespace errors.
- [ ] `rg -n '"source_cwd": "/absolute/path/to/project"' .skills/wiki-update/SKILL.md` returns no matches.
- [ ] `rg -n 'source_repo|source_ref|project-state|project-record' .skills/wiki-update/SKILL.md .skills/wiki-query/SKILL.md .skills/llm-wiki/SKILL.md` finds every new contract.
- [ ] A V2 manifest fixture preserves its generic `sources`, `stats`, and unknown fields after `project-record`.
- [ ] A dirty or branch-diverged temporary clone exits `project-state` with code `4`.
- [ ] A clean aligned clone records a full 40-character cursor and no absolute clone path.
- [ ] `git status --short` contains only intentional implementation changes before the final commit and is clean afterward.
