"""Tests for vault graph analysis: community detection, god nodes, surprising connections."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from obsidian_wiki.graph_analysis import (
    analyse_vault,
    dead_ends,
    detect_communities_greedy,
    god_nodes,
    isolated,
    parse_vault_graph,
    surprising_connections,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic vault
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    return v


def _page(vault: Path, name: str, links: list[str], tags: list[str] | None = None) -> Path:
    """Write a minimal wiki page with wikilinks."""
    lines = ["---", f"title: {name}"]
    if tags:
        lines.append(f"tags: [{', '.join(tags)}]")
    lines += ["---", f"# {name}", ""]
    lines += [f"[[{lnk}]]" for lnk in links]
    p = vault / f"{name}.md"
    p.write_text("\n".join(lines) + "\n")
    return p


@pytest.fixture
def simple_vault(vault):
    """
    A → B → C
    A → C
    D (isolated)
    E → F (dead-end cluster)
    """
    _page(vault, "a", ["b", "c"], tags=["concepts"])
    _page(vault, "b", ["c"], tags=["concepts"])
    _page(vault, "c", [], tags=["references"])
    _page(vault, "d", [], tags=["entities"])
    _page(vault, "e", ["f"])
    _page(vault, "f", [])
    return vault


# ---------------------------------------------------------------------------
# parse_vault_graph
# ---------------------------------------------------------------------------

class TestParseVaultGraph:
    def test_reads_wikilinks(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        assert "b" in outgoing["a"]
        assert "c" in outgoing["a"]

    def test_all_pages_present_as_keys(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        assert set(outgoing.keys()) == {"a", "b", "c", "d", "e", "f"}

    def test_reads_tags(self, simple_vault):
        _, tags = parse_vault_graph(simple_vault)
        assert "concepts" in tags.get("a", [])

    def test_empty_vault(self, vault):
        outgoing, tags = parse_vault_graph(vault)
        assert outgoing == {}

    def test_self_links_ignored(self, vault):
        _page(vault, "selfref", ["selfref"])
        outgoing, _ = parse_vault_graph(vault)
        assert "selfref" not in outgoing.get("selfref", [])

    def test_links_to_nonexistent_pages_excluded(self, vault):
        _page(vault, "orphan", ["doesnotexist"])
        outgoing, _ = parse_vault_graph(vault)
        assert outgoing["orphan"] == []


# ---------------------------------------------------------------------------
# god_nodes
# ---------------------------------------------------------------------------

class TestGodNodes:
    def test_c_is_top_hub(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        result = god_nodes(outgoing, top_n=3)
        # c has 2 in-links (from a and b), so should be in top 3
        top_pages = {r["page"] for r in result}
        assert "c" in top_pages

    def test_degree_sum(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        result = god_nodes(outgoing)
        for node in result:
            assert node["degree"] == node["in_degree"] + node["out_degree"]

    def test_respects_top_n(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        result = god_nodes(outgoing, top_n=2)
        assert len(result) <= 2


# ---------------------------------------------------------------------------
# dead_ends / isolated
# ---------------------------------------------------------------------------

class TestDeadEndsIsolated:
    def test_dead_ends(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        de = dead_ends(outgoing)
        assert "c" in de
        assert "f" in de
        assert "a" not in de

    def test_isolated(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        iso = isolated(outgoing)
        assert "d" in iso
        assert "a" not in iso
        assert "c" not in iso  # c has incoming links so not isolated


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------

class TestCommunityDetection:
    def test_returns_list_of_sets(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        comms = detect_communities_greedy(outgoing)
        assert isinstance(comms, list)
        for c in comms:
            assert isinstance(c, set)

    def test_all_nodes_assigned(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        comms = detect_communities_greedy(outgoing)
        all_nodes = set(outgoing.keys())
        assigned = set()
        for c in comms:
            assigned |= c
        assert assigned == all_nodes

    def test_no_overlap(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        comms = detect_communities_greedy(outgoing)
        seen = set()
        for c in comms:
            assert c.isdisjoint(seen), "Node appears in two communities"
            seen |= c

    def test_connected_cluster_grouped(self, vault):
        # a-b-c tightly connected, x-y-z separate — should land in different communities
        _page(vault, "a", ["b", "c"])
        _page(vault, "b", ["a", "c"])
        _page(vault, "c", ["a", "b"])
        _page(vault, "x", ["y", "z"])
        _page(vault, "y", ["x", "z"])
        _page(vault, "z", ["x", "y"])
        outgoing, _ = parse_vault_graph(vault)
        comms = detect_communities_greedy(outgoing)
        # At least 2 communities
        assert len(comms) >= 2

    def test_empty_graph(self, vault):
        outgoing, _ = parse_vault_graph(vault)
        comms = detect_communities_greedy(outgoing)
        assert comms == []


# ---------------------------------------------------------------------------
# Surprising connections
# ---------------------------------------------------------------------------

class TestSurprisingConnections:
    def test_cross_community_edge_found(self, vault):
        # Build two tight clusters with one bridge
        _page(vault, "a", ["b", "c", "x"])
        _page(vault, "b", ["a", "c"])
        _page(vault, "c", ["a", "b"])
        _page(vault, "x", ["y", "z"])
        _page(vault, "y", ["x", "z"])
        _page(vault, "z", ["x", "y"])
        outgoing, _ = parse_vault_graph(vault)
        comms = detect_communities_greedy(outgoing)
        sc = surprising_connections(outgoing, comms)
        sources = {s["source"] for s in sc}
        targets = {s["target"] for s in sc}
        assert sources | targets  # at least one cross-community edge found

    def test_no_intra_community_edges(self, vault):
        _page(vault, "a", ["b"])
        _page(vault, "b", ["a"])
        outgoing, _ = parse_vault_graph(vault)
        comms = [{"a", "b"}]  # one community
        sc = surprising_connections(outgoing, comms)
        assert sc == []

    def test_scores_positive(self, vault):
        _page(vault, "a", ["b", "x"])
        _page(vault, "b", ["a"])
        _page(vault, "x", ["y"])
        _page(vault, "y", ["x"])
        outgoing, _ = parse_vault_graph(vault)
        comms = detect_communities_greedy(outgoing)
        sc = surprising_connections(outgoing, comms)
        for item in sc:
            assert item["score"] > 0


# ---------------------------------------------------------------------------
# analyse_vault (integration)
# ---------------------------------------------------------------------------

class TestAnalyseVault:
    def test_returns_all_keys(self, simple_vault):
        result = analyse_vault(simple_vault)
        assert set(result.keys()) == {
            "god_nodes", "bridges", "communities", "surprising_connections",
            "suggested_questions", "dead_ends", "isolated", "stats",
        }

    def test_stats_correct(self, simple_vault):
        result = analyse_vault(simple_vault)
        assert result["stats"]["pages"] == 6
        assert result["stats"]["edges"] > 0

    def test_empty_vault(self, vault):
        result = analyse_vault(vault)
        assert result["stats"]["pages"] == 0

    def test_json_serialisable(self, simple_vault):
        result = analyse_vault(simple_vault)
        json.dumps(result)  # must not raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestGraphAnalyseCLI:
    def test_outputs_json(self, simple_vault):
        proc = subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", "graph-analyse", str(simple_vault)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert "god_nodes" in data

    def test_pretty_flag(self, simple_vault):
        proc = subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", "graph-analyse", str(simple_vault), "--pretty"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0
        assert "\n  " in proc.stdout

    def test_top_flag(self, simple_vault):
        proc = subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", "graph-analyse", str(simple_vault), "--top", "3"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert len(data["god_nodes"]) <= 3

    def test_missing_vault_exits_nonzero(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", "graph-analyse", str(tmp_path / "nope")],
            capture_output=True, text=True,
        )
        assert proc.returncode != 0


# ---------------------------------------------------------------------------
# graphify-derived algorithms: betweenness, cohesion, path, neighbourhood,
# diff, suggested questions
# ---------------------------------------------------------------------------

from obsidian_wiki.graph_analysis import (  # noqa: E402
    betweenness_centrality,
    bridge_pages,
    cohesion_score,
    graph_diff,
    load_snapshot,
    neighborhood,
    shortest_path,
    snapshot,
    suggest_questions,
)


@pytest.fixture
def barbell_vault(vault):
    """Two triangles joined through a single bridge page `m`.
    a-b-c clique  —  m  —  x-y-z clique
    """
    _page(vault, "a", ["b", "c", "m"], tags=["left"])
    _page(vault, "b", ["a", "c"], tags=["left"])
    _page(vault, "c", ["a", "b"], tags=["left"])
    _page(vault, "m", ["a", "x"], tags=["mid"])
    _page(vault, "x", ["m", "y", "z"], tags=["right"])
    _page(vault, "y", ["x", "z"], tags=["right"])
    _page(vault, "z", ["x", "y"], tags=["right"])
    return vault


class TestBetweenness:
    def test_bridge_has_highest_betweenness(self, barbell_vault):
        outgoing, _ = parse_vault_graph(barbell_vault)
        bc = betweenness_centrality(outgoing)
        assert max(bc, key=bc.get) == "m"
        # leaf-of-clique nodes lie on no shortest paths
        assert bc["b"] == 0.0 and bc["y"] == 0.0

    def test_normalised_range(self, barbell_vault):
        outgoing, _ = parse_vault_graph(barbell_vault)
        for v in betweenness_centrality(outgoing).values():
            assert 0.0 <= v <= 1.0

    def test_matches_star_exact_value(self, vault):
        # Star: hub h with 4 leaves — hub betweenness = 1.0 normalised
        _page(vault, "h", ["p", "q", "r", "s"])
        for leaf in "pqrs":
            _page(vault, leaf, [])
        outgoing, _ = parse_vault_graph(vault)
        bc = betweenness_centrality(outgoing)
        assert bc["h"] == pytest.approx(1.0)

    def test_bridge_pages_reports_connected_communities(self, barbell_vault):
        outgoing, _ = parse_vault_graph(barbell_vault)
        comms = detect_communities_greedy(outgoing)
        bridges = bridge_pages(outgoing, comms, top_n=3)
        assert bridges[0]["page"] == "m"
        assert bridges[0]["betweenness"] > 0
        assert "connects" in bridges[0]

    def test_empty(self):
        assert betweenness_centrality({}) == {}
        assert bridge_pages({}, [], 5) == []


class TestCohesion:
    def test_clique_is_one(self, barbell_vault):
        outgoing, _ = parse_vault_graph(barbell_vault)
        assert cohesion_score(outgoing, {"a", "b", "c"}) == 1.0

    def test_no_internal_links_is_zero(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        assert cohesion_score(outgoing, {"d", "f", "c"}) == 0.0

    def test_singleton_is_one(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        assert cohesion_score(outgoing, {"d"}) == 1.0

    def test_analyse_includes_cohesion(self, barbell_vault):
        result = analyse_vault(barbell_vault)
        for c in result["communities"]:
            assert 0.0 <= c["cohesion"] <= 1.0


class TestShortestPath:
    def test_finds_path_across_bridge(self, barbell_vault):
        outgoing, _ = parse_vault_graph(barbell_vault)
        path = shortest_path(outgoing, "b", "y")
        assert path[0] == "b" and path[-1] == "y"
        assert "m" in path
        assert len(path) == 5  # b-a-m-x-y

    def test_directed_respects_link_direction(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        assert shortest_path(outgoing, "a", "c", directed=True) == ["a", "c"]
        assert shortest_path(outgoing, "c", "a", directed=True) is None
        assert shortest_path(outgoing, "c", "a") == ["c", "a"]

    def test_unreachable_and_unknown(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        assert shortest_path(outgoing, "a", "d") is None
        assert shortest_path(outgoing, "a", "nope") is None
        assert shortest_path(outgoing, "a", "a") == ["a"]

    def test_slug_normalisation(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        assert shortest_path(outgoing, "A", "B") == ["a", "b"]


class TestNeighborhood:
    def test_depth_layers(self, barbell_vault):
        outgoing, _ = parse_vault_graph(barbell_vault)
        hits = neighborhood(outgoing, "m", depth=1)
        assert {h["page"] for h in hits} == {"a", "x"}
        hits2 = neighborhood(outgoing, "m", depth=2)
        assert {h["page"] for h in hits2} == {"a", "x", "b", "c", "y", "z"}
        assert all(h["depth"] in (1, 2) for h in hits2)

    def test_incoming_blast_radius(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        # who would break if `c` were renamed? a and b link to it
        hits = neighborhood(outgoing, "c", depth=1, direction="in")
        assert {h["page"] for h in hits} == {"a", "b"}
        assert neighborhood(outgoing, "c", depth=1, direction="out") == []

    def test_unknown_seed(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        assert neighborhood(outgoing, "nope") == []


class TestGraphDiff:
    def test_added_removed(self):
        old = {"nodes": ["a", "b", "c"], "edges": [["a", "b"]]}
        new = {"nodes": ["a", "b", "d"], "edges": [["a", "b"], ["a", "d"], ["d", "b"]]}
        d = graph_diff(old, new)
        assert d["added_pages"] == ["d"]
        assert d["removed_pages"] == ["c"]
        assert ["a", "d"] in d["added_edges"]
        assert d["removed_edges"] == []
        assert d["summary"] == {"pages": 0, "edges": 2}

    def test_newly_connected_and_lost_incoming(self):
        old = {"nodes": ["a", "b", "c"], "edges": [["a", "b"]]}
        new = {"nodes": ["a", "b", "c"], "edges": [["a", "c"]]}
        d = graph_diff(old, new)
        assert d["newly_connected"] == ["c"]
        assert d["lost_incoming"] == ["b"]

    def test_snapshot_roundtrip_via_insights_comment(self, simple_vault, tmp_path):
        outgoing, _ = parse_vault_graph(simple_vault)
        snap = snapshot(outgoing)
        insights = tmp_path / "_insights.md"
        insights.write_text("# Insights\n\nstuff\n\n<!-- GRAPH_SNAPSHOT: " + json.dumps(snap) + " -->\n")
        loaded = load_snapshot(insights)
        assert loaded == snap
        assert graph_diff(loaded, snap)["summary"] == {"pages": 0, "edges": 0}

    def test_load_snapshot_missing(self, tmp_path):
        p = tmp_path / "x.md"
        p.write_text("no snapshot here")
        assert load_snapshot(p) is None
        assert load_snapshot(tmp_path / "absent.md") is None

    def test_analyse_with_previous(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        prev = snapshot(outgoing)
        _page(simple_vault, "g", ["a"])
        result = analyse_vault(simple_vault, previous_snapshot=prev, include_snapshot=True)
        assert result["diff"]["added_pages"] == ["g"]
        assert "snapshot" in result


class TestSuggestQuestions:
    def test_bridge_question_first(self, barbell_vault):
        outgoing, _ = parse_vault_graph(barbell_vault)
        comms = detect_communities_greedy(outgoing)
        labels = {i: f"c{i}" for i in range(len(comms))}
        bridges = bridge_pages(outgoing, comms)
        qs = suggest_questions(outgoing, comms, labels, bridges)
        assert qs
        assert qs[0]["type"] == "bridge_node" and "`m`" in qs[0]["question"]

    def test_isolated_question(self, simple_vault):
        outgoing, _ = parse_vault_graph(simple_vault)
        qs = suggest_questions(outgoing, [], {}, [])
        assert any(q["type"] == "isolated_nodes" for q in qs)

    def test_no_signal(self):
        qs = suggest_questions({"a": ["b"], "b": ["a"]}, [{"a", "b"}], {0: "x"}, [])
        assert qs == [] or qs[0]["type"] in ("no_signal", "isolated_nodes")

    def test_included_in_analyse(self, barbell_vault):
        result = analyse_vault(barbell_vault)
        assert "suggested_questions" in result and "bridges" in result
        assert result["stats"]["density"] > 0


class TestSurprisingDedup:
    def test_note_and_pair_dedup(self, vault):
        # Hub h in community 0 links to 3 different pages of community 1;
        # community 1 also has one link to community 2. Pair (1,2) must not
        # be pushed out by the three (0,1) edges.
        _page(vault, "h", ["p", "q", "r"])
        _page(vault, "p", ["q"]); _page(vault, "q", ["p"]); _page(vault, "r", ["p", "s"])
        _page(vault, "s", ["t"]); _page(vault, "t", ["s"])
        outgoing, _ = parse_vault_graph(vault)
        comms = [{"h"}, {"p", "q", "r"}, {"s", "t"}]
        sc = surprising_connections(outgoing, comms, top_n=2)
        assert all("note" in x for x in sc)
        pairs = {tuple(sorted(x["note"].replace("bridges community ", "").split(" -> community "))) for x in sc}
        assert pairs == {("0", "1"), ("1", "2")}


class TestGraphAnalyseCLIQueryModes:
    def _run(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", "graph-analyse", *argv],
            capture_output=True, text=True,
        )

    def test_path(self, barbell_vault):
        proc = self._run(str(barbell_vault), "--path", "b", "y")
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert data["hops"] == 4 and "m" in data["path"]

    def test_around(self, barbell_vault):
        proc = self._run(str(barbell_vault), "--around", "m", "--depth", "1")
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert {p["page"] for p in data["pages"]} == {"a", "x"}

    def test_diff_against_and_snapshot(self, simple_vault, tmp_path):
        proc = self._run(str(simple_vault), "--snapshot")
        snap = json.loads(proc.stdout)["snapshot"]
        prev = tmp_path / "_insights.md"
        prev.write_text("<!-- GRAPH_SNAPSHOT: " + json.dumps(snap) + " -->")
        _page(simple_vault, "new", ["a"])
        proc = self._run(str(simple_vault), "--diff-against", str(prev))
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["diff"]["added_pages"] == ["new"]


class TestUniqueCommunityLabels:
    def test_labels_disambiguated(self, vault):
        # two disconnected clusters both dominated by tag `x`
        _page(vault, "a", ["b"], tags=["x", "left"]); _page(vault, "b", ["a"], tags=["x"])
        _page(vault, "c", ["d"], tags=["x", "right"]); _page(vault, "d", ["c"], tags=["x"])
        result = analyse_vault(vault)
        labels = [c["label"] for c in result["communities"]]
        assert len(labels) == len(set(labels))
        assert "x" in labels and any(l.startswith("x/") for l in labels)


# ---------------------------------------------------------------------------
# Shared page selection + betweenness cache
# ---------------------------------------------------------------------------

from obsidian_wiki.graph_analysis import (  # noqa: E402
    CACHE_FILENAME,
    SKIP_ROOT_FILES,
    betweenness_cached,
    graph_fingerprint,
    is_wiki_page,
    iter_pages,
)


class TestPageSelection:
    def test_root_bookkeeping_excluded(self, vault):
        _page(vault, "a", ["b"]); _page(vault, "b", [])
        for name in SKIP_ROOT_FILES:
            (vault / f"{name}.md").write_text("---\ntitle: x\n---\n[[a]]\n")
        out, _ = parse_vault_graph(vault)
        assert set(out) == {"a", "b"}

    def test_nested_index_is_a_real_page(self, vault):
        """Only ROOT index/log/hot are bookkeeping — concepts/index.md is content."""
        (vault / "concepts").mkdir()
        (vault / "concepts" / "index.md").write_text("---\ntitle: Concept Index\n---\n[[a]]\n")
        _page(vault, "a", [])
        out, _ = parse_vault_graph(vault)
        assert "index" in out
        assert is_wiki_page(vault / "concepts" / "index.md", vault)
        assert not is_wiki_page(vault / "index.md", vault)

    def test_skip_dirs_excluded(self, vault):
        for d in ("_raw", "_meta", "_readouts", "_staging"):
            (vault / d).mkdir()
            (vault / d / "note.md").write_text("---\ntitle: x\n---\n")
        _page(vault, "a", [])
        assert [p.stem for p in iter_pages(vault)] == ["a"]

    def test_iter_pages_is_sorted(self, vault):
        for n in ("zebra", "alpha", "middle"):
            _page(vault, n, [])
        assert [p.stem for p in iter_pages(vault)] == ["alpha", "middle", "zebra"]

    def test_path_outside_vault_is_not_a_page(self, vault, tmp_path):
        assert not is_wiki_page(tmp_path / "elsewhere.md", vault)


class TestGraphFingerprint:
    def test_stable_across_calls(self, simple_vault):
        out, _ = parse_vault_graph(simple_vault)
        assert graph_fingerprint(out) == graph_fingerprint(out)

    def test_changes_when_an_edge_changes(self, simple_vault):
        out, _ = parse_vault_graph(simple_vault)
        before = graph_fingerprint(out)
        _page(simple_vault, "e", ["f", "a"])          # add an edge
        out2, _ = parse_vault_graph(simple_vault)
        assert graph_fingerprint(out2) != before

    def test_insensitive_to_key_order(self, simple_vault):
        out, _ = parse_vault_graph(simple_vault)
        shuffled = {k: out[k] for k in reversed(list(out))}
        assert graph_fingerprint(shuffled) == graph_fingerprint(out)


class TestBetweennessCache:
    def test_matches_uncached(self, barbell_vault):
        out, _ = parse_vault_graph(barbell_vault)
        exact = betweenness_centrality(out)
        cached = betweenness_cached(out, barbell_vault)
        assert all(abs(exact[k] - cached[k]) < 1e-12 for k in exact)

    def test_no_cache_file_for_small_vault(self, barbell_vault):
        """Tiny graphs recompute in microseconds — don't litter the vault."""
        out, _ = parse_vault_graph(barbell_vault)
        betweenness_cached(out, barbell_vault)
        assert not (barbell_vault / CACHE_FILENAME).exists()

    def test_none_vault_still_works(self, barbell_vault):
        out, _ = parse_vault_graph(barbell_vault)
        assert betweenness_cached(out, None) == betweenness_centrality(out)

    def test_corrupt_cache_fails_open(self, barbell_vault):
        (barbell_vault / CACHE_FILENAME).write_text("{ not json")
        out, _ = parse_vault_graph(barbell_vault)
        assert betweenness_cached(out, barbell_vault) == betweenness_centrality(out)

    def test_hit_is_used_when_present(self, barbell_vault):
        """A planted cache entry is returned verbatim — proves the key matches."""
        out, _ = parse_vault_graph(barbell_vault)
        key = f"{graph_fingerprint(out)}:1"
        planted = {n: 0.5 for n in out}
        (barbell_vault / CACHE_FILENAME).write_text(
            json.dumps({"version": 1, "betweenness": {key: planted}})
        )
        assert betweenness_cached(out, barbell_vault) == planted

    def test_stale_key_is_ignored(self, barbell_vault):
        out, _ = parse_vault_graph(barbell_vault)
        (barbell_vault / CACHE_FILENAME).write_text(
            json.dumps({"version": 1, "betweenness": {"someotherkey:1": {n: 9.0 for n in out}}})
        )
        assert betweenness_cached(out, barbell_vault) == betweenness_centrality(out)

    def test_unwritable_vault_does_not_raise(self, barbell_vault, tmp_path):
        out, _ = parse_vault_graph(barbell_vault)
        assert betweenness_cached(out, tmp_path / "does" / "not" / "exist")


class TestCommunityQuality:
    def test_barbell_splits_into_two(self, barbell_vault):
        """A sequential label-propagation sweep collapses this into one group."""
        out, _ = parse_vault_graph(barbell_vault)
        comms = detect_communities_greedy(out)
        assert len(comms) == 2
        assert {"x", "y", "z"} in [set(c) for c in comms]

    def test_deterministic_across_runs(self, barbell_vault):
        out, _ = parse_vault_graph(barbell_vault)
        sigs = {
            json.dumps(sorted(sorted(c) for c in detect_communities_greedy(out)))
            for _ in range(10)
        }
        assert len(sigs) == 1


class TestGitignoreBackfill:
    def test_new_gitignore_ignores_cache(self):
        from obsidian_wiki.sync import GITIGNORE_CONTENT
        assert ".graph-cache.json" in GITIGNORE_CONTENT

    def test_existing_gitignore_is_never_edited_only_advised(self, tmp_path, monkeypatch):
        """The user's .gitignore is theirs — advise, don't mutate."""
        import obsidian_wiki.sync as sync
        v = tmp_path / "vault"; v.mkdir()
        (v / ".gitignore").write_text(".env\n_raw/\n")
        monkeypatch.setattr(sync, "_git", lambda *a, **k: type("P", (), {"returncode": 0, "stderr": "", "stdout": ""})())
        msgs = sync.configure_sync(v, "git@example.com:me/vault.git")
        assert (v / ".gitignore").read_text() == ".env\n_raw/\n"   # byte-identical
        assert any(".graph-cache.json" in m for m in msgs)

    def test_no_advice_when_already_ignored(self, tmp_path, monkeypatch):
        import obsidian_wiki.sync as sync
        v = tmp_path / "vault"; v.mkdir()
        (v / ".gitignore").write_text(".graph-cache.json\n")
        monkeypatch.setattr(sync, "_git", lambda *a, **k: type("P", (), {"returncode": 0, "stderr": "", "stdout": ""})())
        assert not any(".graph-cache.json" in m for m in sync.configure_sync(v, "git@example.com:me/vault.git"))
