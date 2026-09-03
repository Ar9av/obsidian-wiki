"""Vault lint checks for wiki structure and metadata hygiene."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Collection
from pathlib import Path
from typing import Any

from obsidian_wiki.graph_analysis import _page_slug as graph_page_slug
from obsidian_wiki.graph_analysis import iter_pages as iter_graph_pages
from obsidian_wiki.trust import (
    ALLOWED_LIFECYCLES,
    TRUST_LEDGER_RELATIVE_PATH,
    check_lifecycle_transitions,
    check_trust_ledger,
    validate_trust_metadata,
)

SKIP_DIRS = frozenset("_raw _archived _staging _archives _bootstrap .obsidian .git".split())
REQUIRED_FRONTMATTER = (
    "title",
    "category",
    "tags",
    "sources",
    "created",
    "updated",
)
# Introduced by the trust-ledger rollout (#28, #132). Legacy pages that predate
# the schema are missing these by construction; enforcement is staged behind
# lint_vault's strict_trust switch so upgrading obsidian-wiki doesn't fail-close
# every pre-existing page until a vault owner explicitly opts into strict mode
# after a backfill/review pass.
TRUST_REQUIRED_FRONTMATTER = (
    "base_confidence",
    "lifecycle",
)
RESERVED_PAGE_STEMS = frozenset({"index", "log", "hot", "_insights"})
ALLOWED_RELATIONSHIP_TYPES = frozenset(
    {"extends", "implements", "contradicts", "derived_from", "uses", "replaces", "related_to"}
)

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_FIELD_RE = re.compile(r"^([A-Za-z_][\w-]*):", re.MULTILINE)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")
_MD_LINK_RE = re.compile(r"\[.*?\]\(([^)]+\.md[^)]*)\)")
_RELATIONSHIP_LIST_FIELD_RE = re.compile(
    r"^\s*-\s*(type|target):\s*(.*?)\s*$"
)
_RELATIONSHIP_ITEM_START_RE = re.compile(r"^\s*-\s*(?:#.*)?$")
_RELATIONSHIP_FIELD_RE = re.compile(r"^\s+(type|target):\s*(.*?)\s*$")


def _slug(text: str) -> str:
    return text.strip().lower().replace(" ", "-")


def _iter_pages(vault: Path) -> list[Path]:
    return [
        path for path in vault.rglob("*.md")
        if not any(part in SKIP_DIRS for part in path.relative_to(vault).parts)
    ]


def _parse_frontmatter_values(frontmatter: str) -> dict[str, str]:
    values: dict[str, str] = {}
    lines = frontmatter.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line or ":" not in line or line.startswith((" ", "\t")):
            i += 1
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        value = raw.strip()
        if value in {">", ">-", "|", "|-"}:
            block: list[str] = []
            i += 1
            while i < len(lines):
                child = lines[i]
                if child.startswith(" ") or child.startswith("\t"):
                    block.append(child.strip())
                    i += 1
                    continue
                break
            values[key] = " ".join(part for part in block if part).strip()
            continue
        values[key] = value.strip("'\"")
        i += 1
    return values


def _relationship_scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value.split(" #", 1)[0].strip()


def _parse_relationships(frontmatter: str) -> list[dict[str, str]]:
    relationships: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_relationships = False
    for line in frontmatter.splitlines():
        if line.startswith("relationships:") and not line.startswith((" ", "\t")):
            in_relationships = True
            inline = line.split(":", 1)[1].strip()
            if inline in {"[]", "null", "~"}:
                return []
            if inline:
                relationships.append({"parse_error": "inline_relationships_not_supported"})
                return relationships
            continue
        if in_relationships and line and not line.startswith((" ", "\t")):
            break
        if not in_relationships:
            continue
        item_match = _RELATIONSHIP_LIST_FIELD_RE.match(line)
        if item_match:
            if current is not None:
                relationships.append(current)
            current = {item_match.group(1): _relationship_scalar(item_match.group(2))}
            continue
        if _RELATIONSHIP_ITEM_START_RE.match(line):
            if current is not None:
                relationships.append(current)
            current = {}
            continue
        field_match = _RELATIONSHIP_FIELD_RE.match(line)
        if field_match and current is not None:
            key = field_match.group(1)
            if key in current:
                current["parse_error"] = f"duplicate_relationship_{key}"
            else:
                current[key] = _relationship_scalar(field_match.group(2))
            continue
        if line.strip() and not line.lstrip().startswith("#"):
            if current is None:
                current = {"parse_error": "malformed_relationship_entry"}
            else:
                current.setdefault("parse_error", "malformed_relationship_entry")
    if current is not None:
        relationships.append(current)
    return relationships


def _normalise_node_id(raw: str) -> str:
    target = raw.strip().removeprefix("[[").removesuffix("]]")
    target = target.split("|", 1)[0].split("#", 1)[0].strip()
    if target.lower().endswith(".md"):
        target = target[:-3]
    return "/".join(_slug(part) for part in target.strip("/").split("/") if part)


# Extensions Obsidian embeds as attachments. Anything else after a dot is part
# of the page name ("Node.js", "v1.2 release notes"), not a file extension.
_ATTACHMENT_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".avif",
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".webm", ".mov", ".ogv",
    ".pdf", ".canvas", ".base",
})


def _wikilink_page_target(raw: str) -> str | None:
    """Normalise a `_WIKILINK_RE` capture to a page name, or None for an
    attachment embed `by_slug` (`.md`-only) can never hold. Also strips an
    explicit `.md` suffix and a table-escaped pipe's trailing backslash.
    """
    name = raw.rstrip("\\").split("/")[-1]
    suffix = Path(name).suffix.lower()
    if suffix == ".md":
        return name[: -len(suffix)]
    if suffix in _ATTACHMENT_SUFFIXES:
        return None
    return name


def _parse_page(path: Path, vault: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    front_match = _FRONTMATTER_RE.match(text)
    frontmatter = front_match.group(1) if front_match else ""
    fields = set(_FIELD_RE.findall(frontmatter))
    values = _parse_frontmatter_values(frontmatter)
    relative = path.relative_to(vault)

    links: list[str] = []
    for raw in _WIKILINK_RE.findall(text):
        name = _wikilink_page_target(raw)
        target = _slug(name) if name else ""
        if target:
            links.append(target)
    for href in _MD_LINK_RE.findall(text):
        target = _slug(Path(href).stem)
        if target:
            links.append(target)

    return {
        "path": relative.as_posix(),
        "node_id": _normalise_node_id(relative.with_suffix("").as_posix()),
        "slug": _slug(path.stem),
        "title": values.get("title", "").strip() or path.stem,
        "summary": values.get("summary", "").strip(),
        "fields": fields,
        "links": links,
        "relationships": _parse_relationships(frontmatter),
    }


def lint_vault(
    vault: Path,
    *,
    require_trust_ledger: bool = True,
    strict_trust: bool = False,
    allowed_relationship_types: Collection[str] | None = None,
    allowed_lifecycles: Collection[str] | None = None,
    required_trust_fields: Collection[str] | None = None,
    schema_source: str = "framework-defaults",
) -> dict[str, Any]:
    relationship_types = frozenset(
        ALLOWED_RELATIONSHIP_TYPES
        if allowed_relationship_types is None
        else allowed_relationship_types
    )
    lifecycles = frozenset(
        ALLOWED_LIFECYCLES if allowed_lifecycles is None else allowed_lifecycles
    )
    trust_fields = (
        tuple(required_trust_fields)
        if required_trust_fields is not None
        else TRUST_REQUIRED_FRONTMATTER
    )
    pages = [_parse_page(path, vault) for path in _iter_pages(vault)]
    slug_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    node_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        slug_index[page["slug"]].append(page)
        node_index[page["node_id"]].append(page)
    by_slug = {slug: matches[0] for slug, matches in slug_index.items()}
    incoming: dict[str, int] = defaultdict(int)

    broken_links: list[dict[str, str]] = []
    for page in pages:
        for target in page["links"]:
            if target == page["slug"]:
                continue
            if target not in by_slug:
                broken_links.append({"page": page["path"], "target": target})
                continue
            incoming[target] += 1

    missing_frontmatter = []
    confidence_missing_fields = []
    trust_metadata_errors = []
    for page in pages:
        if page["slug"] in RESERVED_PAGE_STEMS:
            continue
        missing = [field for field in REQUIRED_FRONTMATTER if field not in page["fields"]]
        if missing:
            missing_frontmatter.append({"page": page["path"], "missing": missing})
        missing_trust = [field for field in trust_fields if field not in page["fields"]]
        if missing_trust:
            confidence_missing_fields.append({"page": page["path"], "missing": missing_trust})
        try:
            validate_trust_metadata(
                vault / page["path"],
                allowed_lifecycles=lifecycles,
                required_trust_keys=(),
            )
        except ValueError as exc:
            trust_metadata_errors.append({"page": page["path"], "issue": str(exc)})

    # `graph_analysis` identifies a page by its slugged stem (`_page_slug`), so
    # two pages with the same slugged stem are ONE node in the graph metrics:
    # degree, communities, betweenness, and the `neighborhood` blast radius.
    # `Vector Search.md` and `vector-search.md` collide, in one folder or two.
    # Key this check with that module's own slug and page selection, borrowed
    # rather than reimplemented, so the report keys as the merge does.
    stem_index: dict[str, list[str]] = defaultdict(list)
    for graph_page in iter_graph_pages(vault):
        stem_index[graph_page_slug(graph_page, vault)].append(
            graph_page.relative_to(vault).as_posix()
        )
    duplicate_stems = [
        {"stem": stem, "pages": sorted(paths)}
        for stem, paths in sorted(stem_index.items())
        if len(paths) > 1
    ]

    title_index: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        title_index[page["title"].strip().lower()].append(page["path"])
    duplicate_titles = [
        {"title": title, "pages": paths}
        for title, paths in title_index.items()
        if title and len(paths) > 1
    ]
    duplicate_titles.sort(key=lambda item: (item["title"], item["pages"]))

    missing_summaries = [
        page["path"]
        for page in pages
        if page["slug"] not in RESERVED_PAGE_STEMS
        and ("summary" not in page["fields"] or not page["summary"])
    ]

    orphan_pages = []
    for page in pages:
        if page["slug"] in RESERVED_PAGE_STEMS:
            continue
        outgoing = sum(1 for target in page["links"] if target in by_slug and target != page["slug"])
        if outgoing == 0 and incoming.get(page["slug"], 0) == 0:
            orphan_pages.append(page["path"])

    typed_relationship_issues: list[dict[str, Any]] = []
    for page in pages:
        for index, relationship in enumerate(page["relationships"]):
            if "parse_error" in relationship:
                typed_relationship_issues.append(
                    {
                        "page": page["path"],
                        "index": index,
                        "issue": relationship["parse_error"],
                    }
                )
                continue
            relation_type = relationship.get("type", "")
            target_raw = relationship.get("target", "")
            if relation_type not in relationship_types:
                typed_relationship_issues.append(
                    {
                        "page": page["path"],
                        "index": index,
                        "issue": "invalid_type",
                        "type": relation_type,
                    }
                )
                continue
            target = _normalise_node_id(target_raw)
            matches = node_index.get(target, []) if "/" in target else slug_index.get(target, [])
            if len(matches) > 1:
                typed_relationship_issues.append(
                    {
                        "page": page["path"],
                        "index": index,
                        "issue": "ambiguous_target",
                        "target": target,
                    }
                )
                continue
            resolved = matches[0] if matches else None
            if resolved is None:
                typed_relationship_issues.append(
                    {
                        "page": page["path"],
                        "index": index,
                        "issue": "missing_target",
                        "target": target,
                    }
                )
            elif resolved["node_id"] == page["node_id"]:
                typed_relationship_issues.append(
                    {
                        "page": page["path"],
                        "index": index,
                        "issue": "self_reference",
                        "target": target,
                    }
                )

    ledger_path = vault / TRUST_LEDGER_RELATIVE_PATH
    trust_report = (
        check_trust_ledger(
            vault,
            ledger_path,
            allowed_lifecycles=lifecycles,
            required_trust_keys=trust_fields,
            schema_source=schema_source,
        )
        if ledger_path.is_file() or require_trust_ledger
        else None
    )
    illegal_lifecycle_transitions = (
        check_lifecycle_transitions(
            vault,
            ledger_path,
            allowed_lifecycles=lifecycles,
            required_trust_keys=trust_fields,
        )
        if ledger_path.is_file()
        else []
    )

    findings = {
        "broken_links": broken_links,
        "missing_frontmatter": missing_frontmatter,
        "duplicate_titles": duplicate_titles,
        "duplicate_stems": duplicate_stems,
        "missing_summaries": sorted(missing_summaries),
        "orphan_pages": sorted(orphan_pages),
        "typed_relationship_issues": typed_relationship_issues,
        "confidence_missing_fields": confidence_missing_fields,
        "trust_metadata_errors": trust_metadata_errors,
        "confidence_review_stale": trust_report["stale"] if trust_report else [],
        "confidence_unreviewed": trust_report["unreviewed"] if trust_report else [],
        "confidence_mismatches": trust_report["score_mismatches"] if trust_report else [],
        "confidence_ledger_errors": trust_report["errors"] if trust_report else [],
        "illegal_lifecycle_transitions": illegal_lifecycle_transitions,
    }
    counts = {name: len(items) for name, items in findings.items()}

    # Staged migration (#28, #146): a missing trust ledger or trust frontmatter
    # on legacy pages only fails the vault when the owner has explicitly opted
    # into strict_trust. Ledger presence alone never silently enables strict
    # enforcement; core structural findings (broken links, missing core
    # frontmatter) always fail regardless of trust mode.
    trust_finding_names = (
        "confidence_missing_fields",
        "confidence_mismatches",
        "confidence_ledger_errors",
        "confidence_review_stale",
        "confidence_unreviewed",
        "illegal_lifecycle_transitions",
    )
    trust_findings_present = any(counts[name] for name in trust_finding_names)
    trust_fails = strict_trust and any(
        counts[name]
        for name in (
            "confidence_missing_fields",
            "confidence_mismatches",
            "confidence_ledger_errors",
            "confidence_review_stale",
            "illegal_lifecycle_transitions",
        )
    )

    if (
        counts["broken_links"]
        or counts["missing_frontmatter"]
        or counts["trust_metadata_errors"]
        or trust_fails
    ):
        status = "fail"
    elif (
        any(
            counts[name]
            for name in (
                "duplicate_titles",
                "duplicate_stems",
                "missing_summaries",
                "orphan_pages",
                "typed_relationship_issues",
            )
        )
        or trust_findings_present
    ):
        status = "warn"
    else:
        status = "pass"

    return {
        "status": status,
        "schema": {
            "source": schema_source,
            "allowed_lifecycles": sorted(lifecycles),
            "allowed_relationship_types": sorted(relationship_types),
            "required_trust_fields": list(trust_fields),
        },
        "stats": {
            "pages": len(pages),
            "link_count": sum(len(page["links"]) for page in pages),
            "findings": counts,
            "trust": trust_report["counts"] if trust_report else {"ledger": "not_configured"},
        },
        "findings": findings,
    }
