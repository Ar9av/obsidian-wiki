"""Query the session graph: rank sessions by relevance, recency, and topic.

Mirrors the contract of `graphrag.query` — return ranked candidates plus a short
`should_load` list, so the agent opens one or two transcripts instead of ten.

The ranking combines four signals:

  similarity    cosine of the query against the session's TF-IDF vector
  cluster lift  a session inside the best-matching topic scores higher even if
                its own text never used the query's words. This is the whole
                payoff of clustering over plain search.
  bookmarks     a human already decided this session mattered
  recency       exponential time decay, applied with a floor

The floor matters more than the decay. `0.35 + 0.65 * decay` means a stale but
exact match still beats a fresh but weak one — without it the tool cannot answer
"when did I first set this up?", which is half of what session history is for.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from obsidian_wiki import session_index as si
from obsidian_wiki.session_graph import (
    HALF_LIFE_DAYS_DEFAULT, age_days, decay, load_docs, load_graph, parse_ts,
)

CLUSTER_LIFT = 0.25
CLUSTER_LIFT_MEMBERS = 5
TITLE_BOOST = 0.15
BOOKMARK_TAG_BOOST = 1.30
BOOKMARK_BOOST = 1.15
RECENCY_FLOOR = 0.35          # weight retained by an infinitely old session
SHOULD_LOAD_RATIO = 0.6       # relative to the top score
SEARCH_POOL = 200


def _index_for(out_dir: Path) -> si.Index:
    """Rebuild the TF-IDF index from the cached term maps.

    Cheaper than it sounds — about a tenth of a second for a thousand sessions —
    and it avoids persisting vectors that would fall out of sync with docs.jsonl.
    """
    docs = load_docs(out_dir / "docs.jsonl")
    return si.build_index({sid: entry["terms"] for sid, entry in docs.items()})


def _bookmark_multiplier(node: dict, terms: set[str]) -> tuple[float, str]:
    bookmark = node.get("bookmark")
    if not bookmark:
        return 1.0, ""
    tags = {t.lower() for t in bookmark.get("tags") or []}
    if tags & terms:
        return BOOKMARK_TAG_BOOST, "bookmark tag match"
    return BOOKMARK_BOOST, "bookmarked"


def _explain(matched: list[str], node: dict, cluster_name: str,
             bookmark_note: str, age: float | None) -> str:
    parts: list[str] = []
    if matched:
        parts.append(", ".join(matched[:4]))
    if cluster_name:
        parts.append(f"topic:{cluster_name}")
    if bookmark_note:
        parts.append(bookmark_note)
    if age is not None:
        parts.append(f"{int(age)}d ago")
    return " · ".join(parts) or "weak match"


def query(
    out_dir: Path,
    question: str,
    *,
    top_n: int = 10,
    max_load: int = 3,
    half_life_days: float | None = None,
    project: str | None = None,
    cluster: int | None = None,
    since: str | None = None,
    min_score: float = 0.05,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Rank sessions against a question and recommend which to load."""
    out_dir = Path(out_dir).expanduser()
    graph, clusters_doc = load_graph(out_dir)
    now = now or datetime.now(timezone.utc)
    half_life = half_life_days or graph.get("half_life_days") or HALF_LIFE_DAYS_DEFAULT

    node_by_id = {n["id"]: n for n in graph.get("nodes", [])}
    clusters = clusters_doc.get("clusters", [])
    cluster_by_id = {c["id"]: c for c in clusters}

    index = _index_for(out_dir)
    if not len(index):
        return _empty(question, graph, half_life)

    qvec = si.vectorize_query(question, index.idf)
    hits = si.search(index, qvec, top_n=SEARCH_POOL)
    if not hits:
        return _empty(question, graph, half_life)

    sim_by_id = {index.doc_ids[i]: (score, terms) for i, score, terms in hits}
    query_terms = set(qvec)

    # Cluster lift: score each topic by how well its strongest members match,
    # then lift every member of the best topic.
    cluster_scores: dict[int, float] = {}
    for c in clusters:
        member_sims = sorted(
            (sim_by_id.get(s, (0.0, []))[0] for s in c["sessions"]), reverse=True
        )[:CLUSTER_LIFT_MEMBERS]
        if member_sims and member_sims[0] > 0:
            cluster_scores[c["id"]] = sum(member_sims) / len(member_sims)
    best_cluster = max(cluster_scores, key=lambda cid: cluster_scores[cid]) if cluster_scores else None
    lift = CLUSTER_LIFT * cluster_scores.get(best_cluster, 0.0) if best_cluster is not None else 0.0

    since_dt = parse_ts(since) if since else None
    candidates: list[dict] = []

    considered = set(sim_by_id)
    if best_cluster is not None:
        considered |= set(cluster_by_id[best_cluster]["sessions"])

    for session_id in considered:
        node = node_by_id.get(session_id)
        if node is None:
            continue
        if project and node.get("project") != project:
            continue
        if cluster is not None and node.get("cluster") != cluster:
            continue
        if since_dt is not None:
            ended = parse_ts(node.get("end_ts"))
            if ended is None or ended < since_dt:
                continue

        similarity, matched = sim_by_id.get(session_id, (0.0, []))
        member_lift = lift if node.get("cluster") == best_cluster else 0.0

        title = (node.get("title") or "").lower()
        title_boost = TITLE_BOOST if query_terms and all(t in title for t in query_terms) else 0.0

        multiplier, bookmark_note = _bookmark_multiplier(node, query_terms)
        recency = decay(node.get("end_ts"), now, half_life)
        age = age_days(node.get("end_ts"), now)

        score = (similarity + member_lift + title_boost) * multiplier * \
            (RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * recency)
        if score < min_score:
            continue

        node_cluster = cluster_by_id.get(node.get("cluster", -1))
        cluster_name = (node_cluster.get("name") or node_cluster.get("label")) if node_cluster else ""

        candidates.append({
            "session_id": session_id,
            "title": node.get("title") or "",
            "project": node.get("project") or "",
            "score": round(score, 4),
            "similarity": round(similarity, 4),
            "recency": round(recency, 4),
            "end_ts": node.get("end_ts") or "",
            "age_days": int(age) if age is not None else None,
            "n_turns": node.get("n_turns", 0),
            "cluster": node.get("cluster", -1),
            "cluster_name": cluster_name,
            "bookmarked": bool(node.get("bookmark")),
            "tags": (node.get("bookmark") or {}).get("tags", []),
            "tier": node.get("tier", "full"),
            "loadable": node.get("tier") == "full" and bool(node.get("transcript")),
            "transcript": node.get("transcript"),
            "matched_terms": matched,
            "why": _explain(matched, node, cluster_name, bookmark_note, age),
        })

    candidates.sort(key=lambda c: -c["score"])
    top = candidates[:top_n]

    loadable = [c for c in top if c["loadable"]]
    cutoff = top[0]["score"] * SHOULD_LOAD_RATIO if top else 0.0
    should_load = [c["session_id"] for c in loadable if c["score"] >= cutoff][:max_load]

    # A pruned session can still answer "did I ever work on this?", so its
    # surviving prompts are returned inline rather than silently dropped.
    unloadable = [
        {"session_id": c["session_id"], "title": c["title"], "end_ts": c["end_ts"],
         "reason": "history-only — transcript no longer on disk"}
        for c in top if not c["loadable"]
    ]

    return {
        "query": question,
        "terms": sorted(query_terms),
        "candidates": top,
        "clusters": [
            {"id": cid, "name": cluster_by_id[cid].get("name"),
             "label": cluster_by_id[cid].get("label"), "score": round(score, 4),
             "size": cluster_by_id[cid]["size"],
             "last_active": cluster_by_id[cid].get("last_active", "")}
            for cid, score in sorted(cluster_scores.items(), key=lambda kv: -kv[1])[:5]
            if cid in cluster_by_id
        ],
        "should_load": should_load,
        "load_command": f"/claude-session-load {should_load[0]}" if should_load else "",
        "unloadable": unloadable,
        "stats": {
            "indexed": len(index),
            "half_life_days": half_life,
            "considered": len(candidates),
        },
    }


def _empty(question: str, graph: dict, half_life: float) -> dict[str, Any]:
    return {
        "query": question, "terms": [], "candidates": [], "clusters": [],
        "should_load": [], "load_command": "", "unloadable": [],
        "stats": {"indexed": graph.get("stats", {}).get("sessions", 0),
                  "half_life_days": half_life, "considered": 0},
    }


def show(out_dir: Path, session_id: str, *, neighbors: int = 8) -> dict[str, Any]:
    """Inspect one session: its node, its topic, and its nearest neighbours."""
    out_dir = Path(out_dir).expanduser()
    graph, clusters_doc = load_graph(out_dir)
    nodes = {n["id"]: n for n in graph.get("nodes", [])}

    node = nodes.get(session_id)
    if node is None:
        matches = [sid for sid in nodes if sid.startswith(session_id)]
        if len(matches) == 1:
            node = nodes[matches[0]]
        elif len(matches) > 1:
            raise KeyError(f"ambiguous session prefix {session_id!r}: {len(matches)} matches")
        else:
            raise KeyError(f"unknown session {session_id!r}")

    session_id = node["id"]
    linked: list[dict] = []
    for edge in graph.get("edges", []):
        if edge["source"] == session_id:
            other = edge["target"]
        elif edge["target"] == session_id:
            other = edge["source"]
        else:
            continue
        peer = nodes.get(other)
        if peer is None:
            continue
        linked.append({
            "session_id": other, "title": peer.get("title") or "",
            "project": peer.get("project") or "", "weight": edge["weight"],
            "shared": edge["shared"], "end_ts": peer.get("end_ts") or "",
        })
    linked.sort(key=lambda n: -n["weight"])

    cluster = next((c for c in clusters_doc.get("clusters", [])
                    if c["id"] == node.get("cluster")), None)
    return {
        "session": node,
        "cluster": {
            "id": cluster["id"], "name": cluster.get("name"), "label": cluster.get("label"),
            "size": cluster["size"], "top_terms": [t for t, _ in cluster["top_terms"][:10]],
        } if cluster else None,
        "neighbors": linked[:neighbors],
        "load_command": f"/claude-session-load {session_id}" if node.get("transcript") else "",
    }
