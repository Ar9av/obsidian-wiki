"""Build the session graph: similarity edges, topic clusters, time decay.

Ties together `session_sources` (read the caches), `session_index` (vectorise),
and `graph_analysis` (detect communities), then writes a sidecar bundle:

    graph.json     nodes + weighted similarity edges     (public)
    clusters.json  named topic clusters + activity stats (public)
    graph.html     interactive visualisation             (public)
    docs.jsonl     per-session term weights              (internal cache)
    idf.json       inverse document frequencies          (internal cache)
    state.json     size/mtime gating for incremental runs(internal)
    names.json     LLM-assigned cluster names            (internal, durable)

The vault is never touched. This is deliberately a sidecar: session history is
raw material, not compiled knowledge, and mixing the two would put 1000+ noisy
nodes into a graph curated for the opposite property.

Time decay is applied at *query and render time*, never baked into the stored
artifacts — otherwise every file would start rotting the moment it was written.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from obsidian_wiki import session_index as si
from obsidian_wiki import session_sources as ss

HALF_LIFE_DAYS_DEFAULT = 90.0
DEFAULT_OUT_DIR = "~/.claude/session-brain"
GRAPH_VERSION = 1
EDGE_WEIGHT_SCALE = 10       # similarity -> repeated edges, for weighted voting
DORMANT_RECENCY = 0.1
DORMANT_QUIET_DAYS = 60
MOMENTUM_WINDOW_DAYS = 30
CLUSTER_LABEL_TERMS = 3
CLUSTER_TOP_TERMS = 20
STABLE_KEY_TERMS = 8
EXEMPLARS_PER_CLUSTER = 3

# Scalar SessionDoc attributes mirrored into graph.json nodes.
_META_FIELDS = (
    "tier", "title", "title_source", "project", "project_slug", "cwd",
    "git_branch", "start_ts", "end_ts", "n_turns", "n_user_prompts",
    "n_user_words", "transcript", "transcript_bytes", "subagents",
    "pr_links", "repos", "bookmark",
)


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def age_days(end_ts: str | None, now: datetime) -> float | None:
    parsed = parse_ts(end_ts)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds() / 86400.0)


def decay(end_ts: str | None, now: datetime, half_life_days: float = HALF_LIFE_DAYS_DEFAULT) -> float:
    """Exponential recency weight in [0, 1] — 1.0 today, 0.5 one half-life ago.

    The default half-life is 90 days rather than 30: a month-scale half-life
    drives everything older than a quarter below 0.06, which effectively erases
    the archive. Ninety days demotes old sessions without deleting them.
    """
    age = age_days(end_ts, now)
    if age is None or half_life_days <= 0:
        return 0.0
    return max(0.0, min(1.0, 0.5 ** (age / half_life_days)))


# ---------------------------------------------------------------------------
# Document cache (docs.jsonl)
# ---------------------------------------------------------------------------

def _doc_meta(doc: ss.SessionDoc) -> dict[str, Any]:
    return {name: getattr(doc, name) for name in _META_FIELDS}


def save_docs(path: Path, entries: dict[str, dict[str, Any]]) -> None:
    """Persist `{session_id: {"meta": ..., "terms": ...}}` as one JSON per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for session_id in sorted(entries):
            entry = entries[session_id]
            handle.write(json.dumps({
                "id": session_id,
                "meta": entry["meta"],
                "terms": entry["terms"],
            }) + "\n")


def load_docs(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("id"):
                out[rec["id"]] = {"meta": rec.get("meta") or {}, "terms": rec.get("terms") or {}}
    return out


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def _weighted_adjacency(
    edges: list[tuple[int, int, float, list[str]]],
    doc_ids: list[str],
) -> dict[str, list[str]]:
    """Project weighted edges onto the unweighted adjacency graph_analysis wants.

    `detect_communities` counts neighbour labels, and igraph's Leiden treats
    parallel edges as weights, so repeating an edge proportionally to its
    similarity gives weighted voting through an unweighted interface — no
    changes to graph_analysis.py required.
    """
    adjacency: dict[str, list[str]] = {doc_id: [] for doc_id in doc_ids}
    for i, j, weight, _ in edges:
        repeats = max(1, int(round(weight * EDGE_WEIGHT_SCALE)))
        source, target = doc_ids[i], doc_ids[j]
        adjacency[source].extend([target] * repeats)
    return adjacency


def _centroid(index: si.Index, members: list[int]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for i in members:
        for term, value in index.vectors[i].items():
            totals[term] += value
    return totals


def _centroid_terms(index: si.Index, members: list[int], top_n: int) -> list[tuple[str, float]]:
    totals = _centroid(index, members)
    count = max(1, len(members))
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])[:top_n]
    return [(term, round(value / count, 4)) for term, value in ranked]


def _pick_exemplars(index: si.Index, member_ids: list[str], position: dict[str, int],
                    count: int) -> list[str]:
    """The most representative *substantive* members of a cluster.

    Degree alone is a bad proxy: the highest-degree sessions tend to be short
    generic ones ("exit", "ok") that link to everything, which is exactly what
    should not be shown to someone naming the topic. Ranking by closeness to the
    cluster centroid, scaled by how much evidence the session actually has,
    picks members that are both central and worth reading.
    """
    members = [position[m] for m in member_ids]
    centroid = _centroid(index, members)
    norm = math.sqrt(sum(v * v for v in centroid.values())) or 1.0
    unit = {t: v / norm for t, v in centroid.items()}

    scored = [
        (m, si.cosine(index.vectors[position[m]], unit) * si.length_prior(index.vectors[position[m]]))
        for m in member_ids
    ]
    scored.sort(key=lambda kv: -kv[1])
    return [m for m, _ in scored[:count]]


def stable_key(top_terms: list[tuple[str, float]]) -> str:
    """A cluster identity that survives renumbering across rebuilds.

    Community ids are positional and shift whenever the corpus changes, so
    names are keyed by the cluster's dominant vocabulary instead.
    """
    return "-".join(sorted(term for term, _ in top_terms[:STABLE_KEY_TERMS]))


def _cluster_stats(nodes: list[dict], now: datetime, half_life_days: float) -> dict[str, Any]:
    ends = [n["end_ts"] for n in nodes if n.get("end_ts")]
    ends.sort()
    ages = [a for a in (age_days(e, now) for e in ends) if a is not None]
    recent = sum(1 for a in ages if a <= MOMENTUM_WINDOW_DAYS)
    prior = sum(1 for a in ages if MOMENTUM_WINDOW_DAYS < a <= 3 * MOMENTUM_WINDOW_DAYS)
    recency = max((decay(e, now, half_life_days) for e in ends), default=0.0)
    quiet = min(ages) if ages else None
    return {
        "first_active": ends[0] if ends else "",
        "last_active": ends[-1] if ends else "",
        "recency": round(recency, 4),
        "momentum": round(recent / max(1, prior), 2),
        "active_30d": recent,
        "dormant": recency < DORMANT_RECENCY and (quiet is None or quiet > DORMANT_QUIET_DAYS),
    }


def _build_clusters(
    index: si.Index,
    edges: list[tuple[int, int, float, list[str]]],
    node_by_id: dict[str, dict],
    now: datetime,
    half_life_days: float,
) -> tuple[list[dict], dict[str, int]]:
    from obsidian_wiki.graph_analysis import detect_communities, surprising_connections

    adjacency = _weighted_adjacency(edges, index.doc_ids)
    linked = {doc_id for doc_id, targets in adjacency.items() if targets}
    for targets in adjacency.values():
        linked.update(targets)

    communities = [c for c in detect_communities(adjacency) if len(c & linked) > 1]
    communities.sort(key=lambda c: -len(c))

    position = {doc_id: i for i, doc_id in enumerate(index.doc_ids)}
    degree: dict[str, int] = defaultdict(int)
    for i, j, _, _ in edges:
        degree[index.doc_ids[i]] += 1
        degree[index.doc_ids[j]] += 1

    assignment: dict[str, int] = {}
    clusters: list[dict] = []
    for cid, members in enumerate(communities):
        member_ids = sorted(members & linked)
        if not member_ids:
            continue
        for member in member_ids:
            assignment[member] = cid
        top_terms = _centroid_terms(index, [position[m] for m in member_ids], CLUSTER_TOP_TERMS)
        # Namespaced tokens (proj:, repo:) are unique per project and therefore
        # high-IDF, so they win every centroid and make each label read as the
        # directory name. They stay in the vector — searching for a project is
        # genuinely useful — but a label should say what the work *was*.
        label_terms = [t for t, _ in top_terms if ":" not in t]
        member_nodes = [node_by_id[m] for m in member_ids if m in node_by_id]
        projects: dict[str, int] = defaultdict(int)
        for node in member_nodes:
            if node.get("project"):
                projects[node["project"]] += 1
        exemplars = _pick_exemplars(index, member_ids, position, EXEMPLARS_PER_CLUSTER)

        cluster = {
            "id": cid,
            "size": len(member_ids),
            "label": " ".join(label_terms[:CLUSTER_LABEL_TERMS]) or f"cluster-{cid}",
            "label_source": "terms",
            "stable_key": stable_key(top_terms),
            "name": None,
            "summary": None,
            "sessions": member_ids,
            "top_terms": top_terms,
            "projects": dict(sorted(projects.items(), key=lambda kv: -kv[1])),
            "exemplars": exemplars,
            "bridges": [],
        }
        cluster.update(_cluster_stats(member_nodes, now, half_life_days))
        clusters.append(cluster)

    # Bridges: cross-community edges between otherwise inward-facing sessions.
    # These are the sessions where two topics actually met.
    community_sets = [set(c["sessions"]) for c in clusters]
    if community_sets:
        by_pair: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for link in surprising_connections(adjacency, community_sets, top_n=60):
            a = assignment.get(link["source"])
            b = assignment.get(link["target"])
            if a is None or b is None or a == b:
                continue
            by_pair[(min(a, b), max(a, b))].append(link)
        for (a, b), links in by_pair.items():
            best = max(links, key=lambda link: link["score"])
            via = [best["source"], best["target"]]
            clusters[a]["bridges"].append({"to": b, "score": best["score"], "via": via})
            clusters[b]["bridges"].append({"to": a, "score": best["score"], "via": via})

    return clusters, assignment


def carry_over_names(clusters: list[dict], names: dict[str, Any]) -> int:
    """Re-apply stored names to freshly numbered clusters.

    Matches on the stable vocabulary key first, then falls back to membership
    overlap so a cluster that gained or lost a few sessions keeps its name.
    """
    entries = names.get("clusters") or {}
    if not entries:
        return 0

    by_key = {key: value for key, value in entries.items()}
    used: set[str] = set()
    applied = 0

    for cluster in clusters:
        entry = by_key.get(cluster["stable_key"])
        if entry and cluster["stable_key"] not in used:
            cluster["name"] = entry.get("name")
            cluster["summary"] = entry.get("summary")
            used.add(cluster["stable_key"])
            applied += 1

    for cluster in clusters:
        if cluster["name"]:
            continue
        members = set(cluster["sessions"])
        best_key, best_score = None, 0.0
        for key, entry in by_key.items():
            if key in used:
                continue
            previous = set(entry.get("sessions") or [])
            if not previous:
                continue
            overlap = len(members & previous) / len(members | previous)
            if overlap > best_score:
                best_key, best_score = key, overlap
        if best_key and best_score >= 0.5:
            cluster["name"] = by_key[best_key].get("name")
            cluster["summary"] = by_key[best_key].get("summary")
            used.add(best_key)
            applied += 1

    return applied


def set_cluster_names(out_dir: Path, updates: list[dict]) -> dict[str, Any]:
    """Record human/LLM cluster names and re-emit the dependent artifacts."""
    out_dir = Path(out_dir).expanduser()
    clusters_doc = _read_json(out_dir / "clusters.json", None)
    if not clusters_doc:
        raise FileNotFoundError(f"no clusters.json in {out_dir} — run sessions-build first")

    clusters = clusters_doc.get("clusters") or []
    by_id = {c["id"]: c for c in clusters}
    names = _read_json(out_dir / "names.json", {"clusters": {}})
    names.setdefault("clusters", {})

    applied = 0
    for update in updates:
        cluster = by_id.get(update.get("id"))
        if cluster is None:
            continue
        cluster["name"] = update.get("name") or cluster.get("name")
        cluster["summary"] = update.get("summary") or cluster.get("summary")
        names["clusters"][cluster["stable_key"]] = {
            "name": cluster["name"],
            "summary": cluster["summary"],
            "sessions": cluster["sessions"],
        }
        applied += 1

    _write_json(out_dir / "clusters.json", clusters_doc)
    _write_json(out_dir / "names.json", names)

    graph = _read_json(out_dir / "graph.json", None)
    if graph and (out_dir / "graph.html").exists():
        from obsidian_wiki.session_viz import render_html
        (out_dir / "graph.html").write_text(
            render_html(graph, clusters_doc,
                        half_life_days=graph.get("half_life_days", HALF_LIFE_DAYS_DEFAULT),
                        out_dir=out_dir),
            encoding="utf-8")

    return {"named": applied, "clusters": len(clusters)}


def load_graph(out_dir: Path) -> tuple[dict, dict]:
    out_dir = Path(out_dir).expanduser()
    graph = _read_json(out_dir / "graph.json", None)
    if not graph:
        raise FileNotFoundError(
            f"no session graph in {out_dir} — run `obsidian-wiki sessions-build` first")
    return graph, _read_json(out_dir / "clusters.json", {"clusters": []})


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(
    claude_dir: Path,
    out_dir: Path,
    *,
    k: int = 8,
    min_sim: float = 0.08,
    mutual: bool = False,
    half_life_days: float = HALF_LIFE_DAYS_DEFAULT,
    full: bool = False,
    since: str | None = None,
    skip: list[str] | None = None,
    bookmarks_path: Path | None = None,
    write_html: bool = True,
    now: datetime | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Read the caches, rebuild the graph, and write the sidecar bundle."""
    claude_dir = Path(claude_dir).expanduser()
    out_dir = Path(out_dir).expanduser()
    now = now or datetime.now(timezone.utc)
    say = progress or (lambda _msg: None)

    state = {} if full else _read_json(out_dir / "state.json", {})
    cached = {} if full else load_docs(out_dir / "docs.jsonl")

    say("reading session caches…")
    docs, info = ss.collect(
        claude_dir, bookmarks_path=bookmarks_path, skip=skip, since=since,
        state=None if full else state,
    )
    say(f"read {len(docs)} session(s), reused {len(info['unchanged'])} cached")

    # Merge freshly read sessions over the cache, then drop anything that has
    # disappeared from the caches entirely.
    entries: dict[str, dict[str, Any]] = {}
    live_ids = set(info["state"]["sources"])
    for session_id, entry in cached.items():
        if session_id in live_ids:
            entries[session_id] = entry
    for doc in docs:
        entries[doc.session_id] = {"meta": _doc_meta(doc), "terms": si.term_weights(doc)}

    # Bookmarks change independently of transcripts, so refresh them across the
    # whole corpus rather than only on sessions re-read this run.
    bookmarks = ss.load_bookmarks(bookmarks_path)
    for session_id, entry in entries.items():
        entry["meta"]["bookmark"] = bookmarks.get(session_id)

    if not entries:
        say("no sessions found")
        return _write_empty(out_dir, half_life_days, now, write_html)

    say(f"indexing {len(entries)} sessions…")
    index = si.build_index({sid: entry["terms"] for sid, entry in entries.items()})
    edges_raw = si.knn(index, k=k, min_sim=min_sim, mutual=mutual)
    say(f"{len(edges_raw)} similarity edge(s)")

    degree: dict[str, int] = defaultdict(int)
    for i, j, _, _ in edges_raw:
        degree[index.doc_ids[i]] += 1
        degree[index.doc_ids[j]] += 1

    nodes: list[dict] = []
    node_by_id: dict[str, dict] = {}
    for position, session_id in enumerate(index.doc_ids):
        meta = dict(entries[session_id]["meta"])
        node = {"id": session_id, **meta}
        node["degree"] = degree.get(session_id, 0)
        node["top_terms"] = si.top_terms_for(index, position, 10)
        node["cluster"] = -1
        nodes.append(node)
        node_by_id[session_id] = node

    say("detecting topic clusters…")
    clusters, assignment = _build_clusters(index, edges_raw, node_by_id, now, half_life_days)
    for session_id, cid in assignment.items():
        node_by_id[session_id]["cluster"] = cid

    names = _read_json(out_dir / "names.json", {"clusters": {}})
    carried = carry_over_names(clusters, names)

    edges = [
        {
            "source": index.doc_ids[i],
            "target": index.doc_ids[j],
            "weight": round(weight, 4),
            "shared": shared,
            "cross_cluster": assignment.get(index.doc_ids[i], -1) != assignment.get(index.doc_ids[j], -2),
        }
        for i, j, weight, shared in edges_raw
    ]

    tiers: dict[str, int] = defaultdict(int)
    for node in nodes:
        tiers[node.get("tier", "full")] += 1

    graph = {
        "version": GRAPH_VERSION,
        "generated_at": now.isoformat(),
        "source": "claude",
        "half_life_days": half_life_days,
        "stats": {
            "sessions": len(nodes),
            "full": tiers.get("full", 0),
            "thin": tiers.get("thin", 0),
            "edges": len(edges),
            "clusters": len(clusters),
            "unclustered": sum(1 for n in nodes if n["cluster"] == -1),
            "vocab": len(index.idf),
            "read_this_run": len(docs),
            "reused": len(info["unchanged"]),
        },
        "nodes": nodes,
        "edges": edges,
    }
    clusters_doc = {
        "version": GRAPH_VERSION,
        "generated_at": now.isoformat(),
        "half_life_days": half_life_days,
        "clusters": clusters,
    }

    say("writing artifacts…")
    _write_json(out_dir / "graph.json", graph)
    _write_json(out_dir / "clusters.json", clusters_doc)
    _write_json(out_dir / "idf.json", index.idf)
    _write_json(out_dir / "state.json", info["state"])
    save_docs(out_dir / "docs.jsonl", entries)
    if write_html:
        from obsidian_wiki.session_viz import render_html
        (out_dir / "graph.html").write_text(
            render_html(graph, clusters_doc, half_life_days=half_life_days,
                        out_dir=out_dir), encoding="utf-8")

    return {
        "out_dir": str(out_dir),
        "stats": graph["stats"],
        "clusters": [
            {"id": c["id"], "size": c["size"], "label": c["label"], "name": c["name"],
             "recency": c["recency"], "momentum": c["momentum"], "dormant": c["dormant"]}
            for c in clusters
        ],
        "names_carried_over": carried,
        "unnamed": sum(1 for c in clusters if not c["name"]),
    }


def _write_empty(out_dir: Path, half_life_days: float, now: datetime, write_html: bool) -> dict:
    graph = {
        "version": GRAPH_VERSION,
        "generated_at": now.isoformat(),
        "source": "claude",
        "half_life_days": half_life_days,
        "stats": {"sessions": 0, "full": 0, "thin": 0, "edges": 0, "clusters": 0,
                  "unclustered": 0, "vocab": 0, "read_this_run": 0, "reused": 0},
        "nodes": [], "edges": [],
    }
    clusters_doc = {"version": GRAPH_VERSION, "generated_at": now.isoformat(),
                    "half_life_days": half_life_days, "clusters": []}
    _write_json(out_dir / "graph.json", graph)
    _write_json(out_dir / "clusters.json", clusters_doc)
    _write_json(out_dir / "state.json", {"sources": {}, "history": None, "bookmarks": None})
    save_docs(out_dir / "docs.jsonl", {})
    if write_html:
        from obsidian_wiki.session_viz import render_html
        (out_dir / "graph.html").write_text(
            render_html(graph, clusters_doc, half_life_days=half_life_days,
                        out_dir=out_dir), encoding="utf-8")
    return {"out_dir": str(out_dir), "stats": graph["stats"], "clusters": [],
            "names_carried_over": 0, "unnamed": 0}
