"""Tests for the ingest preflight (one source file, one primary page)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from obsidian_wiki.ingest_guard import guard_sources, source_identity


def _page(vault: Path, rel: str, *, title: str, extra: str = "") -> None:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: {title}\ncategory: references\n{extra}---\n# {title}\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "identity"),
    [
        ("report.pdf", "report"),
        ("report.pdf.md", "report"),
        ("_raw/import/Report.md", "report"),
        ("C:\\docs\\Q3 Plan.docx", "q3-plan"),
        ("notes.v2.md", "notes.v2"),
        ("deck_final.pptx.md", "deck-final"),
    ],
)
def test_source_identity_strips_document_extensions(name: str, identity: str) -> None:
    assert source_identity(name) == identity


def test_existing_converted_page_is_updated_not_duplicated(tmp_path: Path) -> None:
    _page(tmp_path, "references/report.md", title="report")
    (tmp_path / ".manifest.json").write_text(
        json.dumps({"sources": {"_raw/_archived/report.md": {"pages_produced": ["references/report.md"]}}}),
        encoding="utf-8",
    )
    pdf = tmp_path / "inbox" / "report.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.7")

    result = guard_sources(tmp_path, [pdf])

    assert result == {
        "sources": [
            {
                "source": "inbox/report.pdf",
                "identity": "report",
                "status": "update",
                "pages": ["references/report.md"],
                "prior_sources": ["_raw/_archived/report.md"],
                "siblings": [],
            }
        ],
        "blocked": [],
    }


def test_two_pages_for_one_source_block_the_write(tmp_path: Path) -> None:
    _page(tmp_path, "references/report.md", title="report")
    _page(tmp_path, "references/report.pdf.md", title="report.pdf")

    result = guard_sources(tmp_path, [tmp_path / "report.pdf"])

    assert result["sources"][0]["status"] == "blocked"
    assert result["sources"][0]["pages"] == ["references/report.md", "references/report.pdf.md"]
    assert result["blocked"] == ["report.pdf"]


def test_title_match_and_redirect_stub(tmp_path: Path) -> None:
    _page(tmp_path, "references/q3-planning.md", title="Q3 Plan.docx")
    _page(tmp_path, "references/q3-plan.md", title="Q3 Plan", extra='redirects_to: "[[q3-planning]]"\n')

    result = guard_sources(tmp_path, [tmp_path / "Q3 Plan.docx", tmp_path / "fresh.pdf"])

    assert [(r["status"], r["pages"]) for r in result["sources"]] == [
        ("update", ["references/q3-planning.md"]),
        ("create", []),
    ]


def test_same_document_in_two_formats_are_siblings(tmp_path: Path) -> None:
    result = guard_sources(tmp_path, [tmp_path / "report.pdf", tmp_path / "Report.docx"])

    assert [(r["status"], r["siblings"]) for r in result["sources"]] == [
        ("create", ["Report.docx"]),
        ("create", ["report.pdf"]),
    ]


def test_cli_exits_2_when_blocked(tmp_path: Path) -> None:
    _page(tmp_path, "references/report.md", title="report")
    _page(tmp_path, "concepts/report.pdf.md", title="report.pdf")
    src = tmp_path / "src"
    src.mkdir()
    (src / "report.pdf").write_bytes(b"%PDF-1.7")
    (src / "other.md").write_text("# other\n", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "ingest-guard", str(tmp_path), str(src)],
        capture_output=True, text=True,
    )

    assert proc.returncode == 2, proc.stderr
    data = json.loads(proc.stdout)
    assert {r["identity"]: r["status"] for r in data["sources"]} == {"other": "create", "report": "blocked"}
    assert data["blocked"] == ["src/report.pdf"]
