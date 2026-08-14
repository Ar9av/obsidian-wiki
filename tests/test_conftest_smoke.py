"""Smoke tests for the shared conftest fixtures (issue #167 wave 1)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from conftest import (
    _run_cli,
    build_index_state,
    make_fake_codegraph_bin,
    make_project,
    make_repo_two_commits,
)


def test_make_project_creates_git_repo_with_commit(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"README.md": "# hi\n"})

    proc = subprocess.run(["git", "log", "--oneline"], capture_output=True, text=True, cwd=project)
    assert proc.returncode == 0
    assert "initial commit" in proc.stdout
    assert (project / "README.md").read_text(encoding="utf-8") == "# hi\n"


def test_make_project_without_git(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"src/a.py": "x = 1\n"}, git=False)

    assert (project / "src" / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not (project / ".git").exists()


def test_fake_codegraph_bin_is_executable_and_answers_impact(tmp_path: Path) -> None:
    bin_path = make_fake_codegraph_bin(tmp_path)

    assert os.access(bin_path, os.X_OK)
    proc = subprocess.run([str(bin_path), "impact", "Foo", "--json"], capture_output=True, text=True)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["symbol"] == "Foo"
    names = [entry["name"] for entry in data["affected"]]
    assert "Foo" in names
    assert all("filePath" in entry for entry in data["affected"])


def test_fake_codegraph_bin_broke_mode_exits_1(tmp_path: Path) -> None:
    bin_path = make_fake_codegraph_bin(tmp_path)

    env = os.environ.copy()
    env["FAKE_CODEGRAPH_MODE"] = "broke"
    proc = subprocess.run(
        [str(bin_path), "query", "x", "--json"], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 1
    assert proc.stderr


def test_build_index_state_fresh_is_newer_than_sources(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"src/a.py": "x = 1\n"}, git=False)

    build_index_state(project)

    db = project / ".codegraph" / "codegraph.db"
    src = project / "src" / "a.py"
    assert db.exists()
    assert db.stat().st_mtime >= src.stat().st_mtime
    assert json.loads((project / ".codegraph" / "source.json").read_text())["version"] == 1


def test_build_index_state_stale_is_older_than_sources(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"src/a.py": "x = 1\n"}, git=False)

    build_index_state(project, fresh=False)

    db = project / ".codegraph" / "codegraph.db"
    src = project / "src" / "a.py"
    assert db.stat().st_mtime < src.stat().st_mtime


def test_make_repo_two_commits_returns_sha_of_first(tmp_path: Path) -> None:
    project, sha_first = make_repo_two_commits(tmp_path)

    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], capture_output=True, text=True, cwd=project
    )
    assert count.stdout.strip() == "2"
    assert len(sha_first) == 40
    assert (project / "src" / "foo.py").exists()
    assert (project / "src" / "bar.py").exists()


def test_run_cli_runs_in_cwd_with_env_overrides(tmp_path: Path) -> None:
    project = make_project(tmp_path, {"src/a.py": "x = 1\n"})

    proc = _run_cli(project, "--version", env_overrides={"FAKE_VAR": "1"})

    assert proc.returncode == 0
    assert "obsidian-wiki" in proc.stdout
