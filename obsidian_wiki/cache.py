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
import sys
import time
from contextlib import contextmanager
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
    missing: list[str]   # vault-local source in manifest but no longer on disk
    unavailable: list[str]  # machine-local source absent here (e.g. synced from another host)


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


def _lock_path(vault: Path) -> Path:
    return vault / ".manifest.lock"


class ManifestLockTimeout(RuntimeError):
    """Raised when the manifest lock could not be acquired within the timeout."""


@contextmanager
def manifest_lock(vault: Path, *, timeout: float = 10.0, stale_after: float = 60.0):
    """Advisory lock around a manifest read-modify-write.

    Parallel ingest agents (``batch-plan`` fan-out) and the Docker server can
    all write one vault's manifest; without this the read-modify-write races
    and a whole entry is silently lost. ``O_CREAT | O_EXCL`` is the portable
    stdlib primitive here — ``fcntl`` is POSIX-only and this ships on Windows.

    A lockfile older than *stale_after* is assumed to belong to a crashed
    process and is stolen.
    """
    # ponytail: whole-manifest advisory lock; per-entry locking if batch fan-out ever contends
    lock = _lock_path(vault)
    deadline = time.monotonic() + timeout
    fd = None
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except FileNotFoundError:
                continue  # holder released it between our open and stat
            if age > stale_after:
                # ponytail: last-writer-wins steal; a pid check would narrow the
                # window if two processes ever race to steal the same stale lock
                try:
                    lock.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise ManifestLockTimeout(
                    f"could not acquire {lock} within {timeout}s "
                    f"(held for {age:.1f}s; stale after {stale_after}s)"
                )
            time.sleep(0.1)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _write_manifest(vault: Path, manifest: dict) -> None:
    """Atomically replace the manifest file — no torn reads, no partial file."""
    target = _manifest_path(vault)
    tmp = target.with_name(f".manifest.json.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(tmp, target)  # atomic on POSIX and Windows
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _save_manifest(vault: Path, sources) -> None:
    """Write *sources* back into the manifest, preserving other top-level keys."""
    with manifest_lock(vault):
        manifest = _load_raw(vault)
        manifest["sources"] = sources
        _write_manifest(vault, manifest)


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

# A Windows drive-absolute path ("C:\dir\file", "C:/dir/file"). On POSIX this is
# not a path at all, so it cannot be resolved and is machine-specific; lint.py
# recognises the same shape when reporting stored keys. Kept local rather than
# imported so the runtime cache carries no dependency on the lint module.
_WINDOWS_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")


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


def _expand_key(key: str) -> str:
    """Expand ``~`` and environment variables, but only when the key uses them.

    A plain vault-relative key like ``Raw/x.pdf`` must survive untouched, so the
    expansion is gated rather than applied unconditionally.
    """
    if key.startswith("~") or "$" in key:
        return os.path.expandvars(os.path.expanduser(key))
    return key


def resolve_key(key: str | None, vault: Path) -> Path | None:
    """Normalize a manifest key to an absolute path, or ``None`` for non-file keys.

    Resolution order (the source key contract v2, see ``llm-wiki/SKILL.md``):

    1. pseudo-key (``scheme:`` / ``://``) -> ``None`` — an opaque identifier, not
       a filesystem location;
    2. ``~``- or env-var-bearing key -> expand;
    3. absolute path -> use as-is (legacy compatibility);
    4. anything else -> resolve against the vault root.
    """
    if not _is_file_key(key):
        return None
    path = Path(_expand_key(key))
    return path if path.is_absolute() else (vault / path)


def stored_key(path: Path, vault: Path) -> str | None:
    """Return the portable manifest key for *path*, or ``None`` if not portable.

    In-vault sources become vault-relative (``Raw/x.pdf``); sources under
    ``$HOME`` become home-relative (``~/.claude/...``); anything else has no
    machine-portable representation and needs an explicit pseudo-key from the
    caller (``repo:``, ``url:``, ``agent:``).
    """
    p = Path(os.path.abspath(_expand_key(str(path))))
    vault_root = Path(os.path.abspath(_expand_key(str(vault))))
    home_root = Path(os.path.expanduser("~"))
    for root, prefix in ((vault_root, ""), (home_root, "~/")):
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if rel == Path("."):
            return None
        return prefix + rel.as_posix()
    return None


def _same_source(stored_key_value: str | None, query: Path, vault: Path) -> bool:
    """True if a manifest key refers to the same source as *query*.

    Matches on the raw string first (covers pseudo-keys), then on the resolved
    absolute form so an absolute query matches a vault-relative or home-relative
    stored key.
    """
    if not stored_key_value:
        return False
    if str(query) == stored_key_value:
        return True
    stored_path = resolve_key(stored_key_value, vault)
    if stored_path is None:
        return False
    try:
        return stored_path.resolve() == query.resolve()
    except OSError:
        return False


def _missing_on_disk(key: str | None, vault: Path) -> bool:
    """True if a filesystem-style manifest key has no file on disk."""
    path = resolve_key(key, vault)
    if path is None:
        return False
    return not path.exists()


def _vault_top_names(vault: Path) -> set[str]:
    """Names of the vault's top-level entries, or an empty set if unreadable."""
    try:
        return {p.name for p in vault.iterdir()}
    except OSError:
        return set()


def _is_vault_local(key: str | None, vault: Path, top_names: set[str] | None = None) -> bool:
    """True if a file key names a source that travels with the vault.

    Vault-local sources travel with the vault, so their absence is a real loss
    (``missing``). A key that is machine-specific *and* points outside this vault
    (``/home/other/wiki/x.md``, ``~/.claude/...``) may simply not exist on the
    machine reading a synced vault, so it is reported under ``unavailable``. An
    absolute or ``~``-relative path that resolves *inside* this vault is still
    vault-local — machine-specific in form, but not in target.

    A *relative* key resolves lexically inside the vault even when it is really
    relative to some other root — the legacy ingest-root keys such as
    ``-Users-x-github/abc.jsonl``. Path shape cannot tell those apart from vault
    keys, so the vault's own topology decides: the first segment must name a real
    top-level entry. That also gives the honest answer for an out-of-vault source
    parked in a namespace the vault does not contain (``external/.hermes/...``):
    unavailable, not missing. When the vault cannot be listed the lexical answer
    stands, so an I/O hiccup never hides a real loss.

    A key written for another OS — a drive-letter path or one using backslashes
    as separators — cannot be resolved on this host, so it is machine-specific
    (``unavailable``) rather than a vault-relative key.
    """
    path = resolve_key(key, vault)
    if path is None:
        return False
    raw = str(key)
    try:
        rel = Path(os.path.abspath(str(path))).relative_to(Path(os.path.abspath(str(vault))))
    except ValueError:
        return False
    if rel == Path("."):
        return False
    if os.name != "nt" and ("\\" in raw or _WINDOWS_ABS_RE.match(raw)):
        # A key written for another OS: a backslash is not a separator here and a
        # drive-letter path cannot be resolved, so this is machine-specific — not
        # a vault source whose file went away.
        return False
    if os.path.isabs(raw) or raw.startswith("~") or "$" in raw:
        return True
    if "/" not in raw and "\\" not in raw:
        # A bare filename at the vault root. There is no leading component that
        # could be a foreign root, so this is a vault source by construction —
        # and if it is gone, that is a real vault-local loss. The backslash guard
        # keeps a Windows-form key out of this shortcut on every platform.
        return True
    if top_names is None:
        top_names = _vault_top_names(vault)
    if not top_names:
        return True
    return rel.parts[0] in top_names


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
    for fp in sorted(path.rglob("*"), key=lambda p: p.relative_to(path).as_posix()):
        if fp.is_file():
            rel = fp.relative_to(path).as_posix()
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
    result: CheckResult = {
        "new": [], "modified": [], "unchanged": [], "missing": [], "unavailable": []
    }

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
    top_names = _vault_top_names(vault)
    for i, (stored_key, _entry) in enumerate(entries):
        if i in matched:
            continue
        if any(_same_source(stored_key, p, vault) for p in source_paths):
            continue
        if _missing_on_disk(stored_key, vault):
            bucket = "missing" if _is_vault_local(stored_key, vault, top_names) else "unavailable"
            result[bucket].append(stored_key)

    return result


def update_source(
    vault: Path,
    source_path: Path,
    *,
    pages_produced: list[str] | None = None,
    key: str | None = None,
) -> str:
    """Record the current hash of *source_path* in the manifest. Returns the hash.

    Edits the manifest in place: matches an existing entry across path forms and
    updates it, otherwise appends a new one — preserving the manifest's shape
    (dict or list), duplicate-path entries, and any skill-written fields.

    The stored key is normalized to the portable form (vault-relative for
    in-vault sources, ``~``-relative under ``$HOME``) so a synced vault never
    accumulates machine absolute paths. Pass *key* explicitly for sources that
    have no filesystem representation in either form — a pseudo-key such as
    ``repo:github.com/owner/name``, ``url:https://...``, or ``agent:claude/<id>``.
    When neither applies, the raw path is kept for backward compatibility and a
    warning is written to stderr, because that entry is not portable across
    machines.
    """
    # Hash outside the lock — hashing a large source tree can take seconds and
    # nothing else in the manifest depends on it.
    current_hash = compute_hash(source_path)
    now = datetime.now(timezone.utc).isoformat()
    explicit_key = key is not None
    if explicit_key:
        new_key = key
    else:
        derived = stored_key(source_path, vault)
        if derived is None:
            new_key = str(source_path)
            print(
                f"warning: {source_path} is outside the vault and $HOME, so it has no "
                f"portable key; storing the absolute path. Pass key=<repo:|url:|agent:> "
                f"to keep the vault portable across machines.",
                file=sys.stderr,
            )
        else:
            new_key = derived

    with manifest_lock(vault):
        return _update_source_locked(
            vault, source_path, new_key, explicit_key, current_hash, now, pages_produced,
        )


def _update_source_locked(
    vault: Path,
    source_path: Path,
    new_key: str,
    explicit_key: bool,
    current_hash: str,
    now: str,
    pages_produced: list[str] | None,
) -> str:
    """The manifest read-modify-write half of :func:`update_source`."""
    manifest = _load_raw(vault)
    sources = manifest.get("sources")

    if isinstance(sources, list):
        target: dict | None = None
        for e in sources:
            if isinstance(e, dict) and _same_source(
                e.get("path") or e.get("source_id"), source_path, vault
            ):
                target = e
                break
        if target is None:
            target = {"path": new_key}
            sources.append(target)
        elif explicit_key and target.get("path") != new_key:
            # An explicit key is authoritative: re-key the matched entry.
            target["path"] = new_key
        target["content_hash"] = _format_hash(target.get("content_hash"), current_hash)
        target["last_ingested"] = now
        if pages_produced is not None:
            target["pages_produced"] = pages_produced
    else:
        if not isinstance(sources, dict):
            sources = {}
        match_key: str | None = None
        for existing_key in sources:
            if _same_source(existing_key, source_path, vault):
                match_key = existing_key
                break
        if match_key is not None and explicit_key and match_key != new_key:
            # Explicit key wins: move the entry rather than updating the legacy
            # key in place, so a skill can record repo:/url: identity for a
            # source the manifest previously tracked by path.
            moved = sources.pop(match_key)
            existing = sources.get(new_key)
            if isinstance(existing, dict):
                moved = {**existing, **moved}
            sources[new_key] = moved
            match_key = new_key
        # A matched legacy entry otherwise keeps its existing key; only new
        # entries use the portable form, so an in-place update never re-keys a
        # dict by surprise (migrate handles legacy conversion).
        manifest_key = match_key if match_key is not None else new_key
        entry = sources.get(manifest_key) if isinstance(sources.get(manifest_key), dict) else {}
        entry["content_hash"] = _format_hash(entry.get("content_hash"), current_hash)
        entry["last_ingested"] = now
        if pages_produced is not None:
            entry["pages_produced"] = pages_produced
        sources[manifest_key] = entry

    manifest["sources"] = sources
    _write_manifest(vault, manifest)
    return current_hash


def hash_file(path: Path) -> str:
    """Just compute and return the hash — no manifest I/O."""
    return compute_hash(path)
