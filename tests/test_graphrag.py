"""Tests for the GraphRAG query index module."""

from __future__ import annotations

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

    def test_gap_query_strips_trailing_punctuation(self):
        # A trailing "?" used to survive on the gap path, leaving a term like
        # "mise?" that can never match a title, tag or summary.
        _, terms = classify_query("What do I know about mise?")
        assert terms == ["mise"]

    def test_list_query_strips_trailing_punctuation(self):
        _, terms = classify_query("List all pages about transformers?")
        assert "transformers" in terms
        assert not any(t.endswith("?") for t in terms)

    def test_gap_and_direct_agree_on_punctuation(self):
        # Both paths must yield the same term for the same subject.
        _, gap_terms = classify_query("What do I know about transformers?")
        _, direct_terms = classify_query("What is transformers?")
        assert "transformers" in gap_terms
        assert "transformers" in direct_terms


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

    def test_non_english_question_about_absent_topic_returns_no_candidates(self, simple_vault):
        # Regression for #191: short German function words ("ich", "über")
        # used to substring-match inside unrelated title words ("Architektur"),
        # scoring a page unrelated to the actual topic and flagging it
        # index_only — telling the agent it can answer without reading a page.
        result = query(simple_vault, "Was weiß ich über Kubernetes?")
        assert result["candidates"] == []
        assert result["index_only"] is False

    def test_mid_word_substring_does_not_match_title(self, simple_vault):
        idx = build_index(simple_vault)
        # "bed" sits mid-word inside "embedding" (em-BED-ding), not at a word
        # boundary. A bare substring check used to score this a title hit.
        result = rank_candidates(idx, ["bed"])
        assert result == []


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


# ---------------------------------------------------------------------------
# Unified graph layer — bookkeeping files must not pollute the query graph
# ---------------------------------------------------------------------------

class TestBookkeepingExcluded:
    def test_index_log_hot_not_indexed(self, simple_vault):
        for name in ("index", "log", "hot", "_insights"):
            (simple_vault / f"{name}.md").write_text(
                "---\ntitle: %s\n---\n" % name
                + "\n".join(f"[[{p}]]" for p in ("transformer", "attention", "embedding", "python"))
            )
        idx = build_index(simple_vault)
        assert {"index", "log", "hot", "_insights"}.isdisjoint(idx)

    def test_path_does_not_route_through_index(self, simple_vault):
        """index.md links to everything; a path through it is meaningless."""
        (simple_vault / "index.md").write_text(
            "---\ntitle: Index\n---\n[[python]]\n[[embedding]]\n"
        )
        idx = build_index(simple_vault)
        path = find_path(idx, "python", "embedding")
        # python and embedding are genuinely disconnected without the index hub
        assert path is None or "index" not in path

    def test_real_path_still_found(self, simple_vault):
        idx = build_index(simple_vault)
        assert find_path(idx, "attention", "embedding") == ["attention", "transformer", "embedding"]

    def test_max_depth_respected(self, simple_vault):
        idx = build_index(simple_vault)
        assert find_path(idx, "attention", "embedding", max_depth=1) is None


# ---------------------------------------------------------------------------
# Structural intents
# ---------------------------------------------------------------------------

class TestStructuralClassification:
    @pytest.mark.parametrize("q,expected", [
        ("what breaks if I delete transformer", "impact"),
        ("what depends on transformer", "impact"),
        ("what links to attention", "impact"),
        ("blast radius of transformer", "impact"),
        ("which pages bridge my clusters", "bridges"),
        ("what would fragment my vault", "bridges"),
        ("what's central in my vault", "hubs"),
        ("show me the top hubs", "hubs"),
        ("what are my main topics", "hubs"),
        ("what clusters do I have", "clusters"),
        ("how is my wiki organised", "clusters"),
        ("show me surprising connections", "surprising"),
        ("any unexpected links?", "surprising"),
    ])
    def test_intent_detected(self, q, expected):
        assert classify_query(q)[0] == expected

    @pytest.mark.parametrize("q,expected", [
        ("how is transformer connected to embedding", "path"),
        ("what connects transformer and embedding", "path"),
        ("list all pages about nlp", "list"),
        ("what do I know about attention", "gap"),      # pre-existing gap pattern
        ("attention mechanism", "direct"),
    ])
    def test_existing_intents_unchanged(self, q, expected):
        assert classify_query(q)[0] == expected


class TestStructuralAnswers:
    def test_impact_lists_dependents(self, simple_vault):
        r = query(simple_vault, "what breaks if I delete transformer")
        g = r["graph"]
        assert r["answer_type"] == "impact" and r["index_only"] is True
        assert g["seed"] == "transformer"
        assert "attention" in g["direct_dependents"]

    def test_impact_unresolvable_falls_back(self, simple_vault):
        r = query(simple_vault, "what breaks if I delete zzz-nonexistent-qqq")
        assert r["answer_type"] == "direct"
        assert r["graph"] is None

    def test_hubs_ranked_by_degree(self, simple_vault):
        g = query(simple_vault, "what's central in my vault")["graph"]
        assert g["hubs"][0]["page"] == "transformer"
        assert "title" in g["hubs"][0]

    def test_bridges_have_betweenness(self, simple_vault):
        g = query(simple_vault, "which pages bridge my clusters")["graph"]
        assert all("betweenness" in b for b in g["bridges"])

    def test_clusters_have_cohesion(self, simple_vault):
        g = query(simple_vault, "what clusters do I have")["graph"]
        assert g["clusters"]
        for c in g["clusters"]:
            assert 0.0 <= c["cohesion"] <= 1.0
            assert isinstance(c["fragmented"], bool)

    def test_surprising_returns_list(self, simple_vault):
        g = query(simple_vault, "show me surprising connections")["graph"]
        assert isinstance(g["connections"], list)

    def test_non_structural_query_has_no_graph_payload(self, simple_vault):
        assert query(simple_vault, "attention mechanism")["graph"] is None
        assert query(simple_vault, "what do I know about attention")["graph"] is None

    def test_structural_queries_need_no_page_reads(self, simple_vault):
        for q in ("what's central in my vault", "what clusters do I have",
                  "which pages bridge my clusters", "show me surprising connections"):
            r = query(simple_vault, q)
            assert r["index_only"] is True, q
            assert r["should_read"] == [], q
