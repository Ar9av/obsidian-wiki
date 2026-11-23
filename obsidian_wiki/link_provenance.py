"""Per-link provenance: is a wikilink something a source says, or something inferred?

Pages mark claims with a trailing `^[inferred]` or `^[ambiguous]` (llm-wiki,
Provenance Markers). A link is the claim it sits in, so it takes the nearest
marker at or after it within the same paragraph or list item; with no marker it is
`extracted`. No new syntax and no schema change — existing pages already carry this.

ponytail: paragraph-granular. A marker is read as covering the links before it in
its block, so an unmarked link earlier in a marked paragraph reads as inferred.
Split the paragraph, or put the link in its own bullet, to be precise.
"""

from __future__ import annotations

import re
from pathlib import Path

from obsidian_wiki.graph_analysis import _MD_LINK_RE, _WIKILINK_RE, iter_pages
from obsidian_wiki.links import PageIndex, strip_code
from obsidian_wiki.provenance import archive_wikilink_relpath
from obsidian_wiki.vault import split_frontmatter

STATES = ("extracted", "inferred", "ambiguous")
_MARKER_RE = re.compile(r"\^\[(inferred|ambiguous)\]")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _blocks(body: str) -> list[str]:
    """Paragraphs, with each list item its own block."""
    blocks: list[list[str]] = [[]]
    for line in body.splitlines():
        if not line.strip():
            blocks.append([])
        elif _LIST_ITEM_RE.match(line):
            blocks.append([line])
        else:
            blocks[-1].append(line)
    return ["\n".join(b) for b in blocks if b]


def classify_links(block: str) -> list[tuple[str, str]]:
    """(raw link target, state) for every link in one block."""
    out = []
    for match in sorted([*_WIKILINK_RE.finditer(block), *_MD_LINK_RE.finditer(block)], key=lambda m: m.start()):
        marker = _MARKER_RE.search(block, match.end())
        out.append((match.group(1), marker.group(1) if marker else "extracted"))
    return out


def link_provenance(vault: Path) -> list[dict[str, str]]:
    """One row per (from, to) page link: `{"from", "to", "state"}`.

    A link written several times keeps its best-supported state (extracted beats
    inferred beats ambiguous), since one plain statement is enough to stand on.
    """
    pages = iter_pages(vault)
    rels = {page: page.relative_to(vault).as_posix() for page in pages}
    index = PageIndex(rels.values())
    best: dict[tuple[str, str], str] = {}
    for page in pages:
        src = index.id_for(rels[page])
        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for block in _blocks(strip_code(split_frontmatter(text)[1])):
            for raw, state in classify_links(block):
                if archive_wikilink_relpath(vault, raw) is not None:
                    continue
                target = index.resolve(raw, rels[page])
                if not target or target == src:
                    continue
                key = (src, target)
                if key not in best or STATES.index(state) < STATES.index(best[key]):
                    best[key] = state
    return [{"from": s, "to": t, "state": st} for (s, t), st in sorted(best.items())]


def summarize(rows: list[dict[str, str]], state: str | None = None) -> dict:
    counts = {s: sum(r["state"] == s for r in rows) for s in STATES}
    links = [r for r in rows if state in (None, "all", r["state"])]
    return {"counts": counts, "state": state or "all", "links": links}
