"""Per-link provenance read from ^[inferred] / ^[ambiguous] markers."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from obsidian_wiki.link_provenance import classify_links, link_provenance, summarize

FM = "---\ntitle: T\ncategory: concepts\ntags: [a]\nsources: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n"


def test_marker_after_a_link_marks_it_and_unmarked_stays_extracted():
    block = "Redis is fast because [[memory]]. ^[inferred] See also [[docs]]."
    assert classify_links(block) == [("memory", "inferred"), ("docs", "extracted")]


def test_ambiguous_marker():
    assert classify_links("Disputed: [[claim]] ^[ambiguous]") == [("claim", "ambiguous")]


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "concepts").mkdir()
    page = lambda name, body: (tmp_path / "concepts" / f"{name}.md").write_text(FM + body)
    page("a", "Stated plainly: [[b]].\n\n- Guess about [[c]] ^[inferred]\n- Dispute over [[d]] ^[ambiguous]\n")
    page("b", "Both ways: [[c]] ^[inferred]\n\nand again [[c]].\n")
    page("c", "x\n")
    page("d", "x\n")
    return tmp_path


def test_rows_per_edge_with_best_state(vault):
    rows = {(r["from"], r["to"]): r["state"] for r in link_provenance(vault)}
    assert rows[("a", "b")] == "extracted"
    assert rows[("a", "c")] == "inferred"
    assert rows[("a", "d")] == "ambiguous"
    assert rows[("b", "c")] == "extracted"  # stated plainly once, so it stands


def test_summarize_filters_by_state(vault):
    out = summarize(link_provenance(vault), "inferred")
    assert out["counts"] == {"extracted": 2, "inferred": 1, "ambiguous": 1}
    assert [(r["from"], r["to"]) for r in out["links"]] == [("a", "c")]


def test_cli_links_flag(vault):
    proc = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki", "graph-analyse", str(vault), "--links", "ambiguous"],
        capture_output=True, text=True,
    )
    data = json.loads(proc.stdout)
    assert [(r["from"], r["to"]) for r in data["links"]] == [("a", "d")]
