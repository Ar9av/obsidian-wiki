"""Content-hash cache for wiki-ingest source tracking.

Provides a reliable, platform-independent alternative to running `sha256sum`
in the skill. The agent calls `obsidian-wiki cache-check` / `cache-update`
instead of shelling out to sha256sum and manually parsing .manifest.json.

Manifest format (.manifest.json in the vault root). Two `sources` shapes are
supported, because real vaults contain both:

1. Dict keyed by path (this module's original format)::

    {"sources": {"<abs-or-rel-path>": {"content_hash": "...", ...}}}

2. List of entry objects, each carrying its own ``path`` (the shape the
   wiki-ingest skill writes)::

    {"sources": [{"path": "_raw/foo.md", "content_hash": "sha256:...", ...}]}

Both shapes are read transparently, and `update_source` edits the manifest
*in place* — preserving its shape, any duplicate-path entries, and
skill-written fields (``pages_created``, ``size_bytes``, ``source_type``, …).

Hashes are compared prefix-insensitively: the skill records
``"sha256:<hex>"`` while this module computes a bare ``<hex>``, so an optional
``algo:`` prefix is stripped from both sides before comparison.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, TypedDict


class SourceEntry(TypedDict, total=False):
    content_hash: str
    last_ingested: str
    pages_produced: list[str]


class CheckResult(TypedDict):
    new: list[str]
    modified: list[str]
    unchanged: list[str]
    missing: list[str]   # in manifest but file no longer on disk


def _manifest_path(vault: Path) -> Path:
    return vault / ".manifest.json"


def _load_raw(vault: Path) -> dict:
    """Return the full manifest object (``{}`` if absent/unreadable)."""
    mp = _manifest_path(vault)
    if not mp.exists():
        return {}
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _load_manifest(vault: Path):
    """Return the raw ``sources`` value — a dict, a list, or ``{}`` if absent.

    Kept for backward compatibility; callers that need shape-agnostic access
    should use :func:`_iter_entries`.
    """
    return _load_raw(vault).get("sources", {})


def _save_manifest(vault: Path, sources) -> None:
    """Write *sources* back into the manifest, preserving other top-level keys."""
    manifest = _load_raw(vault)
    manifest["sources"] = sources
    _manifest_path(vault).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _iter_entries(sources) -> Iterator[tuple[str | None, dict]]:
    """Yield ``(stored_key, entry)`` pairs for either manifest shape.

    For the dict shape the key is the dict key; for the list shape it is the
    entry's ``path`` (falling back to ``source_id``).
    """
    if isinstance(sources, dict):
        for key, entry in sources.items():
            if isinstance(entry, dict):
                yield key, entry
    elif isinstance(sources, list):
        for entry in sources:
            if isinstance(entry, dict):
                yield (entry.get("path") or entry.get("source_id")), entry


# Matches "sha256:", "https://", "slack:#..." — anything with an algo/scheme
# prefix that shouldn't be treated as a filesystem path.
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:[^\\/]")


def _strip_algo(value: str | None) -> str:
    """Drop an optional ``algo:`` prefix so ``sha256:<hex>`` == ``<hex>``."""
    value = value or ""
    return value.split(":", 1)[1] if ":" in value else value


def _format_hash(existing: str | None, new_hex: str) -> str:
    """Format *new_hex* keeping any ``algo:`` prefix the existing value used."""
    if existing and ":" in existing:
        return f"{existing.split(':', 1)[0]}:{new_hex}"
    return new_hex


def _is_file_key(key: str | None) -> bool:
    """True if *key* looks like a filesystem path rather than a URL/pseudo-key."""
    return bool(key) and "://" not in key and not _SCHEME_RE.match(key)


def _same_source(stored_key: str | None, query: Path, vault: Path) -> bool:
    """True if a manifest key refers to the same source as *query*.

    Matches on the raw string first (covers URLs and pseudo-keys), then on the
    resolved absolute form (relative keys resolve against the vault root), so a
    caller-supplied absolute path matches a manifest's vault-relative key.
    """
    if not stored_key:
        return False
    if str(query) == stored_key:
        return True
    if not _is_file_key(stored_key):
        return False
    k = Path(stored_key)
    k_abs = k if k.is_absolute() else (vault / k)
    try:
        return k_abs.resolve() == query.resolve()
    except OSError:
        return False


def _missing_on_disk(key: str | None, vault: Path) -> bool:
    """True if a filesystem-style manifest key has no file on disk."""
    if not _is_file_key(key):
        return False
    resolved = Path(key) if os.path.isabs(key) else (vault / key)
    return not resolved.exists()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Return the hex SHA-256 digest of *path* without loading it all into RAM."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_dir(path: Path) -> str:
    """Stable SHA-256 over all files in a directory tree (sorted by relative path)."""
    h = hashlib.sha256()
    for fp in sorted(path.rglob("*")):
        if fp.is_file():
            rel = str(fp.relative_to(path))
            h.update(rel.encode())
            h.update(sha256_file(fp).encode())
    return h.hexdigest()


def compute_hash(path: Path) -> str:
    if path.is_dir():
        return sha256_dir(path)
    return sha256_file(path)


def check_sources(vault: Path, source_paths: list[Path]) -> CheckResult:
    """Classify each source as new / modified / unchanged vs. the manifest.

    Also reports manifest entries whose source file no longer exists on disk.
    Handles both manifest shapes and compares hashes prefix-insensitively.
    """
    entries = list(_iter_entries(_load_manifest(vault)))
    result: CheckResult = {"new": [], "modified": [], "unchanged": [], "missing": []}

    matched: set[int] = set()
    for path in source_paths:
        key = str(path)
        if not path.exists():
            result["missing"].append(key)
            continue
        current_hash = _strip_algo(compute_hash(path))
        entry = None
        for i, (stored_key, e) in enumerate(entries):
            if _same_source(stored_key, path, vault):
                entry = e
                matched.add(i)
                break
        if entry is None:
            result["new"].append(key)
        elif _strip_algo(entry.get("content_hash")) != current_hash:
            result["modified"].append(key)
        else:
            result["unchanged"].append(key)

    # Report manifest entries whose source file no longer exists on disk and
    # that weren't among the scanned paths (in any path form).
    for i, (stored_key, _entry) in enumerate(entries):
        if i in matched:
            continue
        if any(_same_source(stored_key, p, vault) for p in source_paths):
            continue
        if _missing_on_disk(stored_key, vault):
            result["missing"].append(stored_key)

    return result


def update_source(
    vault: Path,
    source_path: Path,
    *,
    pages_produced: list[str] | None = None,
) -> str:
    """Record the current hash of *source_path* in the manifest. Returns the hash.

    Edits the manifest in place: matches an existing entry across path forms and
    updates it, otherwise appends a new one — preserving the manifest's shape
    (dict or list), duplicate-path entries, and any skill-written fields.
    """
    manifest = _load_raw(vault)
    sources = manifest.get("sources")
    current_hash = compute_hash(source_path)
    now = datetime.now(timezone.utc).isoformat()

    if isinstance(sources, list):
        target: dict | None = None
        for e in sources:
            if isinstance(e, dict) and _same_source(
                e.get("path") or e.get("source_id"), source_path, vault
            ):
                target = e
                break
        if target is None:
            target = {"path": str(source_path)}
            sources.append(target)
        target["content_hash"] = _format_hash(target.get("content_hash"), current_hash)
        target["last_ingested"] = now
        if pages_produced is not None:
            target["pages_produced"] = pages_produced
    else:
        if not isinstance(sources, dict):
            sources = {}
        match_key: str | None = None
        for stored_key in sources:
            if _same_source(stored_key, source_path, vault):
                match_key = stored_key
                break
        key = match_key if match_key is not None else str(source_path)
        entry = sources.get(key) if isinstance(sources.get(key), dict) else {}
        entry["content_hash"] = _format_hash(entry.get("content_hash"), current_hash)
        entry["last_ingested"] = now
        if pages_produced is not None:
            entry["pages_produced"] = pages_produced
        sources[key] = entry

    manifest["sources"] = sources
    _manifest_path(vault).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return current_hash


def hash_file(path: Path) -> str:
    """Just compute and return the hash — no manifest I/O."""
    return compute_hash(path)
