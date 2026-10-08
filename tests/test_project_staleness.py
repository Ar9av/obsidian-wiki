"""Tests for `check_projects` — git-repo staleness against last_commit_synced.

`check_sources` hashes file sources and so is structurally blind to a repo
whose HEAD moved. These cover the branch that closes that gap, including the
cases where the answer must be "no evidence" rather than "stale".
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from obsidian_wiki.cache import check_projects

from conftest import _git, _run_cli, make_project, make_repo_two_commits


def write_manifest(vault: Path, projects: dict) -> None:
    vault.mkdir(parents=True, exist_ok=True)
    (vault / ".manifest.json").write_text(
        json.dumps({"projects": projects}), encoding="utf-8"
    )


def entry(project: Path, sha: str | None, **extra) -> dict:
    e = {"source_repo": "github.com/owner/project", "source_cwd_hint": str(project)}
    if sha is not None:
        e["last_commit_synced"] = sha
    e.update(extra)
    return e


def test_behind_reports_commit_count(tmp_path: Path) -> None:
    project, sha_first = make_repo_two_commits(tmp_path)
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(project, sha_first)})

    result = check_projects(vault)

    assert result["behind"] == [{
        "project": "proj",
        "commits": 1,
        "last_commit_synced": sha_first,
        "path": str(project),
    }]
    assert result["current"] == []


def test_head_synced_is_current(tmp_path: Path) -> None:
    project, _ = make_repo_two_commits(tmp_path)
    head = _git(project, "rev-parse", "HEAD").stdout.strip()
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(project, head)})

    result = check_projects(vault)

    assert result["current"] == ["proj"]
    assert result["behind"] == []


def test_short_sha_is_accepted(tmp_path: Path) -> None:
    """wiki-update's documented manifest example records an abbreviated sha."""
    project, sha_first = make_repo_two_commits(tmp_path)
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(project, sha_first[:7])})

    result = check_projects(vault)

    assert [p["commits"] for p in result["behind"]] == [1]


def test_rewritten_history_is_unreachable_not_behind(tmp_path: Path) -> None:
    """A sha that resolves but is no longer an ancestor must not be counted."""
    project, sha_first = make_repo_two_commits(tmp_path)
    # Record the tip we are about to abandon, then branch off its parent and
    # commit — the force-push/rebase case wiki-update warns about. The recorded
    # sha still resolves, but is no longer an ancestor of HEAD.
    abandoned = _git(project, "rev-parse", "HEAD").stdout.strip()
    _git(project, "checkout", "-q", "-b", "rewritten", sha_first)
    (project / "src/foo.py").write_text("def foo():\n    return 99\n", encoding="utf-8")
    _git(project, "add", "-A")
    _git(project, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "rewritten")
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(project, abandoned)})

    result = check_projects(vault)

    assert result["behind"] == []
    assert len(result["unreachable"]) == 1
    assert result["unreachable"][0]["project"] == "proj"
    assert result["unreachable"][0]["reason"] == "not_ancestor"
    assert result["unreachable"][0]["last_commit_synced"] == abandoned


def test_unknown_commit_is_distinguished_from_not_ancestor(tmp_path: Path) -> None:
    project, _ = make_repo_two_commits(tmp_path)
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(project, "0" * 40)})

    result = check_projects(vault)

    assert result["unreachable"][0]["reason"] == "unknown_commit"


def test_missing_checkout_is_unavailable_not_stale(tmp_path: Path) -> None:
    """The manifest is portable; a repo absent from this machine is not a finding."""
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(tmp_path / "nowhere", "abc1234")})

    result = check_projects(vault)

    assert result["behind"] == []
    assert result["unavailable"] == [{
        "project": "proj",
        "reason": "checkout_not_found",
        "path": str(tmp_path / "nowhere"),
    }]


def test_non_git_directory_is_unavailable(tmp_path: Path) -> None:
    plain = make_project(tmp_path, {"a.py": "x = 1\n"}, git=False)
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(plain, "abc1234")})

    result = check_projects(vault)

    assert result["unavailable"][0]["reason"] == "not_a_git_repo"


def test_entry_without_commit_is_unsynced(tmp_path: Path) -> None:
    project, _ = make_repo_two_commits(tmp_path)
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(project, None)})

    result = check_projects(vault)

    assert result["unsynced"] == ["proj"]
    assert result["behind"] == []


def test_blank_commit_is_unsynced_not_crash(tmp_path: Path) -> None:
    project, _ = make_repo_two_commits(tmp_path)
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(project, "   ")})

    assert check_projects(vault)["unsynced"] == ["proj"]


def test_missing_hint_is_unavailable(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": {"source_repo": "repo:local", "last_commit_synced": "abc"}})

    result = check_projects(vault)

    assert result["unavailable"] == [{"project": "proj", "reason": "no_source_cwd_hint"}]


def test_malformed_entry_does_not_sink_the_run(tmp_path: Path) -> None:
    """One bad entry must not hide a real finding in a sibling entry."""
    project, sha_first = make_repo_two_commits(tmp_path)
    vault = tmp_path / "vault"
    write_manifest(vault, {"bad": "not-a-dict", "proj": entry(project, sha_first)})

    result = check_projects(vault)

    assert [p["project"] for p in result["behind"]] == ["proj"]
    assert {"project": "bad", "reason": "malformed_entry"} in result["unavailable"]


def test_absent_and_malformed_manifest_are_empty(tmp_path: Path) -> None:
    empty = {"behind": [], "current": [], "unreachable": [], "unsynced": [], "unavailable": []}
    vault = tmp_path / "vault"
    vault.mkdir()
    assert check_projects(vault) == empty                      # no manifest at all

    (vault / ".manifest.json").write_text("{not json", encoding="utf-8")
    assert check_projects(vault) == empty                      # unreadable

    (vault / ".manifest.json").write_text('{"projects": []}', encoding="utf-8")
    assert check_projects(vault) == empty                      # wrong shape


def test_tilde_hint_is_expanded(tmp_path: Path, monkeypatch) -> None:
    project, sha_first = make_repo_two_commits(tmp_path)
    monkeypatch.setenv("HOME", str(project.parent))
    monkeypatch.setenv("USERPROFILE", str(project.parent))  # Windows
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(project, sha_first, source_cwd_hint="~/project")})

    assert [p["commits"] for p in check_projects(vault)["behind"]] == [1]


def test_hint_below_repo_root_still_resolves(tmp_path: Path) -> None:
    """`rev-parse --git-dir` works from a subdirectory; a `.git` test would not."""
    project, sha_first = make_repo_two_commits(tmp_path)
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(project, sha_first, source_cwd_hint=str(project / "src"))})

    assert [p["commits"] for p in check_projects(vault)["behind"]] == [1]


def test_linked_worktree_resolves(tmp_path: Path) -> None:
    """A worktree's `.git` is a file, so an is_dir() test would call it non-git."""
    project, sha_first = make_repo_two_commits(tmp_path)
    wt = tmp_path / "wt"
    subprocess.run(
        ["git", "-C", str(project), "worktree", "add", "-q", str(wt)],
        capture_output=True, text=True, check=True,
    )
    assert (wt / ".git").is_file()
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(project, sha_first, source_cwd_hint=str(wt))})

    assert [p["commits"] for p in check_projects(vault)["behind"]] == [1]


def test_cli_exits_2_on_a_finding_and_0_when_clean(tmp_path: Path) -> None:
    project, sha_first = make_repo_two_commits(tmp_path)
    head = _git(project, "rev-parse", "HEAD").stdout.strip()
    vault = tmp_path / "vault"

    write_manifest(vault, {"proj": entry(project, sha_first)})
    stale = _run_cli(tmp_path, "projects-check", str(vault))
    assert stale.returncode == 2, stale.stderr
    assert json.loads(stale.stdout)["behind"][0]["commits"] == 1

    write_manifest(vault, {"proj": entry(project, head)})
    clean = _run_cli(tmp_path, "projects-check", str(vault))
    assert clean.returncode == 0, clean.stderr
    assert json.loads(clean.stdout)["current"] == ["proj"]


def test_cli_does_not_exit_2_for_unavailable_only(tmp_path: Path) -> None:
    """An absent checkout must not fail a scheduled run."""
    vault = tmp_path / "vault"
    write_manifest(vault, {"proj": entry(tmp_path / "nowhere", "abc1234")})

    proc = _run_cli(tmp_path, "projects-check", str(vault))

    assert proc.returncode == 0, proc.stderr
