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
from collections import defaultdict, deque
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

SKIP_DIRS = frozenset(
    "_raw _archived _staging _archives .obsidian".split()
)


def _slug(s: str) -> str:
    return s.strip().lower().replace(" ", "-")


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

    md_files = [
        p for p in vault.rglob("*.md")
        if not any(part in SKIP_DIRS for part in p.relative_to(vault).parts)
    ]

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
        if t == slug or t == title_lower:
            score += 10.0
        elif t in title_lower:
            score += 6.0
        elif any(t in tag for tag in tags_lower):
            score += 4.0
        elif t in summary_lower:
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
    """BFS shortest path from source to target through wikilinks."""
    if source_slug not in index or target_slug not in index:
        return None
    if source_slug == target_slug:
        return [source_slug]

    queue: deque[tuple[str, list[str]]] = deque([(source_slug, [source_slug])])
    visited = {source_slug}

    while queue:
        node, path = queue.popleft()
        if len(path) > max_depth:
            continue
        for neighbour in index[node]["out_links"] + index[node]["in_links"]:
            if neighbour in visited:
                continue
            visited.add(neighbour)
            new_path = path + [neighbour]
            if neighbour == target_slug:
                return new_path
            queue.append((neighbour, new_path))
    return None


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


def classify_query(question: str) -> tuple[str, list[str]]:
    """Return (answer_type, extracted_terms).

    answer_type: "path" | "gap" | "list" | "direct"
    """
    m = _PATH_PATTERNS.search(question)
    if m:
        groups = [g for g in m.groups() if g]
        terms = groups[:2] if len(groups) >= 2 else [question]
        return "path", terms

    if _GAP_PATTERNS.search(question):
        # Extract what the gap is about
        terms = re.sub(r"what (?:do|don't) I (?:not )?know about|what.?s missing", "", question, flags=re.IGNORECASE).strip().split()
        return "gap", terms

    if _LIST_PATTERNS.search(question):
        terms = re.sub(r"(?:list|show|find|give me) (?:all|every|pages about)", "", question, flags=re.IGNORECASE).strip().split()
        return "list", terms

    # Default: extract meaningful terms (drop stop words)
    stop = {"what", "the", "a", "an", "is", "are", "how", "does", "do", "in", "of", "to", "for", "and", "or"}
    terms = [w.strip("?,.'\"") for w in question.split() if w.lower().strip("?,.'\"") not in stop and len(w) > 2]
    return "direct", terms


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

    candidates = rank_candidates(index, terms, top_n=top_n)

    # Decide whether page reads are needed
    top_candidate = candidates[0] if candidates else None
    index_only = False
    if top_candidate and top_candidate["score"] >= 10.0 and top_candidate["summary"]:
        index_only = True  # Exact title match with a summary — likely answerable from index

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
        "stats": {
            "indexed_pages": len(index),
            "query_terms": terms,
        },
    }
