"""Vault graph analysis: community detection, god nodes, bridges, surprising connections.

Reads the vault's wikilink graph (from page frontmatter and [[wikilinks]]),
then runs the same family of algorithms graphify uses on code graphs — all in
pure Python (no networkx / numpy):
  1. Degree-based god-node ranking (most-linked pages)
  2. Community detection — Leiden via `obsidian-wiki[graph]` if installed,
     else greedy label propagation (pure Python, no binary deps)
  3. Community cohesion — intra-community edge density (graphify
     `cohesion_score`); < 0.15 flags a fragmented cluster
  4. Bridge pages — Brandes betweenness centrality; the pages that sit on
     the most shortest paths between other pages (graphify's bridge nodes)
  5. Surprising connections — cross-community edges ranked by unexpectedness,
     de-duplicated one-per-community-pair so a single hub can't dominate
  6. Suggested questions — derived from bridges, isolates, dead-end hubs and
     low-cohesion communities (graphify `suggest_questions`)
  7. Path finding / neighbourhoods — `shortest_path` and BFS `neighborhood`
     (graphify `path` and blast-radius / `affected`)
  8. Graph diff — compare against a previous snapshot (graphify `graph_diff`)

Output JSON:
{
  "god_nodes": [{"page": "...", "degree": N, "in_degree": N, "out_degree": N}, ...],
  "bridges": [{"page": "...", "betweenness": 0.N, "connects": [comm_id, ...]}, ...],
  "communities": [{"id": N, "size": N, "pages": [...], "label": "...", "cohesion": 0.N}, ...],
  "surprising_connections": [{"source": "...", "target": "...", "score": 0.N,
                              "note": "bridges community A -> community B"}, ...],
  "suggested_questions": [{"type": "...", "question": "...", "why": "..."}, ...],
  "dead_ends": ["page with 0 outgoing links", ...],
  "isolated": ["page with 0 links at all", ...],
  "stats": {"pages": N, "edges": N, "communities": N, "density": 0.N}
}
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Wikilink / frontmatter parsing
# ---------------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")
_MD_LINK_RE = re.compile(r"\[.*?\]\(([^)]+\.md[^)]*)\)")
_TAGS_RE = re.compile(r"^tags:\s*\[([^\]]+)\]", re.MULTILINE)
_TAGS_LIST_RE = re.compile(r"^tags:\s*\n((?:\s+-\s+\S+\n)+)", re.MULTILINE)


def _slug(page_name: str) -> str:
    """Normalise a wikilink target to a page slug."""
    return page_name.strip().lower().replace(" ", "-")


def _page_slug(path: Path, root: Path) -> str:
    return _slug(path.stem)


# --- Shared page selection -------------------------------------------------
# Every module that builds a graph over the vault MUST use these, so the
# wikilink graph is identical no matter which entry point produced it.

#: Directories that hold staging / archive / config material, not knowledge.
SKIP_DIRS = frozenset({
    "_raw", "_archived", "_staging", "_archives", "_meta", "_readouts", ".obsidian",
})

#: Vault bookkeeping files at the vault ROOT. They link to (almost) every page,
#: so leaving them in makes every pair of pages look ~2 hops apart and lets a
#: table of contents outrank real knowledge in every degree/centrality ranking.
#: Only the root-level files are skipped — a legitimate `concepts/index.md`
#: is still a normal page.
SKIP_ROOT_FILES = frozenset({"index", "log", "hot", "_insights"})


def is_wiki_page(path: Path, vault: Path) -> bool:
    """True if `path` is a knowledge page of `vault` (not staging/bookkeeping)."""
    try:
        rel = path.relative_to(vault)
    except ValueError:
        return False
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    if len(rel.parts) == 1 and path.stem in SKIP_ROOT_FILES:
        return False
    return True


def iter_pages(vault: Path) -> list[Path]:
    """All knowledge pages in the vault, in stable sorted order."""
    return sorted(p for p in vault.rglob("*.md") if is_wiki_page(p, vault))


def parse_vault_graph(vault: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Parse all .md pages and return (outgoing_edges, page_tags).

    outgoing_edges: {source_slug: [target_slug, ...]}
    page_tags:      {slug: [tag, ...]}
    """
    outgoing: dict[str, list[str]] = defaultdict(list)
    tags_map: dict[str, list[str]] = {}

    pages: list[Path] = iter_pages(vault)

    known_slugs = {_page_slug(p, vault) for p in pages}

    for page in pages:
        src = _page_slug(page, vault)
        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Tags
        m = _TAGS_RE.search(text)
        if m:
            tags_map[src] = [t.strip().strip("'\"") for t in m.group(1).split(",")]
        else:
            m2 = _TAGS_LIST_RE.search(text)
            if m2:
                tags_map[src] = [ln.strip().lstrip("- ") for ln in m2.group(1).splitlines() if ln.strip()]

        # Wikilinks
        for link in _WIKILINK_RE.findall(text):
            target = _slug(link.split("/")[-1])
            if target and target != src and target in known_slugs:
                outgoing[src].append(target)

        # Markdown links (when OBSIDIAN_LINK_FORMAT=markdown)
        for href in _MD_LINK_RE.findall(text):
            target = _slug(Path(href).stem)
            if target and target != src and target in known_slugs:
                outgoing[src].append(target)

        if src not in outgoing:
            outgoing[src] = []

    # Ensure every known page appears as a key
    for p in pages:
        s = _page_slug(p, vault)
        outgoing.setdefault(s, [])

    return dict(outgoing), tags_map


# ---------------------------------------------------------------------------
# Graph metrics
# ---------------------------------------------------------------------------

def _build_degree_tables(
    outgoing: dict[str, list[str]]
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    out_deg: dict[str, int] = {n: len(v) for n, v in outgoing.items()}
    in_deg: dict[str, int] = defaultdict(int)
    for targets in outgoing.values():
        for t in targets:
            in_deg[t] += 1
    degree = {n: out_deg.get(n, 0) + in_deg.get(n, 0) for n in outgoing}
    for n in in_deg:
        degree.setdefault(n, in_deg[n])
    return degree, dict(in_deg), out_deg


def god_nodes(outgoing: dict[str, list[str]], top_n: int = 20) -> list[dict]:
    degree, in_deg, out_deg = _build_degree_tables(outgoing)
    ranked = sorted(degree, key=lambda n: -degree[n])[:top_n]
    return [
        {"page": n, "degree": degree[n],
         "in_degree": in_deg.get(n, 0), "out_degree": out_deg.get(n, 0)}
        for n in ranked
    ]


def dead_ends(outgoing: dict[str, list[str]]) -> list[str]:
    """Pages with no outgoing links."""
    return [n for n, targets in outgoing.items() if not targets]


def isolated(outgoing: dict[str, list[str]]) -> list[str]:
    """Pages with zero links in either direction."""
    _, in_deg, out_deg = _build_degree_tables(outgoing)
    return [n for n in outgoing if in_deg.get(n, 0) == 0 and out_deg.get(n, 0) == 0]


# ---------------------------------------------------------------------------
# Community detection — greedy modularity (Newman-Girvan, pure Python)
# ---------------------------------------------------------------------------

def _modularity(communities: list[set[str]], outgoing: dict[str, list[str]]) -> float:
    """Approximate modularity Q for an undirected projection of outgoing edges."""
    all_edges = [(s, t) for s, targets in outgoing.items() for t in targets]
    m = len(all_edges)
    if m == 0:
        return 0.0
    degree = defaultdict(int)
    for s, t in all_edges:
        degree[s] += 1
        degree[t] += 1
    node_comm: dict[str, int] = {}
    for i, comm in enumerate(communities):
        for n in comm:
            node_comm[n] = i
    Q = 0.0
    for s, t in all_edges:
        if node_comm.get(s) == node_comm.get(t):
            Q += 1 - (degree[s] * degree[t]) / (2 * m)
    return Q / m


def detect_communities_greedy(outgoing: dict[str, list[str]]) -> list[set[str]]:
    """Greedy modularity community detection (label propagation variant).

    Fast O(n·k) approach suitable for vaults up to ~5 000 pages. Each node
    adopts the most frequent label among its neighbours; iterate until stable.
    Falls back gracefully to one community per page if the graph is empty.
    """
    nodes = list(outgoing.keys())
    if not nodes:
        return []

    # Build undirected adjacency
    adj: dict[str, list[str]] = defaultdict(list)
    for src, targets in outgoing.items():
        for t in targets:
            adj[src].append(t)
            adj[t].append(src)

    # Initialise: each node in its own community (label = index)
    labels: dict[str, int] = {n: i for i, n in enumerate(nodes)}

    # Visit nodes in a shuffled order each round. A fixed sequential sweep
    # cascades one label along chains and collapses well-separated clusters
    # into a single community (a barbell graph comes back as one group). The
    # RNG is seeded from the node set, so the result stays reproducible.
    rng = random.Random(len(nodes))
    order = list(nodes)

    for _ in range(20):  # max 20 rounds
        changed = False
        rng.shuffle(order)
        for n in order:
            neighbours = adj[n]
            if not neighbours:
                continue
            freq: dict[int, int] = defaultdict(int)
            for nb in neighbours:
                freq[labels[nb]] += 1
            best = max(freq, key=lambda lbl: (freq[lbl], -lbl))
            if best != labels[n]:
                labels[n] = best
                changed = True
        if not changed:
            break

    # Group by label
    groups: dict[int, set[str]] = defaultdict(set)
    for n, lbl in labels.items():
        groups[lbl].add(n)
    return list(groups.values())


def detect_communities(outgoing: dict[str, list[str]]) -> list[set[str]]:
    """Try Leiden (leidenalg + igraph) first; fall back to greedy label propagation."""
    try:
        import igraph as ig
        import leidenalg

        nodes = list(outgoing.keys())
        node_idx = {n: i for i, n in enumerate(nodes)}
        edges = [
            (node_idx[s], node_idx[t])
            for s, targets in outgoing.items()
            for t in targets
            if t in node_idx
        ]
        g = ig.Graph(n=len(nodes), edges=edges, directed=False)
        partition = leidenalg.find_partition(g, leidenalg.ModularityVertexPartition)
        return [
            {nodes[i] for i in cluster}
            for cluster in partition
        ]
    except ImportError:
        return detect_communities_greedy(outgoing)


def _undirected_adj(outgoing: dict[str, list[str]]) -> dict[str, set[str]]:
    """Undirected simple-graph adjacency (duplicate/self edges collapsed)."""
    adj: dict[str, set[str]] = {n: set() for n in outgoing}
    for src, targets in outgoing.items():
        for t in targets:
            if t == src:
                continue
            adj[src].add(t)
            adj.setdefault(t, set()).add(src)
    return adj


def _node_community_map(communities: list[set[str]]) -> dict[str, int]:
    return {n: i for i, comm in enumerate(communities) for n in comm}


# ---------------------------------------------------------------------------
# Community cohesion (graphify: cluster.cohesion_score)
# ---------------------------------------------------------------------------

def cohesion_score(outgoing: dict[str, list[str]], community: set[str]) -> float:
    """Ratio of actual intra-community (undirected) edges to the maximum possible.

    1.0 = clique, 0.0 = no internal links. Singletons score 1.0.
    """
    n = len(community)
    if n <= 1:
        return 1.0
    adj = _undirected_adj(outgoing)
    actual = sum(1 for a in community for b in adj.get(a, ()) if b in community and a < b)
    possible = n * (n - 1) / 2
    return round(actual / possible, 4) if possible else 0.0


# ---------------------------------------------------------------------------
# Betweenness centrality — Brandes (2001), pure Python
# (graphify: nx.betweenness_centrality → "bridge nodes")
# ---------------------------------------------------------------------------

def betweenness_centrality(
    outgoing: dict[str, list[str]],
    normalized: bool = True,
) -> dict[str, float]:
    """Exact node betweenness on the undirected projection (Brandes algorithm).

    O(V·E) — fine for vaults up to a few thousand pages. Values are normalised
    to [0, 1] by 2/((n-1)(n-2)) so scores are comparable across vault sizes.
    """
    adj = _undirected_adj(outgoing)
    nodes = list(adj)
    bc: dict[str, float] = {n: 0.0 for n in nodes}
    for s in nodes:
        stack: list[str] = []
        preds: dict[str, list[str]] = {n: [] for n in nodes}
        sigma: dict[str, float] = {n: 0.0 for n in nodes}
        dist: dict[str, int] = {n: -1 for n in nodes}
        sigma[s] = 1.0
        dist[s] = 0
        queue = [s]
        qi = 0
        while qi < len(queue):
            v = queue[qi]
            qi += 1
            stack.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    preds[w].append(v)
        delta: dict[str, float] = {n: 0.0 for n in nodes}
        while stack:
            w = stack.pop()
            for v in preds[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                bc[w] += delta[w]
    n = len(nodes)
    # Undirected: every pair counted twice
    scale = 0.5
    if normalized and n > 2:
        scale = 1.0 / ((n - 1) * (n - 2))
    return {k: v * scale for k, v in bc.items()}


# --- Betweenness cache -----------------------------------------------------
# Betweenness is the ONLY expensive step in this module: O(V*E), ~42s on a
# 5 000-page vault, versus 0.13s to parse it and 0.03s for communities. So it
# is the only thing worth caching.
#
# The cache key is a hash of the GRAPH ITSELF, not file mtimes. That makes a
# stale hit impossible by construction: if any link changed, the key changes;
# if only prose changed, the old (still-correct) result is reused. No
# invalidation logic to get wrong.

CACHE_FILENAME = ".graph-cache.json"
_CACHE_MAX_ENTRIES = 3
#: Don't write a cache file for graphs that recompute faster than this — small
#: vaults should not accumulate cache files for no gain.
_CACHE_MIN_SECONDS = 0.5


def graph_fingerprint(outgoing: dict[str, list[str]]) -> str:
    """Stable hash of the undirected graph topology (nodes + edges)."""
    adj = _undirected_adj(outgoing)
    h = hashlib.sha256()
    for node in sorted(adj):
        h.update(node.encode("utf-8"))
        h.update(b"\x00")
        for nb in sorted(adj[node]):
            h.update(nb.encode("utf-8"))
            h.update(b"\x01")
        h.update(b"\x02")
    return h.hexdigest()[:32]


def _cache_path(vault: Path) -> Path:
    return vault / CACHE_FILENAME


def _read_cache(vault: Path) -> dict:
    """Read the cache, failing open (a corrupt or unreadable cache is ignored)."""
    try:
        data = json.loads(_cache_path(vault).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("version") == 1 else {}


def _write_cache(vault: Path, data: dict) -> None:
    """Atomically replace the cache file. Never raises — caching is best-effort."""
    target = _cache_path(vault)
    tmp = target.with_suffix(f".tmp{os.getpid()}")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, target)   # atomic; concurrent writers can't tear the file
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def betweenness_cached(
    outgoing: dict[str, list[str]],
    vault: Path | None = None,
    normalized: bool = True,
) -> dict[str, float]:
    """`betweenness_centrality`, memoised on disk under `vault` by graph topology.

    Falls back to a plain in-process computation when `vault` is None or the
    cache is unusable — the result is always identical either way.
    """
    if vault is None:
        return betweenness_centrality(outgoing, normalized=normalized)

    key = f"{graph_fingerprint(outgoing)}:{int(normalized)}"
    cache = _read_cache(vault)
    hit = cache.get("betweenness", {}).get(key)
    if isinstance(hit, dict) and hit.keys() >= outgoing.keys():
        return {n: float(hit[n]) for n in outgoing}

    started = time.monotonic()
    scores = betweenness_centrality(outgoing, normalized=normalized)
    elapsed = time.monotonic() - started

    if elapsed >= _CACHE_MIN_SECONDS:
        entries = cache.get("betweenness", {})
        if not isinstance(entries, dict):
            entries = {}
        entries[key] = {n: round(v, 10) for n, v in scores.items()}
        # Keep the cache bounded — most recent keys win.
        for old in list(entries)[:-_CACHE_MAX_ENTRIES]:
            entries.pop(old, None)
        _write_cache(vault, {"version": 1, "betweenness": entries})
    return scores


def bridge_pages(
    outgoing: dict[str, list[str]],
    communities: list[set[str]],
    top_n: int = 10,
    vault: Path | None = None,
) -> list[dict]:
    """Pages with the highest betweenness — removing them fragments the graph.

    Each entry lists which communities the page's neighbours belong to, so the
    caller can say "`P` bridges cluster A ↔ cluster B".
    """
    bc = betweenness_cached(outgoing, vault)
    if not bc:
        return []
    adj = _undirected_adj(outgoing)
    node_comm = _node_community_map(communities)
    ranked = sorted((n for n, s in bc.items() if s > 0), key=lambda n: -bc[n])[:top_n]
    out = []
    for n in ranked:
        own = node_comm.get(n)
        others = sorted({node_comm[nb] for nb in adj[n] if nb in node_comm and node_comm[nb] != own})
        out.append({
            "page": n,
            "betweenness": round(bc[n], 4),
            "community": own,
            "connects": others,
        })
    return out


# ---------------------------------------------------------------------------
# Surprising connections
# ---------------------------------------------------------------------------

def surprising_connections(
    outgoing: dict[str, list[str]],
    communities: list[set[str]],
    top_n: int = 20,
) -> list[dict]:
    """Edges that cross community boundaries, ranked by unexpectedness.

    Score = 1 / sqrt(cross_degree(source) * cross_degree(target))
    Low cross-degree nodes connected across communities are the most surprising.

    Results are ordered so that each (community A, community B) boundary is
    represented once before any boundary repeats — graphify's dedup, which
    stops one high-betweenness hub from filling every slot.
    """
    node_comm = _node_community_map(communities)

    # Count how many cross-community edges each node already has
    cross_deg: dict[str, int] = defaultdict(int)
    for src, targets in outgoing.items():
        for t in targets:
            if node_comm.get(src) != node_comm.get(t):
                cross_deg[src] += 1
                cross_deg[t] += 1

    results = []
    seen: set[tuple[str, str]] = set()
    for src, targets in outgoing.items():
        for t in targets:
            pair = tuple(sorted((src, t)))
            if pair in seen:
                continue
            if node_comm.get(src) != node_comm.get(t):
                cd_s = cross_deg.get(src, 1)
                cd_t = cross_deg.get(t, 1)
                score = 1.0 / math.sqrt(cd_s * cd_t)
                cs, ct = node_comm.get(src), node_comm.get(t)
                results.append({
                    "source": src, "target": t, "score": round(score, 4),
                    "note": f"bridges community {cs} -> community {ct}",
                    "_pair": (min(cs, ct), max(cs, ct)) if cs is not None and ct is not None else None,
                })
                seen.add(pair)

    results.sort(key=lambda x: -x["score"])
    # One representative per community pair first, then the rest by score.
    seen_pairs: set = set()
    first: list[dict] = []
    rest: list[dict] = []
    for r in results:
        pair = r.pop("_pair")
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            first.append(r)
        else:
            rest.append(r)
    return (first + rest)[:top_n]


# ---------------------------------------------------------------------------
# Path finding & neighbourhoods (graphify: `path`, `affected` blast radius)
# ---------------------------------------------------------------------------

def shortest_path(
    outgoing: dict[str, list[str]],
    source: str,
    target: str,
    directed: bool = False,
) -> list[str] | None:
    """BFS shortest path between two pages. Follows links in either direction
    unless `directed=True`. Returns the node list, or None if unreachable."""
    source, target = _slug(source), _slug(target)
    if source not in outgoing or target not in outgoing:
        return None
    if source == target:
        return [source]
    if directed:
        adj: dict[str, Any] = {n: set(v) for n, v in outgoing.items()}
    else:
        adj = _undirected_adj(outgoing)
    prev: dict[str, str | None] = {source: None}
    queue = [source]
    qi = 0
    while qi < len(queue):
        v = queue[qi]
        qi += 1
        for w in sorted(adj.get(v, ())):
            if w in prev:
                continue
            prev[w] = v
            if w == target:
                path = [w]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])  # type: ignore[arg-type]
                return path[::-1]
            queue.append(w)
    return None


def neighborhood(
    outgoing: dict[str, list[str]],
    seed: str,
    depth: int = 2,
    direction: str = "both",
) -> list[dict]:
    """Breadth-first neighbourhood of a page up to `depth` hops.

    direction: "out" (pages this one links to), "in" (pages linking here —
    the blast radius if this page is renamed/removed), or "both".
    Returns [{"page", "depth", "via"}] ordered by depth then name.
    """
    seed = _slug(seed)
    if seed not in outgoing:
        return []
    incoming: dict[str, set[str]] = defaultdict(set)
    for s, targets in outgoing.items():
        for t in targets:
            incoming[t].add(s)

    def nbrs(n: str) -> set[str]:
        out: set[str] = set()
        if direction in ("out", "both"):
            out |= set(outgoing.get(n, ()))
        if direction in ("in", "both"):
            out |= incoming.get(n, set())
        out.discard(n)
        return out

    seen = {seed: 0}
    via = {seed: None}
    frontier = [seed]
    for d in range(1, depth + 1):
        nxt = []
        for v in frontier:
            for w in sorted(nbrs(v)):
                if w not in seen:
                    seen[w] = d
                    via[w] = v
                    nxt.append(w)
        frontier = nxt
        if not frontier:
            break
    return [
        {"page": n, "depth": d, "via": via[n]}
        for n, d in sorted(seen.items(), key=lambda kv: (kv[1], kv[0]))
        if n != seed
    ]


# ---------------------------------------------------------------------------
# Graph diff (graphify: analyze.graph_diff)
# ---------------------------------------------------------------------------

_SNAPSHOT_RE = re.compile(r"<!--\s*GRAPH_SNAPSHOT:\s*(\{.*?\})\s*-->", re.DOTALL)


def snapshot(outgoing: dict[str, list[str]]) -> dict[str, list]:
    """Compact, JSON-serialisable snapshot for embedding in `_insights.md`."""
    edges = sorted({(s, t) for s, ts in outgoing.items() for t in ts})
    return {"nodes": sorted(outgoing), "edges": [list(e) for e in edges]}


def load_snapshot(path: Path) -> dict[str, list] | None:
    """Read a snapshot from a JSON file or from the `<!-- GRAPH_SNAPSHOT: ... -->`
    comment inside a previous `_insights.md`. Returns None if not found."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _SNAPSHOT_RE.search(text)
    raw = m.group(1) if m else text
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "nodes" not in data:
        return None
    return {"nodes": list(data.get("nodes", [])), "edges": [list(e) for e in data.get("edges", [])]}


def graph_diff(old: dict[str, list], new: dict[str, list]) -> dict[str, Any]:
    """What changed between two snapshots (see `snapshot`)."""
    old_nodes, new_nodes = set(old.get("nodes", [])), set(new.get("nodes", []))
    old_edges = {tuple(e) for e in old.get("edges", [])}
    new_edges = {tuple(e) for e in new.get("edges", [])}

    def in_targets(edges: set) -> set[str]:
        return {t for _, t in edges}

    old_in, new_in = in_targets(old_edges), in_targets(new_edges)
    added_edges = sorted(new_edges - old_edges)
    removed_edges = sorted(old_edges - new_edges)
    return {
        "added_pages": sorted(new_nodes - old_nodes),
        "removed_pages": sorted(old_nodes - new_nodes),
        "added_edges": [list(e) for e in added_edges],
        "removed_edges": [list(e) for e in removed_edges],
        "newly_connected": sorted((new_in - old_in) & old_nodes),
        "lost_incoming": sorted((old_in - new_in) & new_nodes),
        "summary": {
            "pages": len(new_nodes) - len(old_nodes),
            "edges": len(new_edges) - len(old_edges),
        },
    }


# ---------------------------------------------------------------------------
# Suggested questions (graphify: analyze.suggest_questions)
# ---------------------------------------------------------------------------

def suggest_questions(
    outgoing: dict[str, list[str]],
    communities: list[set[str]],
    labels: dict[int, str],
    bridges: list[dict],
    top_n: int = 7,
) -> list[dict]:
    """Questions the graph structure is uniquely positioned to raise.

    Priority: bridge pages → dead-end hubs → isolated pages → low-cohesion
    communities. Each has `type`, `question`, `why`.
    """
    questions: list[dict] = []
    degree, in_deg, out_deg = _build_degree_tables(outgoing)

    # 1. Bridge pages -> cross-cutting questions
    for b in bridges[:3]:
        if not b["connects"]:
            continue
        own = labels.get(b["community"], f"community {b['community']}")
        others = ", ".join(f"`{labels.get(c, f'community {c}')}`" for c in b["connects"])
        questions.append({
            "type": "bridge_node",
            "question": f"Why does `{b['page']}` connect `{own}` to {others}?",
            "why": f"High betweenness ({b['betweenness']}) — this page is a cross-community bridge.",
        })

    # 2. Sink hubs: many incoming, no outgoing
    sinks = sorted(
        (n for n in outgoing if out_deg.get(n, 0) == 0 and in_deg.get(n, 0) >= 3),
        key=lambda n: -in_deg[n],
    )[:2]
    for n in sinks:
        questions.append({
            "type": "sink_hub",
            "question": f"What should `{n}` link out to?",
            "why": f"{in_deg[n]} pages point at it but it links nowhere — a dead end in a busy area.",
        })

    # 3. Isolated / weakly connected pages
    weak = sorted(n for n in outgoing if degree.get(n, 0) <= 1)
    if weak:
        shown = ", ".join(f"`{n}`" for n in weak[:3])
        questions.append({
            "type": "isolated_nodes",
            "question": f"What connects {shown} to the rest of the vault?",
            "why": f"{len(weak)} weakly-connected pages — possible gaps or missing links.",
        })

    # 4. Low-cohesion communities
    for i, comm in enumerate(communities):
        if len(comm) >= 5:
            c = cohesion_score(outgoing, comm)
            if c < 0.15:
                questions.append({
                    "type": "low_cohesion",
                    "question": f"Should `{labels.get(i, f'community {i}')}` be split into more focused topics?",
                    "why": f"Cohesion {c} across {len(comm)} pages — they share a cluster but are weakly interlinked.",
                })

    if not questions:
        return [{
            "type": "no_signal",
            "question": None,
            "why": "Not enough structure to raise questions — no bridges, sink hubs, isolates or fragmented clusters.",
        }]
    return questions[:top_n]


# ---------------------------------------------------------------------------
# Community labelling (heuristic: most common tag or longest shared prefix)
# ---------------------------------------------------------------------------

def _label_community(
    pages: list[str],
    tags_map: dict[str, list[str]],
    taken: set[str] | None = None,
) -> str:
    """Most common tag; if that label is already `taken` by a bigger community,
    qualify it with the next most common tag (`ai-security/roadmap`) or a
    top page name so every community label is unique."""
    freq: dict[str, int] = defaultdict(int)
    for p in pages:
        for tag in tags_map.get(p, []):
            if not tag.startswith("visibility/"):
                freq[tag] += 1
    if freq:
        ranked = sorted(freq, key=lambda t: (-freq[t], t))
        label = ranked[0]
        if taken is not None and label in taken:
            for alt in ranked[1:]:
                cand = f"{label}/{alt}"
                if cand not in taken:
                    return cand
            return f"{label}/{pages[0]}"
        return label
    # Fallback: shared prefix of page names
    if len(pages) == 1:
        return pages[0]
    prefix = pages[0]
    for p in pages[1:]:
        while not p.startswith(prefix):
            prefix = prefix[:-1]
        if not prefix:
            break
    return prefix.rstrip("-_") or f"cluster-{pages[0][:20]}"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyse_vault(
    vault: Path,
    top_n: int = 20,
    previous_snapshot: dict[str, list] | None = None,
    include_snapshot: bool = False,
) -> dict[str, Any]:
    outgoing, tags_map = parse_vault_graph(vault)

    if not outgoing:
        return {
            "god_nodes": [], "bridges": [], "communities": [],
            "surprising_connections": [], "suggested_questions": [],
            "dead_ends": [], "isolated": [],
            "stats": {"pages": 0, "edges": 0, "communities": 0, "density": 0.0},
        }

    communities_raw = detect_communities(outgoing)
    # Sort communities largest-first
    communities_raw.sort(key=lambda c: -len(c))
    labels: dict[int, str] = {}
    taken: set[str] = set()
    for i, c in enumerate(communities_raw):
        lbl = _label_community(sorted(c), tags_map, taken)
        labels[i] = lbl
        taken.add(lbl)

    total_edges = sum(len(v) for v in outgoing.values())
    n_pages = len(outgoing)
    undirected_edges = sum(len(v) for v in _undirected_adj(outgoing).values()) // 2
    density = undirected_edges / (n_pages * (n_pages - 1) / 2) if n_pages > 1 else 0.0

    bridges = bridge_pages(outgoing, communities_raw, top_n=min(top_n, 10), vault=vault)

    result: dict[str, Any] = {
        "god_nodes": god_nodes(outgoing, top_n),
        "bridges": bridges,
        "communities": [
            {
                "id": i,
                "size": len(comm),
                "pages": sorted(comm),
                "label": labels[i],
                "cohesion": cohesion_score(outgoing, comm),
            }
            for i, comm in enumerate(communities_raw)
        ],
        "surprising_connections": surprising_connections(outgoing, communities_raw, top_n),
        "suggested_questions": suggest_questions(outgoing, communities_raw, labels, bridges),
        "dead_ends": dead_ends(outgoing),
        "isolated": isolated(outgoing),
        "stats": {
            "pages": n_pages,
            "edges": total_edges,
            "communities": len(communities_raw),
            "density": round(density, 4),
        },
    }
    if previous_snapshot is not None:
        result["diff"] = graph_diff(previous_snapshot, snapshot(outgoing))
    if include_snapshot:
        result["snapshot"] = snapshot(outgoing)
    return result
