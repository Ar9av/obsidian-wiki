"""Deterministic ``index.md`` generation from page frontmatter.

Scans the vault's markdown pages, groups them by category, and renders the
master index in the format documented in ``llm-wiki/SKILL.md``. The output
depends only on vault content (stable sort, no timestamps), so ``--check``
can verify the index without writing.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from pathlib import Path
from typing import Any

from obsidian_wiki.lint import SKIP_DIRS as _LINT_SKIP_DIRS
from obsidian_wiki.lint import _parse_page

SKIP_DIRS = _LINT_SKIP_DIRS | frozenset({"_meta", "_readouts"})
SPECIAL_FILES = frozenset({"index.md", "log.md", "hot.md", "_insights.md"})

# Canonical vault categories, in index order; anything else sorts after them.
_CATEGORY_ORDER = ("concepts", "entities", "skills", "references", "synthesis", "journal", "projects")
_CATEGORY_ALIASES = {
    "concept": "concepts",
    "entity": "entities",
    "skill": "skills",
    "reference": "references",
    "project": "projects",
}

_HEADER_LINES = (
    "---",
    "title: Wiki Index",
    "---",
    "",
    "# Wiki Index",
    "",
    "*This index is automatically maintained. Rebuild with `obsidian-wiki index`.*",
)


def _parse_tags(raw: str) -> list[str]:
    """Split an inline frontmatter tag list like ``[ml, architecture]``."""
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    tags: list[str] = []
    for part in raw.split(","):
        tag = part.strip().strip("'\"").lstrip("#")
        if tag:
            tags.append(tag)
    return tags


def _collect_pages(vault: Path) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(vault.rglob("*.md")):
        rel = path.relative_to(vault)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel.name in SPECIAL_FILES:
            continue
        page = _parse_page(path, vault)
        category = page["category"].lower()
        if not category:
            category = rel.parts[0].lower() if len(rel.parts) > 1 else "uncategorized"
        groups[_CATEGORY_ALIASES.get(category, category)].append(page)
    return groups


def _entry(page: dict[str, Any]) -> str:
    entry = f"- [[{Path(page['path']).stem}]]"
    if page["summary"]:
        entry += f" — {page['summary']}"
    tags = _parse_tags(page["tags"])
    if tags:
        entry += " ( " + " ".join(f"#{tag}" for tag in tags) + ")"
    return entry


def _render(groups: dict[str, list[dict[str, Any]]]) -> str:
    lines = list(_HEADER_LINES)
    ordered = [category for category in _CATEGORY_ORDER if category in groups]
    ordered.extend(sorted(category for category in groups if category not in _CATEGORY_ORDER))
    for category in ordered:
        lines.append("")
        lines.append(f"## {category.replace('-', ' ').title()}")
        for page in sorted(groups[category], key=lambda p: (p["slug"], p["path"])):
            lines.append(_entry(page))
    return "\n".join(lines) + "\n"


def build_index(vault: Path) -> str:
    """Return the deterministic ``index.md`` content for *vault*."""
    return _render(_collect_pages(vault))


def rebuild_index(vault: Path, *, check: bool = False) -> dict[str, Any]:
    """Regenerate ``index.md`` (or, with *check*, report whether it matches)."""
    groups = _collect_pages(vault)
    generated = _render(groups)
    index_path = vault / "index.md"
    existing = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    in_sync = existing == generated

    diff: list[str] = []
    if not in_sync:
        diff = list(
            difflib.unified_diff(
                existing.splitlines(),
                generated.splitlines(),
                fromfile="index.md",
                tofile="index.md (generated)",
                lineterm="",
            )
        )

    written = False
    if not check and not in_sync:
        index_path.write_text(generated, encoding="utf-8")
        written = True

    return {
        "in_sync": in_sync,
        "written": written,
        "pages": sum(len(pages) for pages in groups.values()),
        "diff": diff,
    }
