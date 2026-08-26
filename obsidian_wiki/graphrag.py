"""GraphRAG query index for wiki-query.

Builds a compact in-memory index from vault page frontmatter and wikilinks,
then answers structural and factual queries against it without opening any
page bodies. Equivalent to graphify's "query the compiled graph instead of
raw files" — saves reading 10–50 pages for questions answerable from the
graph structure.

The agent calls:
  obsidian-wiki graph-query <vault> "<question>" [options]

And gets back a JSON response:
{
  "answer_type": "direct" | "path" | "list" | "gap",
  "candidates": [{"page": "...", "score": 0.N, "summary": "..."}, ...],
  "path": ["page-a", "page-b", "page-c"],   # multi-hop, if applicable
  "god_nodes_relevant": ["page", ...],        # hub pages related to query terms
  "should_read": ["page-a.md", "page-b.md"], # pages worth opening for full detail
  "index_only": true/false                    # true = answer is complete without page reads
}

The `should_read` list is the key output: it tells the agent exactly which pages
to open, replacing the current approach of opening 10+ pages speculatively.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------

_FRONT_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_TAGS_RE = re.compile(r"^tags:\s*\[([^\]]+)\]", re.MULTILINE)
_TAGS_LIST_RE = re.compile(r"^tags:\s*\n((?:\s+-\s+\S+\n)+)", re.MULTILINE)
_CATEGORY_RE = re.compile(r"^category:\s*(\w+)", re.MULTILINE)
_TIER_RE = re.compile(r"^tier:\s*(\w+)", re.MULTILINE)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")
_MD_LINK_RE = re.compile(r"\[.*?\]\(([^)]+\.md[^)]*)\)")

# A bare `>`, `>-`, `>+`, `|`, `|-`, `|+` (optionally followed by an indent
# indicator digit) marks a YAML block scalar — the real value lives on the
# following indented lines, not on this line.
_BLOCK_SCALAR_RE = re.compile(r"^[>|][+-]?\d*$")

from obsidian_wiki.graph_analysis import (  # noqa: E402
    SKIP_DIRS,
    SKIP_ROOT_FILES,
    _slug,
    iter_pages,
    shortest_path,
)

__all__ = ["SKIP_DIRS", "SKIP_ROOT_FILES", "build_index", "classify_query",
           "find_path", "query", "rank_candidates"]


def _extract_scalar(front: str, key: str) -> str:
    """Extract a YAML scalar frontmatter value, folding block scalars (>, |).

    Handles both `key: value` and the block-scalar form:
        key: >-
          wrapped
          text
    where the real value lives on subsequent indented lines, not on the
    `key:` line itself (see issue #156 — a naive same-line regex captures
    the `>-` indicator instead of the text).
    """
    lines = front.splitlines()
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.*)$")
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        rest = m.group(1).strip()
        if not rest or _BLOCK_SCALAR_RE.match(rest):
            block_lines = []
            for cont in lines[i + 1:]:
                if cont.strip() == "":
                    continue
                if re.match(r"^\s+\S", cont):
                    block_lines.append(cont.strip())
                else:
                    break
            return " ".join(block_lines).strip()
        return rest.strip("\"'")
    return ""


def build_index(vault: Path) -> dict[str, dict]:
    """Build a lightweight index dict from vault frontmatter and wikilinks.

    Returns:
        {slug: {title, tags, summary, category, tier, out_links, in_links, path}}
    """
    pages: dict[str, dict] = {}

    # Shared page selection — identical to graph_analysis, so `graph-query`
    # and `graph-analyse` always see the same graph. Notably this drops the
    # root index/log/hot bookkeeping files: index.md links to every page, so
    # including it made almost any two pages look 2 hops apart and produced
    # meaningless "A -> index -> B" paths.
    md_files = iter_pages(vault)

    # First pass: collect all slugs and frontmatter
    for page in md_files:
        slug = _slug(page.stem)
        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        front_m = _FRONT_RE.match(text)
        front = front_m.group(1) if front_m else ""

        title = _extract_scalar(front, "title")

        tags: list[str] = []
        m = _TAGS_RE.search(front)
        if m:
            tags = [t.strip().strip("'\"") for t in m.group(1).split(",")]
        else:
            m2 = _TAGS_LIST_RE.search(front)
            if m2:
                tags = [ln.strip().lstrip("- ") for ln in m2.group(1).splitlines() if ln.strip()]

        summary = _extract_scalar(front, "summary")

        category = str(page.relative_to(vault).parent)
        m = _CATEGORY_RE.search(front)
        if m:
            category = m.group(1).strip()

        tier = "supporting"
        m = _TIER_RE.search(front)
        if m:
            tier = m.group(1).strip()

        pages[slug] = {
            "title": title or page.stem,
            "tags": tags,
            "summary": summary,
            "category": category,
            "tier": tier,
            "path": str(page.relative_to(vault)),
            "out_links": [],
            "in_links": [],
        }

    # Second pass: extract wikilinks
    known = set(pages.keys())
    for page in md_files:
        slug = _slug(page.stem)
        if slug not in pages:
            continue
        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for link in _WIKILINK_RE.findall(text):
            target = _slug(link.split("/")[-1])
            if target and target != slug and target in known:
                pages[slug]["out_links"].append(target)
                pages[target]["in_links"].append(slug)

        for href in _MD_LINK_RE.findall(text):
            target = _slug(Path(href).stem)
            if target and target != slug and target in known:
                pages[slug]["out_links"].append(target)
                pages[target]["in_links"].append(slug)

    return pages


# ---------------------------------------------------------------------------
# Scoring / ranking
# ---------------------------------------------------------------------------

_TIER_WEIGHT = {"core": 1.3, "supporting": 1.0, "peripheral": 0.7}


def _score(slug: str, entry: dict, terms: list[str]) -> float:
    score = 0.0
    title_lower = entry["title"].lower()
    summary_lower = entry["summary"].lower()
    tags_lower = [t.lower() for t in entry["tags"]]
    for term in terms:
        t = term.lower()
        # Prefix word-boundary match: `\b{t}` rather than a bare substring, so
        # a short function word ("ich", "den") can't hit inside an unrelated
        # longer word ("tatsächlich", "Herausfinden"). Prefix (not `\bt\b`) is
        # kept so inflected/plural forms ("Tags" vs "tag") still match.
        pattern = re.compile(rf"\b{re.escape(t)}")
        if t == slug or t == title_lower:
            score += 10.0
        elif pattern.search(title_lower):
            score += 6.0
        elif any(pattern.search(tag) for tag in tags_lower):
            score += 4.0
        elif pattern.search(summary_lower):
            score += 2.0

    if score > 0:
        # Degree bonus only when at least one term matched — prevents degree
        # noise from surfacing irrelevant pages
        degree = len(entry["in_links"]) + len(entry["out_links"])
        score += min(degree * 0.1, 2.0)
        score *= _TIER_WEIGHT.get(entry.get("tier", "supporting"), 1.0)
    return score


def rank_candidates(
    index: dict[str, dict],
    terms: list[str],
    top_n: int = 8,
) -> list[dict]:
    scored = [
        {
            "slug": slug,
            "page": entry["path"],
            "title": entry["title"],
            "score": _score(slug, entry, terms),
            "summary": entry["summary"],
            "tier": entry["tier"],
            "in_degree": len(entry["in_links"]),
        }
        for slug, entry in index.items()
    ]
    scored.sort(key=lambda x: (-x["score"], -x["in_degree"]))
    return [c for c in scored[:top_n] if c["score"] > 0]


# ---------------------------------------------------------------------------
# Multi-hop path finding (BFS)
# ---------------------------------------------------------------------------

def find_path(
    index: dict[str, dict],
    source_slug: str,
    target_slug: str,
    max_depth: int = 4,
) -> list[str] | None:
    """Shortest wikilink path from source to target (undirected).

    Delegates to `graph_analysis.shortest_path` so there is exactly one BFS
    implementation in the codebase; `max_depth` bounds the result length.
    """
    if source_slug not in index or target_slug not in index:
        return None
    outgoing = {slug: list(entry["out_links"]) for slug, entry in index.items()}
    path = shortest_path(outgoing, source_slug, target_slug)
    if path is None or len(path) - 1 > max_depth:
        return None
    return path


# ---------------------------------------------------------------------------
# Query classification
# ---------------------------------------------------------------------------

_PATH_PATTERNS = re.compile(
    r"how (?:is|are|does) (.+?) (?:connected|related|linked) to (.+?)[\?]?$"
    r"|trace (?:the )?(?:chain|path) from (.+?) to (.+?)[\?]?$"
    r"|what connects (.+?) (?:to|and) (.+?)[\?]?$",
    re.IGNORECASE,
)

_GAP_PATTERNS = re.compile(
    r"what (?:do|don'?t) I (?:not )?know about|what.?s missing|what gaps|open questions",
    re.IGNORECASE,
)

_LIST_PATTERNS = re.compile(
    r"(?:list|show|find|give me) (?:all|every|pages about)",
    re.IGNORECASE,
)

# --- Structural intents ----------------------------------------------------
# Questions about the SHAPE of the vault. Each maps to one graph algorithm.
# Only `bridges` needs betweenness (the one expensive metric), so the rest
# stay as cheap as an ordinary lookup.

#: "what breaks if I delete X" / "what depends on X" -> incoming blast radius
_IMPACT_PATTERNS = re.compile(
    r"what (?:would )?breaks?(?: if I (?:delete|remove|rename))?\s+(.+?)[\?]?$"
    r"|what (?:pages? )?(?:depends?|relies) on\s+(.+?)[\?]?$"
    r"|(?:the )?blast radius (?:of|for)\s+(.+?)[\?]?$"
    r"|what (?:links|points) to\s+(.+?)[\?]?$"
    r"|what(?:'s| is) affected by\s+(.+?)[\?]?$",
    re.IGNORECASE,
)

#: highest betweenness — the pages holding the graph together
_BRIDGE_PATTERNS = re.compile(
    r"bridge pages?|which pages? bridge|what bridges"
    r"|would (?:fragment|split|disconnect)|load.bearing|cross.commun\w+|cut vertex|articulation",
    re.IGNORECASE,
)

#: highest degree — the anchor concepts
_HUB_PATTERNS = re.compile(
    r"what(?:'s| is) central|most connected|most.linked|top hubs?|hub pages?"
    r"|god nodes?|anchor pages?|most important pages?|what are my (?:main|core) (?:topics|concepts)",
    re.IGNORECASE,
)

#: community detection + cohesion
_CLUSTER_PATTERNS = re.compile(
    r"what clusters|what communit\w+|how is my (?:vault|wiki) (?:organi[sz]ed|structured)"
    r"|cluster cohesion|fragmented (?:clusters?|topics?)|vault structure",
    re.IGNORECASE,
)

#: cross-community edges ranked by unexpectedness
_SURPRISE_PATTERNS = re.compile(
    r"surprising connections?|unexpected (?:links?|connections?)|non.obvious (?:links?|connections?)",
    re.IGNORECASE,
)

_STRUCTURAL = (
    ("impact", _IMPACT_PATTERNS),
    ("bridges", _BRIDGE_PATTERNS),
    ("hubs", _HUB_PATTERNS),
    ("clusters", _CLUSTER_PATTERNS),
    ("surprising", _SURPRISE_PATTERNS),
)


# Trailing punctuation to strip off extracted terms. A question mark left on a
# token means it can never match a title, tag or summary.
_TERM_PUNCT = "?,.'\""

# Function words dropped from the "direct" fallback query terms. English is the
# primary vault language, but German/French/Spanish words are common enough in
# mixed-language questions that leaving them in feeds noise straight into
# `_score()` (a short function word can prefix-match inside an unrelated
# longer word). Not exhaustive — vault-language-aware stop words are future
# work — just enough to cover the common short pronouns/articles/prepositions.
_STOP_WORDS = {
    "what", "the", "a", "an", "is", "are", "how", "does", "do", "in", "of",
    "to", "for", "and", "or",
    # German
    "was", "wie", "ich", "der", "die", "das", "den", "dem", "des", "ein",
    "eine", "einer", "einem", "einen", "ist", "sind", "über", "und", "oder",
    "für", "auf", "mit", "im",
    # French
    "que", "qui", "quoi", "comment", "le", "la", "les", "un", "une", "des",
    "est", "sont", "sur", "pour", "et", "ou", "dans",
    # Spanish
    "qué", "que", "cómo", "el", "la", "los", "las", "un", "una", "es", "son",
    "para", "por", "en", "sobre",
}


def _split_terms(text: str) -> list[str]:
    """Split on whitespace, strip surrounding punctuation, drop empties."""
    return [t for t in (w.strip(_TERM_PUNCT) for w in text.split()) if t]


def classify_query(question: str) -> tuple[str, list[str]]:
    """Return (answer_type, extracted_terms).

    answer_type: "path" | "impact" | "bridges" | "hubs" | "clusters"
                 | "surprising" | "gap" | "list" | "direct"
    """
    m = _PATH_PATTERNS.search(question)
    if m:
        groups = [g for g in m.groups() if g]
        terms = groups[:2] if len(groups) >= 2 else [question]
        return "path", terms

    for name, pattern in _STRUCTURAL:
        sm = pattern.search(question)
        if sm:
            captured = [g for g in sm.groups() if g]
            if name == "impact" and not captured:
                continue  # "what breaks" with no subject isn't an impact query
            return name, (captured[:1] if captured else [])

    if _GAP_PATTERNS.search(question):
        # Extract what the gap is about
        terms = _split_terms(re.sub(r"what (?:do|don't) I (?:not )?know about|what.?s missing", "", question, flags=re.IGNORECASE))
        return "gap", terms

    if _LIST_PATTERNS.search(question):
        terms = _split_terms(re.sub(r"(?:list|show|find|give me) (?:all|every|pages about)", "", question, flags=re.IGNORECASE))
        return "list", terms

    # Default: extract meaningful terms (drop stop words)
    terms = [w.strip(_TERM_PUNCT) for w in question.split() if w.lower().strip(_TERM_PUNCT) not in _STOP_WORDS and len(w) > 2]
    return "direct", terms


# ---------------------------------------------------------------------------
# Structural answers (graph shape, not page content)
# ---------------------------------------------------------------------------

def _outgoing_from_index(index: dict[str, dict]) -> dict[str, list[str]]:
    return {slug: list(entry["out_links"]) for slug, entry in index.items()}


def _resolve_page(index: dict[str, dict], term: str) -> str | None:
    """Resolve a free-text page reference to a slug, falling back to ranking."""
    slug = _slug(term)
    if slug in index:
        return slug
    slug = _slug(term.strip().strip("`\"'.,"))
    if slug in index:
        return slug
    cands = rank_candidates(index, [term], top_n=1)
    return cands[0]["slug"] if cands else None


def _structural_answer(
    vault: Path,
    index: dict[str, dict],
    answer_type: str,
    terms: list[str],
    top_n: int,
) -> dict[str, Any] | None:
    """Answer a question about the shape of the graph.

    Returns None when the question named a page that can't be resolved, so the
    caller can fall back to ordinary retrieval.
    """
    from obsidian_wiki import graph_analysis as ga

    outgoing = _outgoing_from_index(index)

    if answer_type == "impact":
        if not terms:
            return None
        seed = _resolve_page(index, terms[0])
        if seed is None:
            return None
        hits = ga.neighborhood(outgoing, seed, depth=2, direction="in")
        direct = [h["page"] for h in hits if h["depth"] == 1]
        return {
            "intent": "impact",
            "seed": seed,
            "direct_dependents": direct,
            "transitive_dependents": [h["page"] for h in hits if h["depth"] == 2],
            "total": len(hits),
            "note": (
                f"{len(direct)} pages link directly to `{seed}`, "
                f"{len(hits)} within 2 incoming hops (excluding `{seed}` itself)."
            ),
        }

    if answer_type == "bridges":
        # The only intent that needs betweenness — cached on disk by topology.
        communities = ga.detect_communities(outgoing)
        communities.sort(key=lambda c: -len(c))
        bridges = ga.bridge_pages(outgoing, communities, top_n=min(top_n, 10), vault=vault)
        labels = _community_labels(index, communities)
        for b in bridges:
            b["label"] = labels.get(b["community"], "")
            b["connects_labels"] = [labels.get(c, str(c)) for c in b["connects"]]
        return {
            "intent": "bridges",
            "bridges": bridges,
            "note": "Ranked by betweenness centrality — removing a high scorer fragments the vault.",
        }

    if answer_type == "hubs":
        gods = ga.god_nodes(outgoing, top_n=min(top_n, 10))
        for g in gods:
            g["title"] = index.get(g["page"], {}).get("title", g["page"])
        return {
            "intent": "hubs",
            "hubs": gods,
            "note": "Ranked by total degree (incoming + outgoing wikilinks).",
        }

    if answer_type == "clusters":
        communities = ga.detect_communities(outgoing)
        communities.sort(key=lambda c: -len(c))
        labels = _community_labels(index, communities)
        out = []
        for i, comm in enumerate(communities):
            cohesion = ga.cohesion_score(outgoing, comm)
            out.append({
                "id": i,
                "label": labels.get(i, f"cluster-{i}"),
                "size": len(comm),
                "cohesion": cohesion,
                "fragmented": bool(cohesion < 0.15 and len(comm) >= 5),
                "pages": sorted(comm)[:12],
            })
        return {
            "intent": "clusters",
            "clusters": out,
            "note": "cohesion = actual links / possible links inside the cluster; < 0.15 with 5+ pages is fragmented.",
        }

    if answer_type == "surprising":
        communities = ga.detect_communities(outgoing)
        communities.sort(key=lambda c: -len(c))
        labels = _community_labels(index, communities)
        items = ga.surprising_connections(outgoing, communities, top_n=min(top_n, 10))
        node_comm = {n: i for i, c in enumerate(communities) for n in c}
        for it in items:
            it["source_cluster"] = labels.get(node_comm.get(it["source"]), "")
            it["target_cluster"] = labels.get(node_comm.get(it["target"]), "")
        return {
            "intent": "surprising",
            "connections": items,
            "note": "Cross-cluster links, rarest first; one per cluster pair before any pair repeats.",
        }

    return None


def _community_labels(index: dict[str, dict], communities: list[set[str]]) -> dict[int, str]:
    """Label each community by its most common tag, kept unique."""
    labels: dict[int, str] = {}
    taken: set[str] = set()
    for i, comm in enumerate(communities):
        freq: dict[str, int] = {}
        for slug in comm:
            for tag in index.get(slug, {}).get("tags", []):
                if not tag.startswith("visibility/"):
                    freq[tag] = freq.get(tag, 0) + 1
        if freq:
            ranked = sorted(freq, key=lambda t: (-freq[t], t))
            label = ranked[0]
            if label in taken:
                label = next(
                    (f"{ranked[0]}/{a}" for a in ranked[1:] if f"{ranked[0]}/{a}" not in taken),
                    f"{ranked[0]}/{sorted(comm)[0]}",
                )
        else:
            label = f"cluster-{i}"
        labels[i] = label
        taken.add(label)
    return labels


# ---------------------------------------------------------------------------
# Main query entry point
# ---------------------------------------------------------------------------

def query(
    vault: Path,
    question: str,
    *,
    top_n: int = 8,
    max_should_read: int = 3,
) -> dict[str, Any]:
    index = build_index(vault)
    if not index:
        return {
            "answer_type": "direct",
            "candidates": [],
            "path": [],
            "god_nodes_relevant": [],
            "should_read": [],
            "index_only": True,
            "note": "Vault appears empty.",
        }

    answer_type, terms = classify_query(question)

    # God nodes relevant to the query
    degree = {s: len(e["in_links"]) + len(e["out_links"]) for s, e in index.items()}
    god_slugs = sorted(degree, key=lambda s: -degree[s])[:10]
    term_set = {t.lower() for t in terms}
    god_relevant = [
        index[s]["path"] for s in god_slugs
        if any(t in index[s]["title"].lower() or t in " ".join(index[s]["tags"]).lower() for t in term_set)
    ][:5]

    path_result: list[str] = []
    if answer_type == "path" and len(terms) >= 2:
        src_slug = _slug(terms[0])
        tgt_slug = _slug(terms[1])
        # Try to find slugs by scoring if exact match fails
        if src_slug not in index:
            cands = rank_candidates(index, [terms[0]], top_n=1)
            src_slug = cands[0]["slug"] if cands else src_slug
        if tgt_slug not in index:
            cands = rank_candidates(index, [terms[1]], top_n=1)
            tgt_slug = cands[0]["slug"] if cands else tgt_slug
        raw_path = find_path(index, src_slug, tgt_slug)
        if raw_path:
            path_result = [index[s]["path"] for s in raw_path if s in index]

    # --- Structural intents ------------------------------------------------
    # Answered entirely from the graph, so `index_only` is true and the agent
    # never opens a page. Everything here is cheap except `bridges`, which
    # needs betweenness and therefore goes through the on-disk cache.
    graph_answer: dict[str, Any] | None = None
    if answer_type in ("impact", "bridges", "hubs", "clusters", "surprising"):
        graph_answer = _structural_answer(vault, index, answer_type, terms, top_n)
        if graph_answer is None:
            answer_type = "direct"   # couldn't resolve the subject — fall back

    candidates = rank_candidates(index, terms, top_n=top_n)

    # Decide whether page reads are needed
    top_candidate = candidates[0] if candidates else None
    index_only = False
    if top_candidate and top_candidate["score"] >= 10.0 and top_candidate["summary"]:
        # A high absolute score alone isn't enough evidence: on a well-linked
        # page even noise terms can clear 10.0 via the degree bonus and tier
        # weight. Require the top candidate to also clearly lead the runner-up
        # — a real topical hit does; noise scores cluster together.
        runner_up = candidates[1]["score"] if len(candidates) > 1 else 0.0
        if runner_up == 0.0 or top_candidate["score"] >= 2 * runner_up:
            index_only = True  # Exact title match with a summary — likely answerable from index
    if graph_answer is not None:
        index_only = True  # structural answers are complete without page reads

    should_read = [c["page"] for c in candidates[:max_should_read] if not index_only]
    if path_result and not index_only:
        # Add path pages to should_read, deduplicated
        for p in path_result:
            if p not in should_read:
                should_read.append(p)
        should_read = should_read[:max_should_read + 2]

    return {
        "answer_type": answer_type,
        "candidates": [
            {
                "page": c["page"],
                "title": c["title"],
                "score": round(c["score"], 2),
                "summary": c["summary"],
                "tier": c["tier"],
            }
            for c in candidates
        ],
        "path": path_result,
        "god_nodes_relevant": god_relevant,
        "should_read": should_read,
        "index_only": index_only,
        "graph": graph_answer,
        "stats": {
            "indexed_pages": len(index),
            "query_terms": terms,
        },
    }
