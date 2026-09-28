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


def parse_snapshots_field(raw: str) -> list[str]:
    if not raw.strip():
        return []
    lines = raw.splitlines()
    inline = lines[0].strip()
    entries: list[str] = []
    if inline.startswith("["):
        entries.extend(inline.strip("[]").split(","))
    elif inline:
        entries.append(inline)
    entries.extend(
        line.strip()[1:] for line in lines[1:] if line.strip().startswith("-")
    )
    result: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        value = unwrap_snapshot_value(entry)
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def expected_snapshots_for_page(
    vault: Path,
    page: str,
    sources: Any,
    *,
    inverted: dict[str, list[str]] | None = None,
    url_index: dict[str, list[str]] | None = None,
) -> list[str]:
    mapping = inverted if inverted is not None else invert_pages(sources)
    keys = mapping.get(page) or []
    need_urls = any(k.startswith("url:") for k in keys)
    index = url_index
    if index is None and need_urls:
        index = clip_url_index(vault)
    expected: list[str] = []
    seen: set[str] = set()
    for key in keys:
        resolved = resolve_source_key(vault, key, url_index=index)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        expected.append(resolved)
    return expected


def prefer_archive_write_path(vault: Path, rel: str) -> str | None:
    """Vault-relative archive path to store, or None if nothing exists on disk."""
    rel = rel.strip().replace("\\", "/")
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    if "_archived" in candidate.parts:
        if (vault / candidate).is_file():
            return candidate.as_posix()
        return None
    archived_rel = Path("_raw") / "_archived" / candidate.name
    if (vault / archived_rel).is_file():
        return archived_rel.as_posix()
    if (vault / candidate).is_file():
        return candidate.as_posix()
    return None


def archive_wikilink_relpath(_vault: Path, inner: str) -> str | None:
    """Normalise a wikilink inner to `_raw/_archived/…`.md if archive-shaped.

    Does not require the file to exist. Returns None when the inner is not
    under `_raw/_archived/`.
    """
    value = unwrap_snapshot_value(inner)
    if not value:
        return None
    path = Path(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return None
    parts = path.parts
    if len(parts) < 3 or parts[0] != "_raw" or parts[1] != "_archived":
        return None
    return value if value.lower().endswith(".md") else f"{value}.md"
