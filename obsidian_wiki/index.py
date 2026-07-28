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


def _category_key(raw: str) -> str:
    normalized = raw.strip().lower()
    return _CATEGORY_ALIASES.get(normalized, normalized)


def _collect_pages(
    vault: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, set[str]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    labels: dict[str, set[str]] = defaultdict(set)
    for path in sorted(vault.rglob("*.md")):
        rel = path.relative_to(vault)
        if any(part in SKIP_DIRS for part in rel.parts) or rel.name in SPECIAL_FILES:
            continue
        page = _parse_page(path, vault)
        raw_category = page["category"] or (
            rel.parts[0] if len(rel.parts) > 1 else "uncategorized"
        )
        key = _category_key(raw_category)
        groups[key].append(page)
        labels[key].add(raw_category)
    return groups, labels


def _render_link(page: dict[str, Any], link_format: str) -> str:
    path = Path(page["path"])
    target = path.with_suffix("").as_posix()
    title = page["title"]
    if link_format == "markdown":
        return f"[{title}]({path.as_posix()})"
    if link_format != "wikilink":
        raise ValueError(f"unsupported link format: {link_format}")
    if title != path.stem:
        return f"[[{target}|{title}]]"
    return f"[[{target}]]"


def _entry(page: dict[str, Any], link_format: str) -> str:
    entry = f"- {_render_link(page, link_format)}"
    if page["summary"]:
        entry += f" — {page['summary']}"
    if page["tag_list"]:
        entry += " ( " + " ".join(f"#{tag}" for tag in page["tag_list"]) + ")"
    return entry


def _render(
    groups: dict[str, list[dict[str, Any]]],
    labels: dict[str, set[str]],
    link_format: str,
) -> str:
    lines = list(_HEADER_LINES)
    ordered = [category for category in _CATEGORY_ORDER if category in groups]
    ordered.extend(sorted(category for category in groups if category not in _CATEGORY_ORDER))
    for category in ordered:
        heading = (
            category.title()
            if category in _CATEGORY_ORDER
            else min(labels[category], key=lambda label: (label.casefold(), label))
        )
        lines.extend(("", f"## {heading}"))
        for page in sorted(
            groups[category],
            key=lambda item: (item["path"].casefold(), item["path"]),
        ):
            lines.append(_entry(page, link_format))
    return "\n".join(lines) + "\n"


def build_index(vault: Path, *, link_format: str = "wikilink") -> str:
    """Return the deterministic ``index.md`` content for *vault*."""
    groups, labels = _collect_pages(vault)
    return _render(groups, labels, link_format)


def rebuild_index(
    vault: Path,
    *,
    check: bool = False,
    link_format: str = "wikilink",
) -> dict[str, Any]:
    """Regenerate ``index.md`` (or, with *check*, report whether it matches)."""
    groups, labels = _collect_pages(vault)
    generated = _render(groups, labels, link_format)
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
