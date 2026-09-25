"""Ledger invert and snapshot-path compare for lint (ADR 0001)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from obsidian_wiki.cache import _is_file_key, _iter_entries
from obsidian_wiki.vault import split_frontmatter

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


def _archived_dir(vault: Path) -> Path:
    return vault / "_raw" / "_archived"


def clip_url_index(vault: Path) -> dict[str, list[str]]:
    """Map clip YAML url -> archived relative paths (may be 0, 1, or many)."""
    index: dict[str, list[str]] = defaultdict(list)
    root = _archived_dir(vault)
    if not root.is_dir():
        return {}
    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        frontmatter = split_frontmatter(text)[0]
        rel = path.relative_to(vault).as_posix()
        for line in frontmatter.splitlines():
            if ":" not in line or line.startswith((" ", "\t")):
                continue
            key, raw = line.split(":", 1)
            if key.strip() not in _URL_FIELDS:
                continue
            url = raw.strip().strip("'\"")
            if url:
                index[url].append(rel)
            break  # first matching URL field wins per file
    return dict(index)


def resolve_source_key(
    vault: Path,
    key: str,
    *,
    url_index: dict[str, list[str]] | None = None,
) -> str | None:
    """Return a vault-relative archived path, or None if not a unique snapshot file."""
    if key.startswith("url:"):
        url = key[4:]
        index = url_index if url_index is not None else clip_url_index(vault)
        matches = index.get(url) or []
        if len(matches) == 1:
            return matches[0]
        return None
    if not _is_file_key(key):
        return None
    candidate = Path(key)
    archived_rel = Path("_raw") / "_archived" / candidate.name
    archived_abs = vault / archived_rel
    if archived_abs.is_file():
        return archived_rel.as_posix()
    if (vault / candidate).is_file() and "_archived" in candidate.parts:
        return candidate.as_posix()
    return None
