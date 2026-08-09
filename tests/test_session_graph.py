from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from obsidian_wiki import session_graph as sg

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)

TELEMETRY = [
    "add telemetry batching to the warden runtime with a redacted sink",
    "the telemetry sink drops spans under load, add warden batching retries",
    "warden telemetry chain signing broke, redacted spans never reach the sink",
]
SPRITES = [
    "slice the generated sprite sheet into aligned animation frames",
    "the sprite sheet flood fill leaves halos around each animation frame",
    "generate a sprite sheet and slice it into frames for the walk animation",
]


def _turn(text: str, sid: str, cwd: str, ts: str) -> str:
    return json.dumps({
        "type": "user", "message": {"role": "user", "content": text},
        "timestamp": ts, "cwd": cwd, "gitBranch": "main", "sessionId": sid,
    })


@pytest.fixture
def cache(tmp_path):
    """A synthetic cache with two clean topics, a thin node, and a bookmark."""
    claude = tmp_path / ".claude"
    for topic, texts, cwd in (("tel", TELEMETRY, "/w/warden"), ("spr", SPRITES, "/w/game")):
        project = claude / "projects" / cwd.replace("/", "-")
        project.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(texts):
            sid = f"{topic}{i}"
            ts = f"2026-07-{10 + i:02d}T10:00:00.000Z"
            lines = [_turn(text, sid, cwd, ts),
                     json.dumps({"type": "ai-title", "aiTitle": text[:40], "sessionId": sid})]
            (project / f"{sid}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    (claude / "history.jsonl").write_text("\n".join([
        json.dumps({"display": "warden telemetry sink batching retries",
                    "timestamp": 1783000000000, "project": "/w/warden", "sessionId": "ghost"}),
    ]) + "\n", encoding="utf-8")

    bookmarks = tmp_path / "bookmarks.json"
    bookmarks.write_text(json.dumps([
        {"id": "bm1", "tool": "claude-code", "sessionId": "tel0", "title": "Telemetry batching",
         "tags": ["observability"], "note": "", "createdAt": "2026-07-10T00:00:00-0700"},
    ]), encoding="utf-8")
    return claude, bookmarks


@pytest.fixture
def built(cache, tmp_path):
    claude, bookmarks = cache
    out = tmp_path / "brain"
    result = sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW)
    return out, result


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------

def test_decay_halves_every_half_life():
    older = (NOW - timedelta(days=90)).isoformat()
    assert sg.decay(NOW.isoformat(), NOW, 90) == pytest.approx(1.0)
    assert sg.decay(older, NOW, 90) == pytest.approx(0.5, abs=1e-6)


def test_decay_is_bounded_and_survives_bad_input():
    assert sg.decay(None, NOW, 90) == 0.0
    assert sg.decay("not-a-date", NOW, 90) == 0.0
    future = (NOW + timedelta(days=5)).isoformat()
    assert 0.0 <= sg.decay(future, NOW, 90) <= 1.0


def test_ninety_day_half_life_keeps_the_archive_reachable():
    """The reason the default is 90d and not 30d: a six-month-old session must
    still carry usable weight, or the tool cannot answer questions about the past."""
    six_months = (NOW - timedelta(days=180)).isoformat()
    assert sg.decay(six_months, NOW, 90) > 0.2
    assert sg.decay(six_months, NOW, 30) < 0.02


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def test_build_separates_the_two_topics(built):
    out, result = built
    graph, clusters = sg.load_graph(out)
    assignment = {n["id"]: n["cluster"] for n in graph["nodes"]}

    tel = {assignment[s] for s in ("tel0", "tel1", "tel2")}
    spr = {assignment[s] for s in ("spr0", "spr1", "spr2")}
    assert len(tel) == 1 and len(spr) == 1, "each topic should land in one cluster"
    assert tel != spr, "the two topics must not merge"
    assert result["stats"]["clusters"] >= 2


def test_thin_node_is_present_but_unloadable(built):
    out, _ = built
    graph, _ = sg.load_graph(out)
    ghost = next(n for n in graph["nodes"] if n["id"] == "ghost")
    assert ghost["tier"] == "thin"
    assert ghost["transcript"] is None
    assert graph["stats"]["thin"] == 1


def test_bookmark_is_carried_onto_the_node(built):
    out, _ = built
    graph, _ = sg.load_graph(out)
    node = next(n for n in graph["nodes"] if n["id"] == "tel0")
    assert node["bookmark"]["tags"] == ["observability"]


def test_all_artifacts_are_written(built):
    out, _ = built
    for name in ("graph.json", "clusters.json", "graph.html", "docs.jsonl",
                 "idf.json", "state.json"):
        assert (out / name).is_file(), f"missing {name}"


def test_html_is_self_contained_and_substituted(built):
    out, _ = built
    html = (out / "graph.html").read_text(encoding="utf-8")
    assert "vis-network" in html
    assert "/* NODES_JSON */" not in html, "placeholder was not substituted"
    assert "claude-session-load" in html, "the load handoff should be offered in the UI"
    assert '"tel0"' in html


def test_html_paints_a_frame_after_physics_is_disabled(built):
    """Regression: turning physics off halts vis.js's render loop before it
    paints, so the canvas stays blank while holding a perfectly good layout.
    Only an explicit redraw after the setOptions call produces a visible graph.
    """
    html = (built[0] / "graph.html").read_text(encoding="utf-8")
    # Anchor on our own handler: the inlined vis-network library mentions the
    # same event name, so a plain split lands inside minified library code.
    body = html.split("network.once('stabilizationIterationsDone'", 1)[1][:600]
    assert "physics: { enabled: false }" in body
    assert "network.redraw()" in body, "physics-off without a redraw renders nothing"
    assert body.index("enabled: false") < body.index("network.redraw()")


def test_loading_overlay_survives_visjs_container_takeover(built):
    """vis.js replaces its container's innerHTML on init, so an overlay nested
    inside #graph is silently deleted and can never be hidden again."""
    html = (built[0] / "graph.html").read_text(encoding="utf-8")
    graph_div = html[html.index('<div id="graph"'):]
    assert graph_div.startswith('<div id="graph"></div>'), \
        "#graph must be empty; vis.js wipes anything inside it"
    assert '<div id="loading"' in html


def test_graph_container_cannot_grow_unbounded(built):
    """Regression: the graph pane ran away to 4350px tall inside a 1000px page.

    A flex item defaults to min-height:auto so it cannot shrink below its
    content; vis.js sizes its canvas from the container and the container then
    grows to fit the canvas, feeding back until the graph renders far below the
    viewport. The page looked completely empty. min-height:0 breaks the loop.
    """
    html = (built[0] / "graph.html").read_text(encoding="utf-8")
    css = html[html.index("<style>"):html.index("</style>")]
    for selector in ("#graph {", "#wrap {"):
        rule = css[css.index(selector):]
        rule = rule[:rule.index("}")]
        assert "min-height: 0" in rule, f"{selector} may grow unbounded"
    assert "html, body { height: 100%; overflow: hidden; }" in css


def test_html_reports_a_missing_library_instead_of_rendering_empty(built):
    """A blank canvas is indistinguishable from "you have no sessions". If the
    graph library is unavailable the page must say so."""
    html = (built[0] / "graph.html").read_text(encoding="utf-8")
    assert "typeof vis === 'undefined'" in html
    assert "failed to load" in html


def test_html_disables_the_layout_prepass_that_gives_up_on_large_graphs(built):
    """vis.js's improvedLayout silently bails above ~150 nodes, leaving a blank
    canvas and only an INFO-level console note."""
    html = (built[0] / "graph.html").read_text(encoding="utf-8")
    assert "improvedLayout: false" in html


def test_cluster_labels_avoid_namespaced_project_tokens(built):
    """proj: tokens are high-IDF and would otherwise make every label a
    directory name, which tells the user nothing they did not already know."""
    out, _ = built
    _, clusters = sg.load_graph(out)
    for cluster in clusters["clusters"]:
        assert ":" not in cluster["label"]


def test_exemplars_prefer_substantive_sessions_over_stubs(cache, tmp_path):
    """Exemplars are the only sessions read when naming a topic, so a stub like
    "exit" must never be one. Degree alone would pick exactly those, since short
    generic sessions link to everything."""
    claude, bookmarks = cache
    project = claude / "projects" / "-w-warden"
    (project / "stub.jsonl").write_text(
        _turn("exit", "stub", "/w/warden", "2026-07-12T10:00:00.000Z") + "\n", encoding="utf-8")

    out = tmp_path / "brain"
    sg.build(claude, out, k=4, min_sim=0.02, bookmarks_path=bookmarks, now=NOW)
    _, clusters = sg.load_graph(out)
    for cluster in clusters["clusters"]:
        assert "stub" not in cluster["exemplars"]


def test_clusters_carry_activity_stats(built):
    out, _ = built
    _, clusters = sg.load_graph(out)
    for cluster in clusters["clusters"]:
        assert cluster["first_active"] <= cluster["last_active"]
        assert 0.0 <= cluster["recency"] <= 1.0
        assert isinstance(cluster["dormant"], bool)
        assert len(cluster["exemplars"]) <= sg.EXEMPLARS_PER_CLUSTER


# ---------------------------------------------------------------------------
# Incremental rebuild
# ---------------------------------------------------------------------------

def test_second_build_reads_nothing(cache, tmp_path):
    claude, bookmarks = cache
    out = tmp_path / "brain"
    sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW)
    again = sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW)
    assert again["stats"]["read_this_run"] == 0
    assert again["stats"]["reused"] == 7, "every session should come from the cache"
    assert again["stats"]["sessions"] == 7


def test_touching_one_session_re_reads_exactly_one(cache, tmp_path):
    claude, bookmarks = cache
    out = tmp_path / "brain"
    sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW)

    target = claude / "projects" / "-w-warden" / "tel0.jsonl"
    time.sleep(0.01)
    target.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    os.utime(target, (time.time() + 5, time.time() + 5))

    again = sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW)
    assert again["stats"]["read_this_run"] == 1


def test_full_flag_forces_a_complete_reread(cache, tmp_path):
    claude, bookmarks = cache
    out = tmp_path / "brain"
    first = sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW)
    again = sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW, full=True)
    assert again["stats"]["read_this_run"] == first["stats"]["read_this_run"]


def test_deleted_sessions_drop_out_of_the_graph(cache, tmp_path):
    claude, bookmarks = cache
    out = tmp_path / "brain"
    sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW)
    (claude / "projects" / "-w-game" / "spr0.jsonl").unlink()

    again = sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW)
    graph, _ = sg.load_graph(out)
    assert "spr0" not in {n["id"] for n in graph["nodes"]}
    assert again["stats"]["sessions"] == 6


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def test_names_survive_a_rebuild(cache, tmp_path):
    """Cluster ids are positional and shift as the corpus changes, so a name
    keyed to an id alone would be silently reattached to the wrong topic."""
    claude, bookmarks = cache
    out = tmp_path / "brain"
    sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW)
    _, clusters = sg.load_graph(out)
    target = next(c for c in clusters["clusters"] if "telemetry" in c["label"])

    sg.set_cluster_names(out, [{"id": target["id"], "name": "warden telemetry",
                                "summary": "the telemetry pipeline work"}])
    again = sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW, full=True)
    assert again["names_carried_over"] >= 1

    _, clusters2 = sg.load_graph(out)
    named = [c for c in clusters2["clusters"] if c["name"] == "warden telemetry"]
    assert len(named) == 1
    assert "telemetry" in named[0]["label"]


def test_set_cluster_names_requires_a_build(tmp_path):
    with pytest.raises(FileNotFoundError):
        sg.set_cluster_names(tmp_path / "nothing", [{"id": 0, "name": "x"}])


# ---------------------------------------------------------------------------
# Degenerate input
# ---------------------------------------------------------------------------

def test_empty_cache_produces_an_empty_graph_not_a_crash(tmp_path):
    result = sg.build(tmp_path / "none", tmp_path / "brain", now=NOW)
    assert result["stats"]["sessions"] == 0
    graph, clusters = sg.load_graph(tmp_path / "brain")
    assert graph["nodes"] == [] and clusters["clusters"] == []
    assert (tmp_path / "brain" / "graph.html").is_file()


def test_load_graph_without_a_build_explains_itself(tmp_path):
    with pytest.raises(FileNotFoundError, match="sessions-build"):
        sg.load_graph(tmp_path / "nope")
