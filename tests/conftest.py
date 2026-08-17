"""Shared pytest test fixtures for the obsidian-wiki test suite.

These are plain module-level helper functions (not @pytest.fixture) so their
signatures are explicit and tests call them directly:

    from conftest import make_project, _run_cli

They support the issue #167 code-graph backend tests: building throwaway git
projects, a fake codegraph CLI binary, and .codegraph index state.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True, scope="session")
def _pin_subprocess_imports_to_this_checkout() -> None:
    """Make CLI subprocesses import this working tree, not an installed copy.

    Every test helper here spawns ``python -m obsidian_wiki.cli`` with a copy
    of ``os.environ``. Without this, ``sys.path[0]`` is the subprocess cwd, so a
    test that runs from a temp dir silently exercises whatever ``obsidian_wiki``
    happens to be pip-installed — which passes or fails for reasons unrelated to
    the code under test. Setting PYTHONPATH once here covers every helper.
    """
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), *([p] if (p := os.environ.get("PYTHONPATH")) else [])]
    )


def make_project(tmp_path: Path, files: dict[str, str], *, git: bool = True) -> Path:
    """Write a mini source tree from files (relpath -> content) and, if git,
    commit it as an initial commit (needed for --since tests)."""
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    for relpath, content in files.items():
        path = project / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if git:
        _git(project, "init", "-q")
        _git(project, "config", "user.email", "test@example.com")
        _git(project, "config", "user.name", "Wiki Tester")
        _git(project, "add", "-A")
        _git(project, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "initial commit")
    return project


def make_fake_codegraph_bin(tmp_path: Path) -> Path:
    """Copy tests/fixtures/codegraph_fake.py into a bin dir, chmod +x, and
    return the executable path (to pass as CODE_UNDERSTANDING_CODEGRAPH_BIN)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).parent / "fixtures" / "codegraph_fake.py"
    dest = bin_dir / "codegraph"
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dest


def build_index_state(project: Path, *, fresh: bool = True) -> None:
    """Create project/.codegraph/codegraph.db (empty; mtime matters) plus
    source.json. If fresh=False, backdate codegraph.db to 2000-01-01 so it
    is older than the tracked source files (stale index)."""
    codegraph_dir = project / ".codegraph"
    codegraph_dir.mkdir(parents=True, exist_ok=True)
    (codegraph_dir / "codegraph.db").write_bytes(b"")
    (codegraph_dir / "source.json").write_text(
        json.dumps({"sourceDir": str(project.resolve()), "version": 1}),
        encoding="utf-8",
    )
    if not fresh:
        stale = time.mktime((2000, 1, 1, 0, 0, 0, 0, 0, -1))
        os.utime(codegraph_dir / "codegraph.db", (stale, stale))


def _run_cli(
    cwd: Path,
    *args: str,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `python -m obsidian_wiki.cli <args>` in cwd with the current
    environment merged with env_overrides."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )


def make_repo_two_commits(tmp_path: Path) -> tuple[Path, str]:
    """A project with 2 commits: first adds src/foo.py + src/only_first.py,
    second modifies foo.py and adds src/bar.py (only_first.py untouched).
    Returns (project, sha_of_first_commit) for --since delta tests.
    The untouched third file makes the delta set ({foo, bar}) strictly
    smaller than the full tracked set ({foo, bar, only_first}), so tests
    actually prove --since filtering rather than passing vacuously."""
    project = make_project(
        tmp_path,
        {
            "src/foo.py": "def foo():\n    return 1\n",
            "src/only_first.py": "x = 1\n",
        },
    )
    sha_first = _git(project, "rev-parse", "HEAD").stdout.strip()
    (project / "src/foo.py").write_text("def foo():\n    return 2\n", encoding="utf-8")
    (project / "src/bar.py").write_text("def bar():\n    return 3\n", encoding="utf-8")
    _git(project, "add", "-A")
    _git(project, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "second commit")
    return project, sha_first


def _git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=project,
        check=True,
    )
