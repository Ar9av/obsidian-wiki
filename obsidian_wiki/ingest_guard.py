"""Ingest preflight: one source file gets exactly one primary page (#315).

`report.pdf`, its conversion `report.md`, and the pages `report.md` /
`report.pdf.md` all name the same document, but their stems, titles, and
hashes differ, so `cache-check` and `lint`'s duplicate checks see four
unrelated things. Here each name is reduced to one *identity* (document
extensions stripped, slugged) and every source is matched against the pages
and manifest entries that share it. Read-only: nothing is written.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from obsidian_wiki.cache import _iter_entries, _load_manifest, _is_file_key, stored_key
from obsidian_wiki.graph_analysis import iter_pages
from obsidian_wiki.memory import parse_frontmatter
from obsidian_wiki.vault import split_frontmatter

# Formats a source arrives in or is converted through. Only these are
# stripped, so `notes.v2.md` keeps its `.v2`.
DOC_EXTENSIONS = frozenset({
    ".md", ".markdown", ".txt", ".pdf", ".doc", ".docx", ".odt", ".rtf",
    ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".odp",
    ".html", ".htm", ".epub",
})


def source_identity(name: str) -> str:
    """`Report.pdf.md` -> `report`: the name with document extensions stripped, slugged."""
    stem = re.split(r"[\\/]", name.strip())[-1]
    while True:
        base, dot, ext = stem.rpartition(".")
        if not dot or not base or f".{ext.lower()}" not in DOC_EXTENSIONS:
            break
        stem = base
    return re.sub(r"[\s_]+", "-", stem.strip().lower())


def _page_identities(vault: Path) -> dict[str, list[str]]:
    """identity -> pages whose stem or title reduces to it. Redirect stubs are skipped."""
    index: dict[str, set[str]] = {}
    for page in iter_pages(vault):
        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        values = parse_frontmatter(split_frontmatter(text)[0])
        if str(values.get("redirects_to") or "").strip():
            continue
        rel = page.relative_to(vault).as_posix()
        names = {page.name, str(values.get("title") or "")}
        for identity in {source_identity(name) for name in names if name.strip()}:
            if identity:
                index.setdefault(identity, set()).add(rel)
    return {identity: sorted(pages) for identity, pages in index.items()}


def guard_sources(vault: Path, sources: list[Path]) -> dict[str, Any]:
    """Classify each source as `create`, `update` (one primary page) or `blocked`.

    `blocked` means two or more pages already claim the source's identity:
    writing would add to the duplication, so the caller must resolve it first
    (merge with `wiki-dedup`). `prior_sources` lists manifest keys with the
    same identity, e.g. the `_raw/` conversion an original PDF was ingested
    through, so the caller can see the document was ingested before.
    `siblings` lists the other sources in this call with the same identity
    (`report.pdf` beside `report.docx`): together they make one page.
    """
    pages = _page_identities(vault)
    prior: dict[str, list[str]] = {}
    for key, _entry in _iter_entries(_load_manifest(vault)):
        if key and _is_file_key(key):
            prior.setdefault(source_identity(key), []).append(key)

    own_keys = [stored_key(source, vault) for source in sources]
    keys = [own or str(source) for own, source in zip(own_keys, sources)]
    by_identity: dict[str, list[str]] = {}
    for source, key in zip(sources, keys):
        by_identity.setdefault(source_identity(source.name), []).append(key)

    results = []
    for source, key, own_key in zip(sources, keys, own_keys):
        identity = source_identity(source.name)
        # A source kept in the vault outside `_raw/` is itself a page; it is
        # not a second claim on its own identity.
        candidates = [page for page in pages.get(identity, []) if page != own_key]
        status = "blocked" if len(candidates) > 1 else "update" if candidates else "create"
        results.append({
            "source": key,
            "identity": identity,
            "status": status,
            "pages": candidates,
            "prior_sources": sorted(k for k in prior.get(identity, []) if k != own_key),
            "siblings": sorted(k for k in by_identity[identity] if k != key),
        })
    return {
        "sources": results,
        "blocked": [item["source"] for item in results if item["status"] == "blocked"],
    }
