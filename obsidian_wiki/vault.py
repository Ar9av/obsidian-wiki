"""Shared vault primitives: frontmatter splitting, skip dirs, and the page walker.

Every module that reads pages out of a vault goes through these, so a vault
parses and walks the same way no matter which command touches it (#238).
Modules layer their own extra skip dirs / reserved files on top.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Iterable

#: Staging, archive, and tool-owned directories that never hold knowledge pages.
#: Dot-prefixed paths (`.venv`, `.git`, `.obsidian`) are skipped wholesale by
#: `iter_md`; this list adds the non-hidden equivalents.
SKIP_DIRS = frozenset({
    "_raw", "_archived", "_staging", "_archives",
    ".obsidian", ".git", "venv", "node_modules", "__pycache__",
})

#: CRLF-tolerant so a vault edited on Windows parses the same as one from Unix.
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)
# A bare `>`, `>-`, `>+`, `|`, `|-`, `|+` (optionally followed by an indent
# indicator digit) marks a YAML block scalar — the real value lives on the
# following indented lines, not on this line.
BLOCK_SCALAR_RE = re.compile(r"^[>|][+-]?\d*$")


def split_frontmatter(text: str) -> tuple[str, str]:
    """(frontmatter, body); frontmatter is "" when the page has none."""
    match = FRONTMATTER_RE.match(text)
    return (match.group(1), text[match.end():]) if match else ("", text)


def okignore_patterns(vault: Path) -> list[str]:
    """Patterns from the vault-root `.okignore` (gitignore syntax, subset)."""
    try:
        lines = (vault / ".okignore").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    # ponytail: no `!` negation or `**`-specific semantics; add if a vault needs them.
    return [
        line.strip().rstrip("/") for line in lines
        if line.strip() and not line.strip().startswith(("#", "!"))
    ]


def okignored(rel: Path, patterns: list[str]) -> bool:
    """True if vault-relative `rel` is excluded by any `.okignore` pattern.

    A pattern without a slash matches any path component (`_inbox`, `*.draft.md`);
    one with a slash is anchored to the vault root and matches that path or
    anything beneath it (`/drafts`, `notes/old`).
    """
    parts = rel.parts
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    for pattern in patterns:
        if "/" in pattern:
            anchored = pattern.lstrip("/")
            if any(fnmatch.fnmatchcase(prefix, anchored) for prefix in prefixes):
                return True
        elif any(fnmatch.fnmatchcase(part, pattern) for part in parts):
            return True
    return False


#: Instructions for coding agents, not knowledge, wherever they sit: a vault
#: built from per-project sub-wikis carries one per project. A `README.md` is
#: only excluded at the vault root, where it describes the vault itself.
AGENT_INSTRUCTION_FILES = frozenset({"AGENTS.md", "CLAUDE.md", "GEMINI.md"})


def is_instruction_file(rel: Path) -> bool:
    """True if vault-relative `rel` is an agent-instruction file, not a page."""
    return rel.name in AGENT_INSTRUCTION_FILES or (len(rel.parts) == 1 and rel.name == "README.md")


def skipped_dir(rel: Path, skip_dirs: Iterable[str] = SKIP_DIRS) -> bool:
    """True if any component of vault-relative `rel` is hidden or in `skip_dirs`."""
    return any(part in skip_dirs or part.startswith(".") for part in rel.parts)


def _walk_md(vault: Path) -> Iterable[Path]:
    """Every `.md` under `vault`, descending into symlinked directories.

    Obsidian follows a symlinked folder as part of the vault, but `Path.rglob`
    does not descend into one before Python 3.13, so a vault that mounts its
    project folders by symlink looked empty and `memory index` dropped their
    entries. A directory whose real path was already visited is pruned, which
    breaks symlink loops.
    """
    seen: set[str] = set()
    for root, dirs, files in os.walk(vault, followlinks=True):
        real = os.path.realpath(root)
        if real in seen:
            dirs[:] = []
            continue
        seen.add(real)
        for name in files:
            if name.endswith(".md"):
                yield Path(root) / name


def iter_instruction_files(vault: Path, skip_dirs: Iterable[str] = SKIP_DIRS) -> list[Path]:
    """The agent-instruction files `iter_md` leaves out. Not pages, but real
    files a `[[CLAUDE]]` link opens, so link checks must still find them."""
    return sorted(
        path for path in _walk_md(vault)
        if is_instruction_file(path.relative_to(vault))
        and not skipped_dir(path.relative_to(vault), skip_dirs)
    )


def iter_md(vault: Path, skip_dirs: Iterable[str] = SKIP_DIRS) -> list[Path]:
    """Every `.md` page under `vault`, sorted, minus hidden/skipped dirs,
    agent-instruction files, and `.okignore`."""
    patterns = okignore_patterns(vault)
    return sorted(
        path for path in _walk_md(vault)
        if not skipped_dir(path.relative_to(vault), skip_dirs)
        and not is_instruction_file(path.relative_to(vault))
        and not okignored(path.relative_to(vault), patterns)
    )
