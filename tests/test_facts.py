"""Tests for _meta/facts.md: the approved-claims table and the draft check."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from obsidian_wiki import facts as fx
from obsidian_wiki.memory import MemoryError_

ROOT = Path(__file__).resolve().parents[1]


def _cli(*argv: str, stdin: str | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, OBSIDIAN_WIKI_NO_UPDATE_CHECK="1", PYTHONPATH=str(ROOT))
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "facts", *argv],
        input=stdin, capture_output=True, text=True, cwd=cwd or ROOT, env=env,
    )


def _claims() -> list:
    return [
        fx.Claim("f1", "We have 40 paying customers", "stripe", "2026-11-01"),
        fx.Claim("f2", "First SOC 2 certified agent firewall", "audit report", "2026-10-01"),
        fx.Claim("f3", "ARR is $1M", "stripe", "2025-01-01", status="retired"),
    ]


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("$2M ARR", {"2000000"}),
        ("2 million users", {"2000000"}),
        ("2,000,000 rows", {"2000000"}),
        ("1.5k stars", {"1500"}),
        ("40% faster", {"40%"}),
        ("3x cheaper", {"3x"}),
        ("founded in 2021", {"2021"}),
        ("over 3 months", {"3"}),
        ("see [[page 42]] and `retry 5`", set()),
        ("https://example.com/v/12 and v1.2.3", set()),
    ],
)
def test_numbers_are_canonicalised(text: str, values: set) -> None:
    assert fx.numbers_in(text) == values


def test_backed_numbers_pass_and_new_numbers_are_flagged() -> None:
    findings = fx.check_text("We have 40 customers. We have 41 customers.", _claims())
    assert [(f["text"], f["status"], f["missing"]) for f in findings] == [
        ("We have 41 customers.", "unsupported", ["41"]),
    ]


def test_spelling_of_a_number_does_not_matter() -> None:
    claims = [fx.Claim("f1", "Revenue passed $2,000,000", "stripe", "2026-11-01")]
    assert fx.check_text("Revenue passed 2 million dollars.", claims) == []


def test_absolute_needs_a_fact_on_the_same_subject() -> None:
    claims = _claims()
    assert fx.check_text("We are the first SOC 2 certified firewall.", claims) == []
    findings = fx.check_text("We are the first company in Europe.", claims)
    assert findings and findings[0]["missing"] == ["first"]


def test_retired_claim_is_named() -> None:
    (finding,) = fx.check_text("Our ARR is $1M today.", _claims())
    assert finding["status"] == "retired"
    assert finding["fact"] == "f3"
    assert finding["missing"] == ["$1M"]


def test_sentences_without_numbers_or_absolutes_are_ignored() -> None:
    assert fx.check_text("We help security teams ship faster.", []) == []


def test_frontmatter_code_tables_and_headings_are_skipped() -> None:
    text = (
        "---\ntitle: Post 2026\nupdated: 2026-11-01\n---\n"
        "# Top 10 lessons\n\n"
        "```\nretry 500 times\n```\n"
        "| 99 | col |\n|---|---|\n"
        "> quoted 77\n"
        "We grew 3x in a year.\n"
    )
    (finding,) = fx.check_text(text, [])
    assert finding["line"] == 13
    assert finding["missing"] == ["3x"]


def test_list_markers_are_not_numbers() -> None:
    assert fx.check_text("1. Ship the parser.\n2. Write the docs.", []) == []


def test_add_list_retire_round_trip(tmp_path: Path) -> None:
    first = fx.add_fact(tmp_path, "We have 40 paying customers", source="stripe", as_of="2026-11-01")
    second = fx.add_fact(tmp_path, "ARR is $1M", source="stripe", as_of="2025-01-01")
    assert (first.id, second.id) == ("f1", "f2")

    again = fx.add_fact(tmp_path, "we have 40  paying customers", source="crm", as_of="2026-11-10")
    assert again.id == "f1" and again.source == "crm"

    retired = fx.retire_fact(tmp_path, "F2", reason="passed $2M")
    assert retired.status == "retired" and "passed $2M" in retired.note

    loaded = fx.load_facts(tmp_path)
    assert [(c.id, c.status, c.as_of) for c in loaded] == [
        ("f1", "approved", "2026-11-10"),
        ("f2", "retired", "2025-01-01"),
    ]
    text = (tmp_path / fx.FACTS_REL).read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: Approved Facts\n")
    assert "| f2 | ARR is $1M | stripe | 2025-01-01 | retired |" in text


def test_hand_edited_rows_parse_and_get_ids(tmp_path: Path) -> None:
    (tmp_path / "_meta").mkdir()
    (tmp_path / fx.FACTS_REL).write_text(
        fx.render_facts([fx.Claim("f4", "Team of 6", "owner", "2026-11-01")])
        + "|  | Pipes \\| work in claims | owner | 2026-11-02 |  |  |\n",
        encoding="utf-8",
    )
    loaded = fx.load_facts(tmp_path)
    assert [(c.id, c.text) for c in loaded] == [("f4", "Team of 6"), ("f5", "Pipes | work in claims")]

    fx.add_fact(tmp_path, "Based in Berlin", source="owner", as_of="2026-11-03")
    assert [c.id for c in fx.load_facts(tmp_path)] == ["f4", "f5", "f6"]


def test_created_date_survives_rewrites(tmp_path: Path) -> None:
    (tmp_path / "_meta").mkdir()
    (tmp_path / fx.FACTS_REL).write_text(fx.render_facts([], created="2026-01-01"), encoding="utf-8")
    fx.add_fact(tmp_path, "Team of 6", source="owner")
    assert "created: 2026-01-01" in (tmp_path / fx.FACTS_REL).read_text(encoding="utf-8")


def test_validation(tmp_path: Path) -> None:
    with pytest.raises(MemoryError_, match="--source"):
        fx.add_fact(tmp_path, "Team of 6", source=" ")
    with pytest.raises(MemoryError_, match="YYYY-MM-DD"):
        fx.add_fact(tmp_path, "Team of 6", source="owner", as_of="last week")
    with pytest.raises(MemoryError_, match="no fact"):
        fx.retire_fact(tmp_path, "f9")


def test_staleness() -> None:
    claim = fx.Claim("f1", "Team of 6", "owner", "2026-01-01")
    assert claim.is_stale(on="2026-11-15", days=180)
    assert not claim.is_stale(on="2026-03-01", days=180)
    assert not fx.Claim("f2", "x", "y", "2020-01-01", status="retired").is_stale(on="2026-11-15")
    assert not fx.Claim("f3", "x", "y", "").is_stale(on="2026-11-15")


def test_cli_check_exits_2_on_unbacked_claims(tmp_path: Path) -> None:
    fx.add_fact(tmp_path, "We have 40 paying customers", source="stripe", as_of="2026-11-01")
    draft = tmp_path / "draft.md"
    draft.write_text("We serve 40 customers.\nWe are the fastest tool.\n", encoding="utf-8")

    result = _cli("check", str(draft), "--vault", str(tmp_path), "--json")
    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["approved"] == 1
    assert [(f["line"], f["missing"]) for f in payload["findings"]] == [(2, ["fastest"])]

    clean = _cli("check", "-", "--vault", str(tmp_path), stdin="We serve 40 customers.\n")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "every claim-shaped sentence is backed" in clean.stdout


def test_cli_add_list_retire(tmp_path: Path) -> None:
    missing_source = _cli("add", "Team of 6", "--vault", str(tmp_path))
    assert missing_source.returncode == 1
    assert "--source" in missing_source.stderr

    assert _cli("add", "Team", "of", "6", "--source", "owner", "--as-of", "2026-01-01", "--vault", str(tmp_path)).returncode == 0
    listed = _cli("list", "--vault", str(tmp_path), "--stale-days", "30")
    assert "f1" in listed.stdout and "Team of 6" in listed.stdout and "STALE" in listed.stdout

    assert _cli("retire", "f1", "--vault", str(tmp_path)).returncode == 0
    assert "no approved facts" in _cli("list", "--vault", str(tmp_path)).stdout
    assert "retired" in _cli("list", "--all", "--vault", str(tmp_path)).stdout


def test_facts_file_is_not_an_index_page(tmp_path: Path) -> None:
    from obsidian_wiki.memory import SKIP_DIRS

    assert fx.FACTS_REL.split("/")[0] in SKIP_DIRS
