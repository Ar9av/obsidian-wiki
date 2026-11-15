"""Tests for the playbook evidence ranking behind wiki-playbook-review."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from obsidian_wiki.playbooks import parse_since, playbook_evidence

ROOT = Path(__file__).resolve().parents[1]
SINCE = date(2026, 11, 8)


def _page(vault: Path, rel: str, *, updated: str, tags: str = "[]", body: str = "", title: str = "") -> None:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntitle: {title or path.stem}\ncategory: {rel.split('/')[0]}\ntags: {tags}\n"
        f"sources: []\ncreated: 2026-01-01\nupdated: {updated}\nsummary: about {path.stem}\n---\n"
        f"# {title or path.stem}\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    _page(tmp_path, "skills/sales-discovery-call.md", updated="2026-06-01",
          tags="[sales, customer]", body="Step 1: ask about [[pricing]].")
    _page(tmp_path, "skills/deploy-runbook.md", updated="2026-11-10", tags="[infra]")
    _page(tmp_path, "projects/app/skills/release-checklist.md", updated="2026-03-01", tags="[release]")
    _page(tmp_path, "references/onboarding.md", updated="2026-02-01", tags="[playbook, onboarding]")
    _page(tmp_path, "concepts/untouched-playbook-adjacent.md", updated="2026-01-01",
          body="[[sales-discovery-call]]")
    # Evidence inside the window.
    _page(tmp_path, "journal/meetings/2026-11-10-acme.md", updated="2026-11-10T15:00:00Z",
          tags="[meeting, customer]", body="Objection handled per [[sales-discovery-call]]. Code: `[[deploy-runbook]]`")
    _page(tmp_path, "concepts/pricing.md", updated="2026-11-12", tags="[pricing]")
    _page(tmp_path, "entities/acme.md", updated="2026-11-11", tags="[customer, sales]")
    _page(tmp_path, "entities/globex.md", updated="2026-11-11", tags="[sales, visibility/internal]")
    _page(tmp_path, "journal/2026-11-09.md", updated="2026-11-09", tags="[onboarding]",
          body="Shipped [release checklist](../projects/app/skills/release-checklist.md).")
    (tmp_path / "log.md").write_text(
        "# Log\n\n"
        "- [2026-11-01T10:00:00Z] LINT note=release-checklist\n"
        "- [2026-11-13T10:00:00Z] INGEST_MEETING source=meeting:wispr/1 playbook=release-checklist\n",
        encoding="utf-8",
    )
    return tmp_path


def _by_path(result: dict) -> dict:
    return {book["playbook"]: book for book in result["playbooks"]}


def test_playbooks_are_skills_folders_and_tagged_pages(vault: Path) -> None:
    result = playbook_evidence(vault, since=SINCE)
    assert result["playbooks_total"] == 4


def test_evidence_and_reasons(vault: Path) -> None:
    books = _by_path(playbook_evidence(vault, since=SINCE))
    sales = books["skills/sales-discovery-call.md"]
    assert [(e["path"], e["score"]) for e in sales["evidence"]] == [
        ("journal/meetings/2026-11-10-acme.md", 4),  # link to (3) + shared tag customer (1)
        ("concepts/pricing.md", 2),                   # linked from the playbook
        ("entities/acme.md", 2),                      # two shared tags (ties sort by path)
    ]
    assert sales["evidence"][0]["reasons"] == ["links to the playbook", "shares tags: customer"]
    assert sales["score"] == 8
    assert sales["updated_in_window"] is False


def test_one_shared_tag_alone_and_system_tags_are_not_evidence(vault: Path) -> None:
    sales = _by_path(playbook_evidence(vault, since=SINCE))["skills/sales-discovery-call.md"]
    assert "entities/globex.md" not in {e["path"] for e in sales["evidence"]}


def test_links_in_code_are_ignored_and_markdown_links_count(vault: Path) -> None:
    books = _by_path(playbook_evidence(vault, since=SINCE))
    assert "skills/deploy-runbook.md" not in books  # only an inline-code "link"
    release = books["projects/app/skills/release-checklist.md"]
    assert [e["path"] for e in release["evidence"]] == ["journal/2026-11-09.md"]


def test_log_lines_in_window_name_the_playbook(vault: Path) -> None:
    release = _by_path(playbook_evidence(vault, since=SINCE))["projects/app/skills/release-checklist.md"]
    assert len(release["log"]) == 1 and "INGEST_MEETING" in release["log"][0]
    assert release["score"] == 3 + 2


def test_window_excludes_older_pages(vault: Path) -> None:
    books = _by_path(playbook_evidence(vault, since=date(2026, 11, 12)))
    sales = books["skills/sales-discovery-call.md"]
    assert [e["path"] for e in sales["evidence"]] == ["concepts/pricing.md"]


def test_single_playbook_filter(vault: Path) -> None:
    result = playbook_evidence(vault, since=SINCE, playbook="deploy-runbook")
    (book,) = result["playbooks"]
    assert book["playbook"] == "skills/deploy-runbook.md"
    assert book["evidence"] == [] and book["updated_in_window"] is True
    with pytest.raises(ValueError, match="no playbook"):
        playbook_evidence(vault, since=SINCE, playbook="concepts/pricing")


def test_ranked_by_score(vault: Path) -> None:
    order = [b["playbook"] for b in playbook_evidence(vault, since=SINCE)["playbooks"]]
    assert order[0] == "skills/sales-discovery-call.md"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("7d", date(2026, 11, 8)), ("2w", date(2026, 11, 1)), ("2026-10-01", date(2026, 10, 1))],
)
def test_parse_since(value: str, expected: date) -> None:
    assert parse_since(value, today=date(2026, 11, 15)) == expected


def test_parse_since_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="--since"):
        parse_since("last friday")


def test_cli(vault: Path) -> None:
    env = dict(os.environ, CI="true", PYTHONPATH=str(ROOT))
    run = lambda *a: subprocess.run(  # noqa: E731
        [sys.executable, "-m", "obsidian_wiki.cli", "playbooks", "--vault", str(vault), *a],
        capture_output=True, text=True, cwd=ROOT, env=env,
    )
    result = run("--since", "2026-11-08", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["playbooks"][0]["playbook"] == "skills/sales-discovery-call.md"
    text = run("--since", "2026-11-08")
    assert "skills/sales-discovery-call.md  score 8" in text.stdout
    assert run("--since", "whenever").returncode == 1
