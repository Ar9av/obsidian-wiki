"""Staged-write promotion — the mechanical half of `wiki-stage-commit`.

When ``WIKI_STAGED_WRITES=true``, skills write pages into ``_staging/`` instead of
the live vault, and a human approves them before they land. This module owns the
parts of that workflow that have one correct answer: what is queued, moving a
file to its live path, moving a rejection back to ``_raw/``, and refusing to do
either when the files changed since they were reviewed.

Judgment stays with the skill — whether a page *should* land, how to summarise
it, and how to merge a ``.patch.md`` whose surrounding text has moved on.
Promotion never rewrites a page: it is a rename, so frontmatter, body and links
arrive exactly as they were reviewed.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

STAGING_DIR = "_staging"
RAW_DIR = "_raw"
PATCH_SUFFIX = ".patch.md"


class StagingError(Exception):
    """A staged operation could not be performed."""


class StagingConflict(StagingError):
    """The staged or live file changed since the caller reviewed it.

    Raised instead of overwriting, so a caller can re-read the pair and show the
    reviewer what actually changed. Agents write to the vault while a human is
    still looking at a diff; this is the case that makes promotion unsafe.
    """


def resolve_in_vault(vault: Path, rel: str) -> Path:
    """Resolve a caller-supplied relative path inside *vault*, or refuse.

    The single path check for staged operations. Symlinks are resolved before
    the comparison, so a link inside the vault pointing out of it is caught too.
    """
    root = Path(vault).resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise StagingError(f"path escapes the vault: {rel}")
    return target


def revision(path: Path) -> str | None:
    """Content hash of *path*, or ``None`` when it does not exist.

    ``None`` is meaningful: it is the revision of a live page that does not exist
    yet, so a caller can pin "there was no live page when I reviewed this" and
    have promotion fail if one appeared in the meantime.
    """
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class StagedEntry:
    """One file waiting in ``_staging/``."""

    staged_path: str
    live_path: str
    kind: str  # "new" | "update" | "patch"
    staged_revision: str | None = None
    live_revision: str | None = None
    staged_mtime: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "staged_path": self.staged_path,
            "live_path": self.live_path,
            "kind": self.kind,
            "staged_revision": self.staged_revision,
            "live_revision": self.live_revision,
            "staged_mtime": self.staged_mtime,
        }


def _live_relative(staged_rel: Path) -> str:
    """Map a path under ``_staging/`` to the live path it targets."""
    name = staged_rel.name
    if name.endswith(PATCH_SUFFIX):
        # `concepts/foo.patch.md` describes an edit to `concepts/foo.md`.
        name = name[: -len(PATCH_SUFFIX)] + ".md"
    return str(staged_rel.with_name(name))


def list_staged(vault: Path) -> list[StagedEntry]:
    """Inventory ``_staging/``, newest-staged last, with both revisions pinned."""
    vault = Path(vault)
    root = vault / STAGING_DIR
    if not root.is_dir():
        return []

    entries: list[StagedEntry] = []
    for staged in sorted(root.rglob("*.md")):
        staged_rel = staged.relative_to(root)
        live_rel = _live_relative(staged_rel)
        live = vault / live_rel
        if staged.name.endswith(PATCH_SUFFIX):
            kind = "patch"
        else:
            kind = "update" if live.is_file() else "new"
        stat = staged.stat()
        entries.append(
            StagedEntry(
                staged_path=str(staged.relative_to(vault)),
                live_path=live_rel,
                kind=kind,
                staged_revision=revision(staged),
                live_revision=revision(live),
                staged_mtime=date.fromtimestamp(stat.st_mtime).isoformat(),
            )
        )
    return entries


def _staged_file(vault: Path, rel: str) -> Path:
    """Resolve *rel* to a file under ``_staging/``, accepting either spelling.

    Callers hold either the vault-relative path from `list_staged`
    (``_staging/concepts/a.md``) or the staging-relative one (``concepts/a.md``).
    Both name the same file; accepting one and not the other is a trap.
    """
    rel = rel.replace(os.sep, "/").lstrip("/")
    if not rel:
        raise StagingError("no staged path given")
    candidate = rel if rel.startswith(f"{STAGING_DIR}/") else f"{STAGING_DIR}/{rel}"
    staged = resolve_in_vault(vault, candidate)
    # Being inside the vault is not enough: `../concepts/a.md` resolves to a live
    # page, which would otherwise be promoted or discarded as if it were staged.
    root = resolve_in_vault(vault, STAGING_DIR)
    if root not in staged.parents:
        raise StagingError(f"path is not under {STAGING_DIR}/: {rel}")
    if not staged.is_file():
        raise StagingError(f"no staged file: {candidate}")
    return staged


def _check_revision(path: Path, expected: str | None, label: str) -> None:
    """Refuse when *path* no longer matches the revision the caller reviewed.

    ``expected`` of ``None`` means the caller did not pin this side and accepts
    whatever is there — distinct from a pinned ``None``, which asserts absence.
    """
    if expected is None:
        return
    actual = revision(path)
    if actual == expected:
        return
    raise StagingConflict(
        f"{label} changed since it was reviewed "
        f"(expected {expected or 'no file'}, found {actual or 'no file'})"
    )


def promote(
    vault: Path,
    rel: str,
    *,
    expected_staged_revision: str | None = None,
    expected_live_revision: str | None = None,
    pin_live_absent: bool = False,
) -> dict[str, Any]:
    """Move one staged page to its live path.

    The move is a rename, so the promoted page is byte-for-byte what was
    reviewed — arbitrary frontmatter, body and wikilinks all survive untouched.

    Pass ``expected_staged_revision`` / ``expected_live_revision`` from the
    listing the reviewer saw to make this fail rather than clobber a concurrent
    write. ``pin_live_absent=True`` asserts there was no live page at review
    time, which a bare ``expected_live_revision=None`` cannot express.

    ``.patch.md`` files are refused: merging a human-readable diff into a page
    whose surrounding text may have moved is judgment, and belongs in the skill.
    """
    vault = Path(vault)
    staged = _staged_file(vault, rel)
    if staged.name.endswith(PATCH_SUFFIX):
        raise StagingError(
            f"{staged.relative_to(vault)} is a patch, not a whole page — "
            "merge it with the wiki-stage-commit skill, then promote the result"
        )

    live_rel = _live_relative(staged.relative_to(vault / STAGING_DIR))
    live = resolve_in_vault(vault, live_rel)

    _check_revision(staged, expected_staged_revision, "staged file")
    if pin_live_absent and live.is_file():
        raise StagingConflict(f"live page {live_rel} was created since it was reviewed")
    _check_revision(live, expected_live_revision, f"live page {live_rel}")

    replaced = live.is_file()
    live.parent.mkdir(parents=True, exist_ok=True)
    # os.replace is atomic within a filesystem: no reader ever sees a partial page.
    os.replace(staged, live)
    _prune_empty_dirs(vault / STAGING_DIR, staged.parent)

    return {
        "action": "promote",
        "staged_path": str(staged.relative_to(vault)),
        "live_path": live_rel,
        "kind": "update" if replaced else "new",
        "revision": revision(live),
    }


def discard(vault: Path, rel: str) -> dict[str, Any]:
    """Move one staged file back to ``_raw/`` for manual editing.

    Named ``rejected-<category>-<page>.md`` so the origin stays readable once the
    directory structure is flattened away.
    """
    vault = Path(vault)
    staged = _staged_file(vault, rel)
    staged_rel = staged.relative_to(vault / STAGING_DIR)

    stem = "-".join(staged_rel.with_suffix("").parts)
    prefix = "rejected-patch-" if staged.name.endswith(PATCH_SUFFIX) else "rejected-"
    if stem.endswith(".patch"):
        stem = stem[: -len(".patch")]
    raw = resolve_in_vault(vault, f"{RAW_DIR}/{prefix}{stem}.md")
    raw.parent.mkdir(parents=True, exist_ok=True)
    # Never silently overwrite an earlier rejection of the same page.
    counter = 2
    while raw.exists():
        raw = raw.with_name(f"{prefix}{stem}-{counter}.md")
        counter += 1

    os.replace(staged, raw)
    _prune_empty_dirs(vault / STAGING_DIR, staged.parent)

    return {
        "action": "discard",
        "staged_path": str(staged.relative_to(vault)),
        "raw_path": str(raw.relative_to(vault)),
    }


def _prune_empty_dirs(root: Path, start: Path) -> None:
    """Remove directories left empty under ``_staging/`` after a move."""
    current = start.resolve()
    root = root.resolve()
    while current != root and root in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def log_decisions(vault: Path, results: list[dict[str, Any]]) -> None:
    """Append one STAGE_COMMIT line to ``log.md``, matching the skill's format."""
    if not results:
        return
    promoted = sum(1 for r in results if r["action"] == "promote")
    discarded = sum(1 for r in results if r["action"] == "discard")
    log = Path(vault) / "log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(
            f"- [{date.today().isoformat()}] STAGE_COMMIT "
            f"accepted={promoted} rejected={discarded}\n"
        )
