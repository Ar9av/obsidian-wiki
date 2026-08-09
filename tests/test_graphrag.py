"""Tests for the GraphRAG query index module."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from obsidian_wiki.graphrag import (
    build_index,
    classify_query,
    find_path,
    query,
    rank_candidates,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    return v


def _page(vault: Path, name: str, *, title: str = "", summary: str = "",
          tags: list[str] | None = None, links: list[str] | None = None,
          tier: str = "supporting", category: str = "concepts") -> Path:
    lines = ["---", f"title: {title or name}"]
    if summary:
        lines.append(f"summary: {summary}")
    if tags:
        lines.append(f"tags: [{', '.join(tags)}]")
    lines.append(f"tier: {tier}")
    lines.append(f"category: {category}")
    lines.append("---")
    lines.append(f"# {title or name}")
    for lnk in (links or []):
        lines.append(f"[[{lnk}]]")
    p = vault / f"{name}.md"
    p.write_text("\n".join(lines) + "\n")
    return p


@pytest.fixture
def simple_vault(vault):
    _page(vault, "transformer", title="Transformer Architecture",
          summary="Self-attention mechanism for sequence modelling.",
          tags=["deep-learning", "nlp"], tier="core", links=["attention", "embedding"])
    _page(vault, "attention", title="Attention Mechanism",
          summary="Computes weighted sums over value vectors.",
          tags=["deep-learning"], links=["transformer"])
    _page(vault, "embedding", title="Word Embedding",
          summary="Dense vector representation of tokens.",
          tags=["nlp"])
    _page(vault, "python", title="Python",
          summary="General-purpose programming language.",
          tags=["programming"])
    return vault


# ---------------------------------------------------------------------------
# build_index
# ---------------------------------------------------------------------------

class TestBuildIndex:
    def test_returns_slugs(self, simple_vault):
        idx = build_index(simple_vault)
        assert "transformer" in idx
        assert "attention" in idx

    def test_reads_title(self, simple_vault):
        idx = build_index(simple_vault)
        assert idx["transformer"]["title"] == "Transformer Architecture"

    def test_reads_summary(self, simple_vault):
        idx = build_index(simple_vault)
        assert "Self-attention" in idx["transformer"]["summary"]

    def test_reads_tags(self, simple_vault):
        idx = build_index(simple_vault)
        assert "deep-learning" in idx["transformer"]["tags"]

    def test_reads_tier(self, simple_vault):
        idx = build_index(simple_vault)
        assert idx["transformer"]["tier"] == "core"

    def test_out_links(self, simple_vault):
        idx = build_index(simple_vault)
        assert "attention" in idx["transformer"]["out_links"]

    def test_in_links_reverse(self, simple_vault):
        idx = build_index(simple_vault)
        assert "transformer" in idx["attention"]["in_links"]

    def test_empty_vault(self, vault):
        idx = build_index(vault)
        assert idx == {}

    def test_skips_raw_dir(self, vault):
        (vault / "_raw").mkdir()
        _page(vault / "_raw", "draft", title="Draft")
        idx = build_index(vault)
        assert "draft" not in idx

    def test_reads_folded_block_scalar_summary(self, vault):
        # Regression for #156: `summary: >-` puts the real text on the next
        # indented line(s), not on the `summary:` line itself.
        (vault / "folded.md").write_text(
            "---\n"
            "title: >-\n"
            "  Folded Title\n"
            "summary: >-\n"
            "  Some text that wraps\n"
            "  onto a second line.\n"
            "category: concepts\n"
            "---\n"
            "# Folded\n"
        )
        idx = build_index(vault)
        assert idx["folded"]["title"] == "Folded Title"
        assert idx["folded"]["summary"] == "Some text that wraps onto a second line."

    def test_reads_literal_block_scalar_summary(self, vault):
        (vault / "literal.md").write_text(
            "---\n"
            "title: Literal\n"
            "summary: |-\n"
            "  Literal block text.\n"
            "category: concepts\n"
            "---\n"
            "# Literal\n"
        )
        idx = build_index(vault)
        assert idx["literal"]["summary"] == "Literal block text."


# ---------------------------------------------------------------------------
# rank_candidates
# ---------------------------------------------------------------------------

class TestRankCandidates:
    def test_exact_title_match_scores_highest(self, simple_vault):
        idx = build_index(simple_vault)
        result = rank_candidates(idx, ["transformer"])
        assert result[0]["slug"] == "transformer"

    def test_tag_match_included(self, simple_vault):
        idx = build_index(simple_vault)
        result = rank_candidates(idx, ["nlp"])
        slugs = [r["slug"] for r in result]
        assert "transformer" in slugs or "embedding" in slugs

    def test_no_match_returns_empty(self, simple_vault):
        idx = build_index(simple_vault)
        result = rank_candidates(idx, ["zzznomatch"])
        assert result == []

    def test_core_tier_boosted(self, simple_vault):
        idx = build_index(simple_vault)
        result = rank_candidates(idx, ["deep-learning"])
        # transformer is tier:core; attention is tier:supporting — transformer should score higher
        transformer_score = next((r["score"] for r in result if r["slug"] == "transformer"), 0)
        attention_score = next((r["score"] for r in result if r["slug"] == "attention"), 0)
        assert transformer_score > attention_score

    def test_respects_top_n(self, simple_vault):
        idx = build_index(simple_vault)
        result = rank_candidates(idx, ["deep-learning"], top_n=1)
        assert len(result) <= 1


# ---------------------------------------------------------------------------
# find_path
# ---------------------------------------------------------------------------

class TestFindPath:
    def test_direct_link(self, simple_vault):
        idx = build_index(simple_vault)
        path = find_path(idx, "transformer", "attention")
        assert path is not None
        assert "transformer" in path
        assert "attention" in path

    def test_same_node(self, simple_vault):
        idx = build_index(simple_vault)
        path = find_path(idx, "transformer", "transformer")
        assert path == ["transformer"]

    def test_unknown_node_returns_none(self, simple_vault):
        idx = build_index(simple_vault)
        path = find_path(idx, "transformer", "zzznone")
        assert path is None

    def test_multi_hop(self, vault):
        _page(vault, "a", links=["b"])
        _page(vault, "b", links=["c"])
        _page(vault, "c", links=[])
        idx = build_index(vault)
        path = find_path(idx, "a", "c")
        assert path is not None
        assert len(path) == 3

    def test_no_path_returns_none(self, vault):
        _page(vault, "x", links=[])
        _page(vault, "y", links=[])
        idx = build_index(vault)
        path = find_path(idx, "x", "y")
        assert path is None


# ---------------------------------------------------------------------------
# classify_query
# ---------------------------------------------------------------------------

class TestClassifyQuery:
    def test_direct_query(self):
        qt, terms = classify_query("What is a transformer?")
        assert qt == "direct"
        assert any("transformer" in t.lower() for t in terms)

    def test_path_query(self):
        qt, terms = classify_query("How is transformer connected to embedding?")
        assert qt == "path"
        assert len(terms) == 2

    def test_gap_query(self):
        qt, _ = classify_query("What do I not know about reinforcement learning?")
        assert qt == "gap"

    def test_list_query(self):
        qt, _ = classify_query("List all pages about deep learning")
        assert qt == "list"

    def test_stop_words_filtered(self):
        _, terms = classify_query("What is the difference?")
        assert "the" not in terms
        assert "is" not in terms


# ---------------------------------------------------------------------------
# query (integration)
# ---------------------------------------------------------------------------

class TestQuery:
    def test_returns_required_keys(self, simple_vault):
        result = query(simple_vault, "What is a transformer?")
        assert set(result.keys()) >= {"answer_type", "candidates", "path",
                                       "god_nodes_relevant", "should_read", "index_only"}

    def test_finds_exact_match(self, simple_vault):
        result = query(simple_vault, "transformer architecture")
        pages = [c["page"] for c in result["candidates"]]
        assert any("transformer" in p for p in pages)

    def test_path_query_populated(self, simple_vault):
        result = query(simple_vault, "How is transformer connected to embedding?")
        assert result["answer_type"] == "path"

    def test_index_only_on_exact_with_summary(self, simple_vault):
        result = query(simple_vault, "Transformer Architecture")
        # Title exact match + summary → index_only should be True
        assert result["index_only"] is True

    def test_should_read_empty_when_index_only(self, simple_vault):
        result = query(simple_vault, "Transformer Architecture")
        if result["index_only"]:
            assert result["should_read"] == []

    def test_empty_vault(self, vault):
        result = query(vault, "anything")
        assert result["candidates"] == []
        assert result["index_only"] is True

    def test_json_serialisable(self, simple_vault):
        result = query(simple_vault, "deep learning")
        json.dumps(result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestGraphQueryCLI:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", *args],
            capture_output=True, text=True,
        )

    def test_outputs_json(self, simple_vault):
        proc = self._run("graph-query", str(simple_vault), "transformer")
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert "candidates" in data

    def test_pretty_flag(self, simple_vault):
        proc = self._run("graph-query", str(simple_vault), "transformer", "--pretty")
        assert proc.returncode == 0
        assert "\n  " in proc.stdout

    def test_missing_vault_exits_nonzero(self, tmp_path):
        proc = self._run("graph-query", str(tmp_path / "nope"), "anything")
        assert proc.returncode != 0
