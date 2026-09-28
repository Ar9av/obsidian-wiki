"""Write YAML snapshots: only (ADR 0003)."""

from __future__ import annotations

import re
from pathlib import Path

from obsidian_wiki.provenance import parse_snapshots_field
from obsidian_wiki.vault import split_frontmatter

_SNAPSHOTS_LINE = re.compile(r"^snapshots\s*:")


def _wikilink_inner(rel: str) -> str:
    rel = rel.strip().replace("\\", "/")
    if rel.lower().endswith(".md"):
        rel = rel[: -len(".md")]
    return rel


def format_snapshots_block(paths: list[str]) -> str:
    lines = ["snapshots:"]
    seen: set[str] = set()
    for raw in paths:
        inner = _wikilink_inner(raw)
        if not inner or inner in seen:
            continue
        seen.add(inner)
        # Quote so YAML does not parse `[[path]]` as a nested flow sequence.
        # Unquoted items render as orange non-links in Obsidian Properties.
        lines.append(f'  - "[[{inner}]]"')
    return "\n".join(lines)


def union_snapshot_paths(existing: list[str], added: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for path in (*existing, *added):
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _snapshots_field_block(frontmatter: str) -> str:
    """Copy of lint._frontmatter_field_block for field 'snapshots' — do not import lint."""
    lines = frontmatter.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^snapshots\s*:(.*)$", line)
        if not match:
            continue
        block = [match.group(1)]
        for following in lines[index + 1 :]:
            if re.match(r"^\s+-\s", following) or not following.strip():
                block.append(following)
                continue
            break
        return "\n".join(block)
    return ""


def read_snapshots(page: Path) -> list[str]:
    frontmatter = split_frontmatter(page.read_text(encoding="utf-8"))[0]
    return parse_snapshots_field(_snapshots_field_block(frontmatter))


def rewrite_page_snapshots(page: Path, paths: list[str]) -> None:
    text = page.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    if not frontmatter and not text.startswith("---"):
        raise ValueError(f"no frontmatter: {page}")
    block = format_snapshots_block(paths)
    lines = frontmatter.splitlines()
    start = None
    end = None
    for index, line in enumerate(lines):
        if _SNAPSHOTS_LINE.match(line):
            start = index
            end = index + 1
            while end < len(lines) and (
                not lines[end].strip() or re.match(r"^\s+-\s", lines[end])
            ):
                end += 1
            break
    if start is None:
        new_fm = "\n".join([*lines, *block.splitlines()])
    else:
        new_fm = "\n".join([*lines[:start], *block.splitlines(), *lines[end:]])
    page.write_text(f"---\n{new_fm.rstrip()}\n---\n{body}", encoding="utf-8")
