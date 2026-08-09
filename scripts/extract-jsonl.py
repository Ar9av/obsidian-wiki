#!/usr/bin/env python3
"""Pre-extract Claude Code conversation JSONL files into compact, signal-only JSON.

Raw JSONL files are 80-90% noise: tool_use blocks, thinking blocks, progress events,
and file-history-snapshots.  This script strips all of that and writes compact
{turns: [{role, text}]} files that the ingest skill can read directly — reducing
token consumption by 5-10x and allowing 5-10x more conversations per run.

Output layout
-------------
  <output_dir>/                           default: ~/.claude/extracted/
    <project-dir-name>/
      <session-uuid>.json                 one per conversation

Extracted file format
---------------------
  {
    "session_id": "uuid",
    "project": "-Users-name-myapp",
    "cwd": "/Users/name/myapp",
    "start_ts": "2026-06-01T10:00:00Z",   first message timestamp
    "end_ts":   "2026-06-01T11:30:00Z",   last message timestamp
    "n_turns": 18,                         user+assistant turns kept
    "n_user_words": 620,
    "turns": [
      {"role": "user",      "text": "..."},
      {"role": "assistant", "text": "..."}
    ]
  }

Usage
-----
  # Full extraction (all projects, all sessions)
  python3 scripts/extract-jsonl.py

  # Incremental — only sessions modified since a date (ISO date or datetime)
  python3 scripts/extract-jsonl.py --since 2026-06-01

  # Skip specific projects (also reads WIKI_SKIP_PROJECTS env var)
  python3 scripts/extract-jsonl.py --skip tsg,autom8

  # Custom paths
  python3 scripts/extract-jsonl.py \\
      --history-path /path/to/.claude \\
      --output-dir   /path/to/extracted

  # Preview what would be extracted without writing
  python3 scripts/extract-jsonl.py --dry-run --verbose

Pure stdlib, no dependencies.
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Truncate very long individual text blocks (assistant text that includes
# e.g. a pasted file read) to keep extracted files reasonable.
MAX_BLOCK_CHARS = 8_000


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def canonical(path: str) -> str:
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def default_history_path() -> str:
    return canonical("~/.claude")


def default_output_dir(history_path: str) -> str:
    return os.path.join(history_path, "extracted")


# ---------------------------------------------------------------------------
# Skip logic
# ---------------------------------------------------------------------------

def skip_patterns(cli_skip: str | None) -> list[str]:
    pats: list[str] = []
    for raw in (os.environ.get("WIKI_SKIP_PROJECTS", ""), cli_skip or ""):
        pats.extend(p.strip() for p in raw.split(",") if p.strip())
    return pats


def is_skipped(path: str, patterns: list[str]) -> bool:
    return any(p in path for p in patterns)


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------

def needs_extraction(
    source_path: str,
    out_path: str,
    since_ts: float | None,
) -> bool:
    """Return True if the source JSONL should be (re)extracted.

    Idempotent staleness check keyed on the output file: (re)extract when the
    output is missing or the source is newer than it, so the extractor does not
    depend on the caller passing the right --since.  --since only narrows the
    scan range; it never suppresses extraction of a file with a fresh output.
    """
    # A missing output is always (re)extracted, regardless of --since.
    if not os.path.exists(out_path):
        return True
    mtime = os.path.getmtime(source_path)
    # --since narrows the scan range: among files that already have an output,
    # skip those not modified since the cutoff.
    if since_ts is not None and mtime < since_ts:
        return False
    # Re-extract if the source changed after the output was last written.
    return mtime > os.path.getmtime(out_path)


# ---------------------------------------------------------------------------
# JSONL parsing — the signal extraction core
# ---------------------------------------------------------------------------

def _text_from_content(content: str | list) -> str:
    """Return plain text from a message content field.

    content is either a bare string (user messages) or a list of typed blocks
    (assistant messages).  We keep only 'text' blocks and skip tool_use,
    thinking, tool_result, image, etc.
    """
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text", "").strip()
            if text:
                parts.append(text[:MAX_BLOCK_CHARS])
    return "\n\n".join(parts)


def extract_conversation(jsonl_path: str) -> dict | None:
    """Parse one JSONL conversation file and return the compact representation.

    Returns None if the file contains no usable turns (e.g. pure tool sessions).
    """
    turns: list[dict] = []
    cwd = ""
    start_ts = ""
    end_ts = ""
    session_id = ""
    ai_title = ""
    git_branch = ""

    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")
                # Skip noise entries immediately
                if entry_type in ("progress", "file-history-snapshot"):
                    continue

                # The rolling auto-generated title is the best summary a session
                # has; it repeats throughout the file, so the last one wins.
                if entry_type == "ai-title":
                    ai_title = entry.get("aiTitle", "") or ai_title
                    continue

                # Subagent traffic and injected context are not the user talking.
                # Counting them as turns inflates n_user_words and pollutes any
                # downstream summary with the agent's own scaffolding.
                if entry.get("isSidechain") or entry.get("isMeta"):
                    continue

                ts = entry.get("timestamp", "")
                if ts and not start_ts:
                    start_ts = ts
                if ts:
                    end_ts = ts

                if not cwd:
                    cwd = entry.get("cwd", "")
                if not session_id:
                    session_id = entry.get("sessionId", "")
                if not git_branch:
                    git_branch = entry.get("gitBranch", "") or ""

                msg = entry.get("message", {})
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role", "")
                if role not in ("user", "assistant"):
                    continue

                text = _text_from_content(msg.get("content", ""))
                if not text:
                    continue

                # Slash commands, caveats, and hook output arrive as user-role
                # strings wrapped in a tag. They are machine boilerplate.
                if role == "user" and text.startswith("<"):
                    continue

                turns.append({"role": role, "text": text})

    except OSError:
        return None

    if not turns:
        return None

    # Derive project dir name from the path
    # e.g. ~/.claude/projects/-Users-name-myapp/uuid.jsonl
    project = os.path.basename(os.path.dirname(jsonl_path))
    if not session_id:
        session_id = os.path.splitext(os.path.basename(jsonl_path))[0]

    n_user_words = sum(
        len(t["text"].split()) for t in turns if t["role"] == "user"
    )

    return {
        "session_id": session_id,
        "project": project,
        "cwd": cwd,
        "git_branch": git_branch,
        "ai_title": ai_title,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "n_turns": len(turns),
        "n_user_words": n_user_words,
        "turns": turns,
    }


# ---------------------------------------------------------------------------
# Main extraction loop
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    history_path = canonical(args.history_path)
    output_dir = canonical(args.output_dir) if args.output_dir else default_output_dir(history_path)
    skips = skip_patterns(args.skip)

    since_ts: float | None = None
    if args.since:
        try:
            dt = datetime.fromisoformat(args.since)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            since_ts = dt.timestamp()
        except ValueError:
            print(f"ERROR: --since value '{args.since}' is not a valid ISO date.", file=sys.stderr)
            return 1

    # Find all conversation JSONL files
    pattern = os.path.join(history_path, "projects", "*", "*.jsonl")
    all_files = sorted(globmod.glob(pattern))

    if not all_files:
        print(f"No JSONL files found under {pattern}")
        return 0

    if not args.dry_run:
        os.makedirs(output_dir, exist_ok=True)

    stats = {"scanned": 0, "skipped_pattern": 0, "skipped_since": 0,
             "skipped_unchanged": 0, "extracted": 0, "empty": 0, "error": 0}

    for source_path in all_files:
        stats["scanned"] += 1

        if is_skipped(source_path, skips):
            stats["skipped_pattern"] += 1
            if args.verbose:
                print(f"  SKIP(pattern)  {source_path}")
            continue

        # Derive the output path from the source path (project dir + file stem)
        # so the staleness check can compare against the actual output file.
        project = os.path.basename(os.path.dirname(source_path))
        session_id = os.path.splitext(os.path.basename(source_path))[0]
        out_path = os.path.join(output_dir, project, session_id + ".json")

        if not needs_extraction(source_path, out_path, since_ts):
            stats["skipped_unchanged"] += 1
            if args.verbose:
                print(f"  SKIP(unchanged) {source_path}")
            continue

        if args.verbose:
            print(f"  EXTRACT  {source_path}")

        result = extract_conversation(source_path)

        if result is None:
            stats["empty"] += 1
            if args.verbose:
                print(f"    -> empty (no usable turns)")
            continue

        project_dir = os.path.join(output_dir, result["project"])
        out_path = os.path.join(project_dir, result["session_id"] + ".json")

        if not args.dry_run:
            os.makedirs(project_dir, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
                f.write("\n")

        stats["extracted"] += 1
        if not args.verbose and stats["extracted"] % 25 == 0:
            print(f"  ... {stats['extracted']} extracted so far")

    # Summary
    print(
        f"\nDone.\n"
        f"  Scanned:          {stats['scanned']}\n"
        f"  Extracted:        {stats['extracted']}\n"
        f"  Empty (no turns): {stats['empty']}\n"
        f"  Skipped (pattern):{stats['skipped_pattern']}\n"
        f"  Skipped (since):  {stats['skipped_since']}\n"
        f"  Skipped (unchanged):{stats['skipped_unchanged']}\n"
        f"  Output dir:       {output_dir if not args.dry_run else '(dry-run, nothing written)'}"
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--history-path",
        default=default_history_path(),
        metavar="PATH",
        help="Root of Claude Code data directory (default: ~/.claude)",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        metavar="PATH",
        help="Where to write extracted files (default: <history-path>/extracted/)",
    )
    p.add_argument(
        "--since",
        default=None,
        metavar="DATE",
        help="Only process sessions modified on or after this ISO date (e.g. 2026-06-01)",
    )
    p.add_argument(
        "--skip",
        default=None,
        metavar="A,B",
        help="Comma-separated project substrings to exclude (also reads WIKI_SKIP_PROJECTS env var)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be extracted without writing anything",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print one line per file",
    )
    args = p.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
