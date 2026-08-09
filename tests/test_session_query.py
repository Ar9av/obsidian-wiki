from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from obsidian_wiki import session_graph as sg
from obsidian_wiki import session_query as sq

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


def _session(project_dir, sid, text, ts, cwd):
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": text},
                    "timestamp": ts, "cwd": cwd, "gitBranch": "main", "sessionId": sid}),
        json.dumps({"type": "ai-title", "aiTitle": text[:40], "sessionId": sid}),
    ]
    (project_dir / f"{sid}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def brain(tmp_path):
    """Two topics, a bookmark, and a thin history-only session."""
    claude = tmp_path / ".claude"
    for topic, texts, cwd in (("tel", TELEMETRY, "/w/warden"), ("spr", SPRITES, "/w/game")):
        project = claude / "projects" / cwd.replace("/", "-")
        project.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(texts):
            _session(project, f"{topic}{i}", text, _iso(5 + i * 3), cwd)

    (claude / "history.jsonl").write_text(json.dumps({
        "display": "warden telemetry sink batching retries and redacted spans",
        "timestamp": 1783000000000, "project": "/w/warden", "sessionId": "ghost",
    }) + "\n", encoding="utf-8")

    bookmarks = tmp_path / "bookmarks.json"
    bookmarks.write_text(json.dumps([
        {"id": "bm1", "tool": "claude-code", "sessionId": "tel2", "title": "Telemetry",
         "tags": ["observability"], "note": "", "createdAt": "2026-07-10T00:00:00-0700"},
    ]), encoding="utf-8")

    out = tmp_path / "brain"
    sg.build(claude, out, k=3, min_sim=0.05, bookmarks_path=bookmarks, now=NOW)
    return out


def test_query_finds_the_right_topic(brain):
    """Relevance is relevance: a thin session may outrank a full one, but
    nothing from the unrelated topic may reach the top of the list."""
    result = sq.query(brain, "warden telemetry sink", now=NOW)
    assert result["candidates"]
    assert not result["candidates"][0]["session_id"].startswith("spr")
    top_three = {c["session_id"] for c in result["candidates"][:3]}
    assert top_three <= {"tel0", "tel1", "tel2", "ghost"}
    assert "telemetry" in result["terms"]


def test_should_load_only_offers_loadable_sessions(brain):
    result = sq.query(brain, "warden telemetry sink", now=NOW, max_load=3)
    assert result["should_load"]
    assert len(result["should_load"]) <= 3
    by_id = {c["session_id"]: c for c in result["candidates"]}
    assert all(by_id[s]["loadable"] for s in result["should_load"])
    assert "ghost" not in result["should_load"]


def test_pruned_sessions_are_surfaced_not_silently_dropped(brain):
    """A thin session cannot be loaded, but hiding it would misreport history."""
    result = sq.query(brain, "warden telemetry sink", now=NOW, top_n=10)
    ids = {c["session_id"] for c in result["candidates"]}
    assert "ghost" in ids
    assert any(u["session_id"] == "ghost" for u in result["unloadable"])
    assert "no longer on disk" in next(
        u["reason"] for u in result["unloadable"] if u["session_id"] == "ghost")


def test_recency_breaks_a_tie(brain, tmp_path):
    """Two equally relevant sessions must order by recency.

    The pair is added to the full fixture corpus rather than tested alone: two
    identical documents have no distinguishing vocabulary by construction, so a
    corpus of exactly two would index to nothing.
    """
    claude = tmp_path / ".claude"
    project = claude / "projects" / "-w-warden"
    text = "warden telemetry sink batching redacted spans retries chain"
    _session(project, "old", text, _iso(300), "/w/warden")
    _session(project, "new", text, _iso(2), "/w/warden")

    out = tmp_path / "brain2"
    sg.build(claude, out, k=3, min_sim=0.05, now=NOW)
    result = sq.query(out, "warden telemetry", now=NOW, top_n=20)
    ordering = [c["session_id"] for c in result["candidates"]]
    assert ordering.index("new") < ordering.index("old")


def test_an_old_exact_match_still_beats_a_fresh_weak_one(tmp_path):
    """The decay floor exists for exactly this case. Without it the tool cannot
    answer "when did I first set this up?" — which is most of why it exists."""
    claude = tmp_path / ".claude"
    project = claude / "projects" / "-w-warden"
    project.mkdir(parents=True)
    _session(project, "old-exact", "warden telemetry sink batching redacted spans",
             _iso(400), "/w/warden")
    _session(project, "new-weak", "unrelated sprite sheet animation frames slicing work",
             _iso(1), "/w/warden")

    out = tmp_path / "brain"
    sg.build(claude, out, k=3, min_sim=0.05, now=NOW)
    result = sq.query(out, "warden telemetry sink", now=NOW)
    assert result["candidates"][0]["session_id"] == "old-exact"


def test_short_sessions_do_not_outrank_substantive_ones(tmp_path):
    """L2 normalisation hands a one-word session a near-perfect cosine; the
    length prior is what stops `exit` from topping every search."""
    claude = tmp_path / ".claude"
    project = claude / "projects" / "-w-warden"
    project.mkdir(parents=True)
    _session(project, "stub", "telemetry", _iso(1), "/w/warden")
    _session(project, "real",
             "add telemetry batching to the warden runtime with a redacted sink and retries",
             _iso(1), "/w/warden")

    out = tmp_path / "brain"
    sg.build(claude, out, k=3, min_sim=0.05, now=NOW)
    result = sq.query(out, "telemetry batching warden", now=NOW)
    assert result["candidates"][0]["session_id"] == "real"


def test_bookmark_boost_applies(brain):
    result = sq.query(brain, "observability", now=NOW)
    hit = next((c for c in result["candidates"] if c["session_id"] == "tel2"), None)
    assert hit is not None and hit["bookmarked"]
    assert "observability" in hit["tags"]


def test_project_and_cluster_filters(brain):
    scoped = sq.query(brain, "sheet animation frames", now=NOW, project="game")
    assert scoped["candidates"]
    assert all(c["project"] == "game" for c in scoped["candidates"])

    graph, _ = sg.load_graph(brain)
    cid = next(n["cluster"] for n in graph["nodes"]
               if n["id"] == "spr0" and n["cluster"] >= 0)
    by_cluster = sq.query(brain, "sheet animation frames", now=NOW, cluster=cid)
    assert all(c["cluster"] == cid for c in by_cluster["candidates"])


def test_since_filter_excludes_older_sessions(brain):
    cutoff = (NOW - timedelta(days=6)).isoformat()
    result = sq.query(brain, "warden telemetry sink", now=NOW, since=cutoff)
    assert all(c["end_ts"] >= cutoff[:10] for c in result["candidates"])


def test_every_candidate_explains_itself(brain):
    result = sq.query(brain, "warden telemetry sink", now=NOW)
    for candidate in result["candidates"]:
        assert candidate["why"], "a ranked result must say why it ranked"


def test_nonsense_query_returns_nothing_gracefully(brain):
    result = sq.query(brain, "zzzzqqqq nonexistentterm", now=NOW)
    assert result["candidates"] == []
    assert result["should_load"] == []


def test_query_before_build_explains_itself(tmp_path):
    with pytest.raises(FileNotFoundError, match="sessions-build"):
        sq.query(tmp_path / "nope", "anything")


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

def test_show_returns_node_cluster_and_neighbours(brain):
    result = sq.show(brain, "tel0")
    assert result["session"]["id"] == "tel0"
    assert result["cluster"] is not None
    assert result["neighbors"]
    assert all("weight" in n for n in result["neighbors"])
    assert result["load_command"].endswith("tel0")


def test_show_accepts_a_unique_prefix(brain):
    assert sq.show(brain, "ghos")["session"]["id"] == "ghost"


def test_show_rejects_unknown_and_ambiguous_ids(brain):
    with pytest.raises(KeyError, match="unknown session"):
        sq.show(brain, "nope-not-here")
    with pytest.raises(KeyError, match="ambiguous"):
        sq.show(brain, "tel")


def test_show_offers_no_load_command_for_a_thin_session(brain):
    assert sq.show(brain, "ghost")["load_command"] == ""
