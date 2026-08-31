#!/usr/bin/env python3
"""Manifest helper for the Obsidian wiki — normalize paths and compute ingest deltas.

Pure stdlib, no dependencies. Optional accelerator for the ingest skills: the
markdown instructions still work without it, but this makes the manifest steps
deterministic and testable.

Source keys in `.manifest.json` are stored in a single canonical form:
**absolute paths with `~` and environment variables expanded.** This prevents
the same file being tracked under both `~/.claude/...` and `/Users/me/.claude/...`,
which otherwise causes silent re-ingestion in append mode (see issues #86/#88).

Usage:
  # Rewrite source keys to canonical absolute paths, merging any collisions.
  python3 scripts/manifest.py normalize <vault_path> [--dry-run]

  # List new/modified sources under a glob that aren't in the manifest yet.
  # Honors $WIKI_SKIP_PROJECTS (comma-separated substrings) plus --skip.
  python3 scripts/manifest.py delta <vault_path> --scan '<glob>' [--skip a,b]
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import os
import sys


def canonical(path: str) -> str:
    """Single canonical key form: expand ~ and env vars, make absolute."""
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def manifest_path(vault: str) -> str:
    return os.path.join(canonical(vault), ".manifest.json")


def load_manifest(vault: str) -> dict:
    mp = manifest_path(vault)
    if not os.path.exists(mp):
        return {"version": 1, "sources": {}, "projects": {}, "stats": {}}
    with open(mp) as f:
        return json.load(f)


def _newest(a: dict, b: dict) -> dict:
    """Merge two entries for the same file, preferring the newer ingested_at and
    unioning the pages_created / pages_updated lists."""
    keep = a
    other = b
    if str(b.get("ingested_at", "")) > str(a.get("ingested_at", "")):
        keep, other = b, a
    merged = dict(keep)
    for field in ("pages_created", "pages_updated"):
        union = list(dict.fromkeys((other.get(field) or []) + (keep.get(field) or [])))
        if union:
            merged[field] = union
    return merged


def cmd_normalize(args: argparse.Namespace) -> int:
    m = load_manifest(args.vault)
    sources = m.get("sources", {})
    new_sources: dict = {}
    collisions = 0
    rekeyed = 0
    for key, entry in sources.items():
        if not os.path.isabs(key):
            # Real vaults store some keys relative to the ingest root (e.g.
            # "-Users-x-github/abc.jsonl" under ~/.claude/projects/). canonical()
            # would resolve those against the CWD and rewrite them to a bogus
            # absolute path. normalize only dedups/canonicalizes absolute keys, so
            # preserve relative keys untouched (safe no-op) and warn.
            print(f"  WARN   preserving relative key as-is (not canonicalized): {key}")
            ckey = key
        else:
            ckey = canonical(key)
            if ckey != key:
                rekeyed += 1
        if ckey in new_sources:
            new_sources[ckey] = _newest(new_sources[ckey], entry)
            collisions += 1
            print(f"  MERGE  {ckey}")
        else:
            new_sources[ckey] = entry

    print(
        f"sources: {len(sources)} -> {len(new_sources)} "
        f"({rekeyed} re-keyed, {collisions} collisions merged)"
    )
    if args.dry_run:
        print("(dry-run — no changes written)")
        return 0
    if collisions == 0 and rekeyed == 0:
        print("already canonical — nothing to write")
        return 0
    m["sources"] = new_sources
    mp = manifest_path(args.vault)
    with open(mp, "w") as f:
        json.dump(m, f, indent=2)
        f.write("\n")
    print(f"wrote {mp}")
    return 0


def _skip_patterns(cli_skip: str | None) -> list[str]:
    pats: list[str] = []
    env = os.environ.get("WIKI_SKIP_PROJECTS", "")
    for raw in (env, cli_skip or ""):
        pats.extend(p.strip() for p in raw.split(",") if p.strip())
    return pats


def _normalize_for_match(path: str) -> str:
    """Normalize either slash style for host-independent path comparison."""
    portable = path.replace("\\", os.sep).replace("/", os.sep)
    return os.path.normcase(os.path.normpath(portable))


def _relative_key_index(sources: dict) -> dict[str, list[tuple[str, dict]]]:
    """Index relative source keys by basename for suffix matching.

    Real vaults store many keys relative to the ingest root (e.g.
    "-Users-x-github/abc.jsonl" under ~/.claude/projects/). canonical()
    resolves those against the CWD, so they never equal a scanned absolute
    path. Keying by basename lets cmd_delta fall back to an O(1) suffix check
    instead of scanning every key per file.
    """
    index: dict[str, list[tuple[str, dict]]] = {}
    for k, v in sources.items():
        if not os.path.isabs(k):
            basename = os.path.basename(_normalize_for_match(k))
            index.setdefault(basename, []).append((k, v))
    return index


def _match_relative(path: str, index: dict[str, list[tuple[str, dict]]]) -> dict | None:
    """Return the manifest entry whose relative key is a suffix of `path`."""
    normalized_path = _normalize_for_match(path)
    basename = os.path.basename(normalized_path)
    for relkey, entry in index.get(basename, ()):
        normalized_relkey = _normalize_for_match(relkey)
        if normalized_path == normalized_relkey or normalized_path.endswith(
            os.sep + normalized_relkey
        ):
            return entry
    return None


def cmd_delta(args: argparse.Namespace) -> int:
    m = load_manifest(args.vault)
    sources = m.get("sources", {})
    known = {canonical(k): v for k, v in sources.items()}
    rel_index = _relative_key_index(sources)
    skips = _skip_patterns(args.skip)

    matched = sorted(globmod.glob(os.path.expanduser(args.scan), recursive=True))
    new, modified, skipped = [], [], 0
    for path in matched:
        if not os.path.isfile(path):
            continue
        if any(s in path for s in skips):
            skipped += 1
            continue
        ckey = canonical(path)
        entry = known.get(ckey)
        if entry is None:
            entry = _match_relative(path, rel_index)
        if entry is None:
            new.append(ckey)
        else:
            mtime = os.path.getmtime(path)
            ingested = str(entry.get("ingested_at", ""))
            # modified if file changed after it was last ingested
            from datetime import datetime, timezone

            try:
                ing_ts = datetime.fromisoformat(ingested.replace("Z", "+00:00")).timestamp()
            except ValueError:
                ing_ts = 0
            if mtime > ing_ts:
                modified.append(ckey)

    if skips:
        print(f"# skip patterns: {', '.join(skips)} ({skipped} files skipped)")
    print(f"# {len(new)} new, {len(modified)} modified, {len(known)} known")
    for p in new:
        print(f"NEW\t{p}")
    for p in modified:
        print(f"MOD\t{p}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    n = sub.add_parser("normalize", help="rewrite source keys to canonical absolute paths")
    n.add_argument("vault", help="path to the Obsidian vault (contains .manifest.json)")
    n.add_argument("--dry-run", action="store_true", help="preview without writing")
    n.set_defaults(func=cmd_normalize)

    d = sub.add_parser("delta", help="list new/modified sources vs the manifest")
    d.add_argument("vault", help="path to the Obsidian vault")
    d.add_argument("--scan", required=True, help="glob of source files (use ** with recursive)")
    d.add_argument("--skip", default=None, help="comma-separated substrings to exclude")
    d.set_defaults(func=cmd_delta)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
