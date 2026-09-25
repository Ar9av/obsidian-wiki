"""Ledger invert and snapshot-path compare for lint (ADR 0001)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from obsidian_wiki.cache import _is_file_key, _iter_entries

_PAGE_LIST_KEYS = ("pages_produced", "pages_created")
_URL_FIELDS = ("url", "source", "source_url")


def unwrap_snapshot_value(raw: str) -> str:
    value = raw.strip().strip("'\"").strip()
    if value.startswith("[[") and "]]" in value:
        inner = value[2 : value.index("]]")]
        inner = inner.split("|", 1)[0].split("#", 1)[0].strip()
        value = inner
    if value and _is_file_key(value) and not value.lower().endswith(".md"):
        value = f"{value}.md"
    return value


def invert_pages(sources: Any) -> dict[str, list[str]]:
    """Map wiki page path -> unique ledger keys, first-seen order."""
    by_page: dict[str, list[str]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    for key, entry in _iter_entries(sources):
        if not key or not isinstance(entry, dict):
            continue
        pages: list[str] = []
        for field in _PAGE_LIST_KEYS:
            raw = entry.get(field) or []
            if isinstance(raw, list):
                pages.extend(str(p) for p in raw if p)
        for page in pages:
            if key in seen[page]:
                continue
            seen[page].add(key)
            by_page[page].append(key)
    return dict(by_page)
