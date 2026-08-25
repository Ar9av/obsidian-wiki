"""Batch planner for parallel wiki-ingest subagent dispatch.

When ingesting a large folder of docs, this module splits the source list into
batches and emits a dispatch plan the skill uses to spawn parallel Claude
subagents — each handling one batch independently, then merging results.

The agent calls `obsidian-wiki batch-plan <vault> <source-dir> [options]`
and gets back a JSON plan:

{
  "batches": [
    {
      "id": 0,
      "files": ["path/to/a.md", "path/to/b.pdf"],
      "total_bytes": 45000,
      "kinds": {"markdown": 1, "pdf": 1}
    },
    ...
  ],
  "stats": {
    "total_files": N,
    "total_bytes": N,
    "batch_count": N,
    "skipped_unchanged": N,
    "skipped_binary": N
  },
  "merge_hint": "Run /wiki-ingest on each batch in parallel, then run /cross-linker once all batches are done."
}

The skill dispatches each batch as a parallel subagent call, then runs
cross-linker once all agents report completion.
"""

from __future__ import annotations

import mimetypes
import os
import subprocess
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

# Ingestible text/doc extensions
TEXT_EXTENSIONS = frozenset(
    ".md .mdx .txt .rst .html .htm .csv .tsv .json .jsonl .yaml .yml .xml".split()
)
PDF_EXTENSIONS = frozenset(".pdf".split())
IMAGE_EXTENSIONS = frozenset(".png .jpg .jpeg .webp .gif .bmp .tiff .svg".split())
OFFICE_EXTENSIONS = frozenset(".docx .xlsx .pptx .odt .ods .odp".split())
CODE_EXTENSIONS = frozenset(
    ".py .ts .js .jsx .tsx .go .rs .java .kt .rb .c .cpp .h .hpp .swift .sh".split()
)

# Binary / generated — skip entirely
SKIP_EXTENSIONS = frozenset(
    ".pyc .pyo .pyd .so .dylib .dll .exe .class .jar .war .egg "
    ".zip .tar .gz .bz2 .whl .lock .mp4 .mov .mp3 .wav .ttf .woff .eot".split()
)

SKIP_DIRS = frozenset(
    "node_modules .git __pycache__ .pytest_cache dist build target "
    ".venv venv env .mypy_cache .ruff_cache coverage .tox .obsidian "
    "_raw _archived _staging _archives".split()
)


def _classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in OFFICE_EXTENSIONS:
        return "office"
    if ext in CODE_EXTENSIONS:
        return "code"
    if ext in SKIP_EXTENSIONS:
        return "skip"
    # Guess via mime
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime.startswith("text/"):
        return "text"
    return "skip"


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _git_tracked_files(source_dir: Path) -> list[Path] | None:
    """Return repo-relative-to-source_dir file paths via `git ls-files`, or
    None if source_dir isn't a usable git working tree (no `.git`, `git`
    missing, not a repo, etc).

    Uses `--cached --others --exclude-standard` so both committed files and
    new-but-not-yet-committed files are picked up, while anything the repo's
    own `.gitignore` excludes (node_modules, build output, venvs, secrets,
    ...) is skipped automatically — no hardcoded SKIP_DIRS guesswork needed.
    """
    if not (source_dir / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(source_dir), "ls-files", "-z",
             "--cached", "--others", "--exclude-standard"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.decode("utf-8", errors="replace")
    return [source_dir / rel for rel in raw.split("\0") if rel]


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------

def discover_sources(
    source_dir: Path,
    *,
    vault: Path | None = None,
    include_code: bool = False,
) -> list[dict]:
    """Return a list of ingestible file dicts under source_dir.

    Each dict: {path, kind, size_bytes}. Code files are excluded by default
    because wiki-ingest Step 1c handles them via ast-extract separately.

    If source_dir is the root of a git working tree, files are enumerated
    with `git ls-files` so the repo's own `.gitignore` rules apply (this
    correctly skips whatever a project actually ignores, not just the
    common-case SKIP_DIRS list below). Otherwise falls back to a plain
    directory walk.
    """
    tracked = _git_tracked_files(source_dir)
    if tracked is not None:
        candidates = sorted(tracked)
    else:
        candidates = []
        for dirpath, dirnames, filenames in os.walk(source_dir):
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
            ]
            for fn in sorted(filenames):
                candidates.append(Path(dirpath) / fn)

    files = []
    for p in candidates:
        kind = _classify(p)
        if kind == "skip":
            continue
        if kind == "code" and not include_code:
            continue
        files.append({"path": str(p), "kind": kind, "size_bytes": _file_size(p)})
    return files


# ---------------------------------------------------------------------------
# Manifest filtering (skip unchanged sources)
# ---------------------------------------------------------------------------

def _filter_unchanged(
    files: list[dict],
    vault: Path,
) -> tuple[list[dict], int]:
    """Remove files whose hash matches the manifest. Returns (to_ingest, skipped_count)."""
    try:
        from obsidian_wiki.cache import check_sources, compute_hash
        paths = [Path(f["path"]) for f in files]
        result = check_sources(vault, paths)
        unchanged_set = set(result["unchanged"])
        to_ingest = [f for f in files if f["path"] not in unchanged_set]
        return to_ingest, len(unchanged_set)
    except Exception:
        return files, 0


# ---------------------------------------------------------------------------
# Batch splitting
# ---------------------------------------------------------------------------

def _make_batches(
    files: list[dict],
    *,
    max_batch_bytes: int,
    max_batch_files: int,
) -> list[list[dict]]:
    """Split files into batches respecting size and file-count limits."""
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_bytes = 0

    for f in files:
        sz = f["size_bytes"]
        if current and (
            current_bytes + sz > max_batch_bytes
            or len(current) >= max_batch_files
        ):
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(f)
        current_bytes += sz

    if current:
        batches.append(current)
    return batches


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def plan_batches(
    source_dir: Path,
    vault: Path,
    *,
    max_batch_mb: float = 2.0,
    max_batch_files: int = 20,
    skip_unchanged: bool = True,
    include_code: bool = False,
) -> dict[str, Any]:
    """Discover sources, filter unchanged, and split into batches."""
    all_files = discover_sources(source_dir, vault=vault, include_code=include_code)

    skipped_binary = 0  # files already excluded by _classify
    skipped_unchanged = 0

    to_ingest = all_files
    if skip_unchanged and vault.is_dir():
        to_ingest, skipped_unchanged = _filter_unchanged(all_files, vault)

    max_batch_bytes = int(max_batch_mb * 1024 * 1024)
    batches_raw = _make_batches(
        to_ingest,
        max_batch_bytes=max_batch_bytes,
        max_batch_files=max_batch_files,
    )

    total_bytes = sum(f["size_bytes"] for f in to_ingest)

    batches_out = []
    for i, batch in enumerate(batches_raw):
        kinds: dict[str, int] = {}
        for f in batch:
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
        batches_out.append({
            "id": i,
            "files": [f["path"] for f in batch],
            "total_bytes": sum(f["size_bytes"] for f in batch),
            "kinds": kinds,
        })

    merge_hint = (
        "Dispatch each batch as a parallel subagent with /wiki-ingest on its file list. "
        "Each subagent must record its sources with `obsidian-wiki cache-update` (it takes "
        "the manifest lock); hand-editing .manifest.json in parallel batches loses entries. "
        "Once all batches complete, run /cross-linker to wire up cross-references."
    )

    return {
        "batches": batches_out,
        "stats": {
            "total_files": len(all_files),
            "to_ingest": len(to_ingest),
            "total_bytes": total_bytes,
            "batch_count": len(batches_out),
            "skipped_unchanged": skipped_unchanged,
            "skipped_binary": skipped_binary,
        },
        "merge_hint": merge_hint,
    }
