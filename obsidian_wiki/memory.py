"""The vault's memory surface: log, index, hot cache, owner profile, todo index.

Before this module these files were maintained by prose. Fifteen-odd skills each
restated "append a line to ``log.md``, add the new pages to ``index.md``, rewrite
``hot.md``" in their own words, and every one of them rewrote the prose files
wholesale with no lock. Two skills running in parallel silently dropped one of
the two updates, and nothing enforced the documented ~500-word cap on the hot
cache.

Everything here is one code path instead, serialised by the same advisory lock
the manifest writer uses (:func:`obsidian_wiki.cache.advisory_lock`) and written
atomically, so a reader never sees a torn file.

Four artifacts, three of them generated and one hybrid:

``log.md``
    Append-only, one parseable ``- [TS] VERB key=value`` line per operation.
``index.md``
    Category catalog, reconciled against what is actually on disk. A preamble
    and any non-category section are preserved verbatim.
``hot.md``
    Generated session snapshot, word-capped. ``## Key Takeaways`` is the one
    LLM-owned slot and survives every rebuild unless it is explicitly replaced.
``_meta/profile.md`` / ``_meta/todos.md``
    The owner's durable facts and open threads. Markdown tables, so a human can
    edit them in Obsidian and the parser still round-trips them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

from obsidian_wiki.cache import advisory_lock

MEMORY_LOCK_NAME = ".memory.lock"
PROFILE_REL = "_meta/profile.md"
TODOS_REL = "_meta/todos.md"

#: Directories that hold staging, archives, or tool state rather than pages.
SKIP_DIRS = frozenset({
    "_raw", "_staging", "_archives", "_archived", "_readouts", "_meta",
    ".obsidian", ".git", "venv", "node_modules", "__pycache__",
})
#: Root files that are the memory surface itself, not catalog entries.
SKIP_FILES = frozenset({
    "index.md", "log.md", "hot.md", "_insights.md",
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md",
})

#: Canonical ordering for index sections; anything else sorts after, alphabetically.
CATEGORY_ORDER = (
    "concepts", "entities", "skills", "references",
    "synthesis", "journal", "projects",
)

DEFAULT_HOT_MAX_WORDS = 500
DEFAULT_RECENT_ACTIVITY = 3
DEFAULT_ACTIVE_THREADS = 7
DEFAULT_CONTRADICTIONS = 5
DEFAULT_TODO_STALE_DAYS = 30

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)
_LOG_LINE_RE = re.compile(r"^-\s*\[(?P<ts>[^\]]+)\]\s+(?P<verb>[A-Z][A-Z0-9_-]*)\s*(?P<rest>.*)$")
_FIELD_RE = re.compile(r"""(?P<key>[A-Za-z_][\w-]*)=(?P<value>"[^"]*"|'[^']*'|\S*)""")
_VERB_RE = re.compile(r"^[A-Z][A-Z0-9_-]*$")
_TAG_RE = re.compile(r"#[\w/-]+")
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_MD_DECORATION_RE = re.compile(r"[*_`]|^\s*[-*+]\s+|^\s*>\s?|^#{1,6}\s+")
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")
#: Split a table row on unescaped pipes only — `\|` is a literal in a cell.
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")


class MemoryError_(RuntimeError):
    """A memory-surface operation could not be completed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def memory_lock(vault: Path, *, timeout: float = 10.0):
    """Serialise writes to the prose memory files.

    Deliberately one lock for all four artifacts rather than one each: a skill
    that finishes an ingest touches the log, the index, and the hot cache as a
    single logical update, and interleaving another writer between them is what
    produced inconsistent snapshots before.
    """
    return advisory_lock(Path(vault) / MEMORY_LOCK_NAME, timeout=timeout)


def atomic_write(path: Path, text: str) -> None:
    """Replace *path* with *text* via a temp file and ``os.replace``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)  # atomic on POSIX and Windows
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _require_vault(vault: Path) -> Path:
    vault = Path(vault)
    if not vault.is_dir():
        raise MemoryError_("vault_not_found", f"vault not found: {vault}")
    return vault


def _split_frontmatter(text: str) -> tuple[str, str]:
    match = _FRONTMATTER_RE.match(text)
    return (match.group(1), text[match.end():]) if match else ("", text)


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def parse_frontmatter(frontmatter: str) -> dict:
    """Scalars, inline lists, and block lists — enough of YAML for page headers."""
    values: dict = {}
    lines = frontmatter.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.startswith((" ", "\t")) or ":" not in line:
            i += 1
            continue
        key, raw = line.split(":", 1)
        key, raw = key.strip(), raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            values[key] = [_scalar(part) for part in raw[1:-1].split(",") if part.strip()]
            i += 1
            continue
        if not raw:
            block: list = []
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
                stripped = lines[j].strip()
                if stripped.startswith("- "):
                    block.append(stripped[2:].strip())
                elif stripped and block and ":" in stripped:
                    # continuation of a mapping item, e.g. `type: contradicts`
                    block.append(stripped)
                j += 1
            values[key] = block if block else ""
            i = j
            continue
        values[key] = _scalar(raw)
        i += 1
    return values


# --------------------------------------------------------------------------
# log.md
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LogEntry:
    timestamp: str
    verb: str
    fields: dict
    raw: str


def format_log_line(verb: str, fields: Optional[dict] = None, *, timestamp: Optional[str] = None) -> str:
    """Render one ``- [TS] VERB key=value`` line in the documented format."""
    verb = verb.strip().upper()
    if not _VERB_RE.match(verb):
        raise MemoryError_("bad_verb", f"log verb must be UPPERCASE alphanumeric: {verb!r}")
    parts = [f"- [{timestamp or utc_now()}] {verb}"]
    for key, value in (fields or {}).items():
        text = "" if value is None else str(value)
        text = text.replace("\n", " ").replace('"', "'")
        parts.append(f'{key}="{text}"' if (" " in text or not text) else f"{key}={text}")
    return " ".join(parts)


def parse_log_line(line: str) -> Optional[LogEntry]:
    match = _LOG_LINE_RE.match(line.strip())
    if not match:
        return None
    fields = {
        found.group("key"): _scalar(found.group("value"))
        for found in _FIELD_RE.finditer(match.group("rest"))
    }
    return LogEntry(match.group("ts"), match.group("verb"), fields, line.rstrip())


def append_log(
    vault: Path,
    verb: str,
    fields: Optional[dict] = None,
    *,
    timestamp: Optional[str] = None,
    lock: bool = True,
) -> str:
    """Append one operation line to ``log.md``. Returns the line written.

    Append-only and O_APPEND, so this stays correct even for a writer that
    skipped the lock; the lock is still taken by default so a caller doing
    log+index+hot as one update holds it across all three.
    """
    vault = _require_vault(vault)
    line = format_log_line(verb, fields, timestamp=timestamp)
    log = vault / "log.md"

    def _write() -> None:
        if not log.exists():
            atomic_write(log, "---\ntitle: Wiki Log\n---\n\n# Wiki Log\n\n")
        existing = log.read_text(encoding="utf-8")
        prefix = "" if existing.endswith("\n") or not existing else "\n"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"{prefix}{line}\n")

    if lock:
        with memory_lock(vault):
            _write()
    else:
        _write()
    return line


def read_log(vault: Path, *, limit: Optional[int] = None, verbs: Optional[Iterable[str]] = None) -> list:
    """Parsed log entries, newest last. *limit* keeps the newest *limit* entries."""
    log = Path(vault) / "log.md"
    if not log.is_file():
        return []
    wanted = {v.upper() for v in verbs} if verbs else None
    entries = []
    for line in log.read_text(encoding="utf-8").splitlines():
        entry = parse_log_line(line)
        if entry and (wanted is None or entry.verb in wanted):
            entries.append(entry)
    return entries[-limit:] if limit else entries


# --------------------------------------------------------------------------
# page scan
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PageInfo:
    path: str
    category: str
    title: str
    summary: str
    tags: tuple
    updated: str
    lifecycle: str
    contradicts: tuple


def _summary_from_body(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ">", "---", "|", "!", "*[")):
            continue
        if stripped.startswith("*") and stripped.endswith("*") and len(stripped) > 2:
            continue  # the italic "this file is generated" note
        text = _MD_DECORATION_RE.sub("", stripped).strip()
        if text:
            return text[:200]
    return ""


def _contradicts_targets(values: dict) -> tuple:
    """Targets of ``relationships:`` items whose ``type`` is ``contradicts``."""
    raw = values.get("relationships")
    if not isinstance(raw, list):
        return ()
    targets: list = []
    pending_target = None
    pending_type = None
    for item in raw:
        text = item.strip()
        if text.startswith("target:"):
            if pending_target and pending_type == "contradicts":
                targets.append(pending_target)
            pending_target, pending_type = _scalar(text[7:]), None
        elif text.startswith("type:"):
            pending_type = _scalar(text[5:])
            if pending_type == "contradicts" and pending_target:
                targets.append(pending_target)
                pending_target, pending_type = None, None
    if pending_target and pending_type == "contradicts":
        targets.append(pending_target)
    cleaned = []
    for target in targets:
        match = _WIKILINK_RE.search(target)
        cleaned.append(match.group(1).strip() if match else target)
    return tuple(cleaned)


def page_from_path(path: Path, vault: Path) -> PageInfo:
    rel = path.relative_to(vault)
    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = _split_frontmatter(text)
    values = parse_frontmatter(frontmatter)
    tags_raw = values.get("tags", [])
    if isinstance(tags_raw, str):
        tags = tuple(tag.lstrip("#") for tag in _TAG_RE.findall(tags_raw)) or tuple(
            part.strip().lstrip("#") for part in tags_raw.split(",") if part.strip()
        )
    else:
        tags = tuple(str(tag).strip().lstrip("#") for tag in tags_raw if str(tag).strip())
    title = str(values.get("title") or "").strip() or path.stem.replace("-", " ")
    summary = str(values.get("summary") or "").strip() or _summary_from_body(body)
    return PageInfo(
        path=rel.as_posix(),
        category=rel.parts[0] if len(rel.parts) > 1 else "",
        title=title,
        summary=summary,
        tags=tags,
        updated=str(values.get("updated") or "").strip(),
        lifecycle=str(values.get("lifecycle") or "").strip(),
        contradicts=_contradicts_targets(values),
    )


def scan_pages(vault: Path) -> list:
    """Every real wiki page, excluding staging, archives, and the memory files."""
    vault = _require_vault(vault)
    pages = []
    for path in sorted(vault.rglob("*.md")):
        rel = path.relative_to(vault)
        if path.name in SKIP_FILES and len(rel.parts) == 1:
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        try:
            pages.append(page_from_path(path, vault))
        except OSError:
            continue
    return pages


def _category_sort_key(category: str):
    label = category or "uncategorized"
    try:
        return (0, CATEGORY_ORDER.index(label), label)
    except ValueError:
        return (1, 0, label)


def _heading_for(category: str) -> str:
    return (category or "uncategorized").replace("-", " ").replace("_", " ").title()


# --------------------------------------------------------------------------
# index.md
# --------------------------------------------------------------------------


def _index_entry(page: PageInfo, link_format: str) -> str:
    node = page.path[:-3] if page.path.endswith(".md") else page.path
    link = f"[{page.title}]({page.path})" if link_format == "markdown" else f"[[{node}]]"
    # Format rule: a space after the opening paren, or tag parsing breaks.
    tags = f" ( {' '.join('#' + tag for tag in page.tags)})" if page.tags else ""
    summary = f" — {page.summary}" if page.summary else ""
    return f"- {link}{summary}{tags}"


@dataclass(frozen=True)
class IndexResult:
    added: tuple
    removed: tuple
    total: int
    changed: bool
    text: str


def render_index(pages: Sequence, *, link_format: str = "wikilink", preamble: str = "", extra_sections: str = "") -> str:
    by_category: dict = {}
    for page in pages:
        by_category.setdefault(page.category, []).append(page)
    chunks = [preamble.rstrip("\n") if preamble.strip() else "---\ntitle: Wiki Index\n---\n\n# Wiki Index"]
    for category in sorted(by_category, key=_category_sort_key):
        entries = sorted(by_category[category], key=lambda p: (p.title.casefold(), p.path))
        chunks.append(
            f"## {_heading_for(category)}\n\n"
            + "\n".join(_index_entry(page, link_format) for page in entries)
        )
    if not by_category:
        chunks.append("## Concepts\n\n*No pages yet. Use `wiki-ingest` to add your first source.*")
    if extra_sections.strip():
        chunks.append(extra_sections.strip("\n"))
    return "\n\n".join(chunks) + "\n"


def _split_index(text: str) -> tuple:
    """Preamble, category-section paths, and verbatim non-category sections.

    A section is treated as generated when its heading matches a category that
    exists on disk; anything else is a human's own section and is preserved.
    """
    headings = list(_HEADING_RE.finditer(text))
    if not headings:
        return text, {}, ""
    preamble = text[: headings[0].start()].rstrip("\n")
    sections = {}
    for position, match in enumerate(headings):
        end = headings[position + 1].start() if position + 1 < len(headings) else len(text)
        sections[match.group(1).strip().casefold()] = text[match.start(): end]
    return preamble, sections, ""


def rebuild_index(
    vault: Path,
    *,
    link_format: str = "wikilink",
    write: bool = True,
    lock: bool = True,
) -> IndexResult:
    """Reconcile ``index.md`` against the pages actually on disk.

    Regenerates one section per category and preserves the preamble plus any
    section whose heading is not a category — a hand-written "Reading queue"
    section survives, a stale page entry does not.
    """
    vault = _require_vault(vault)
    pages = scan_pages(vault)
    index = vault / "index.md"
    existing = index.read_text(encoding="utf-8") if index.is_file() else ""
    preamble, sections, _ = _split_index(existing)

    # A heading counts as generated when it names a category, whether or not a
    # page currently lives there. Deriving this from pages alone meant deleting
    # the last page in a category left its stale section behind, preserved as
    # though a human had written it.
    categories = {_heading_for(name).casefold() for name in CATEGORY_ORDER}
    categories |= {_heading_for(page.category).casefold() for page in pages}
    categories |= {
        _heading_for(child.name).casefold()
        for child in vault.iterdir()
        if child.is_dir() and child.name not in SKIP_DIRS and not child.name.startswith(".")
    }
    extra = "\n\n".join(
        body.strip("\n") for heading, body in sections.items() if heading not in categories
    )

    listed = set()
    for heading, body in sections.items():
        if heading in categories:
            for match in _WIKILINK_RE.finditer(body):
                listed.add(match.group(1).strip())
            for line in body.splitlines():
                md = re.match(r"^-\s*\[[^\]]*\]\(([^)]+)\)", line.strip())
                if md:
                    listed.add(md.group(1)[:-3] if md.group(1).endswith(".md") else md.group(1))

    current = {page.path[:-3] for page in pages}
    added = tuple(sorted(current - listed))
    removed = tuple(sorted(listed - current))
    text = render_index(pages, link_format=link_format, preamble=preamble, extra_sections=extra)
    changed = text != existing

    if write and changed:
        if lock:
            with memory_lock(vault):
                atomic_write(index, text)
        else:
            atomic_write(index, text)
    return IndexResult(added=added, removed=removed, total=len(pages), changed=changed, text=text)


# --------------------------------------------------------------------------
# _meta/profile.md — who the vault owner is
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    key: str
    value: str
    confidence: float
    source: str
    updated: str


def _cell(text: str) -> str:
    return str(text).replace("|", r"\|").replace("\n", " ").strip()


def _uncell(text: str) -> str:
    return text.replace(r"\|", "|").strip()


def _parse_table(text: str, columns: int) -> list:
    """Rows of the first markdown table in *text*, header and rule dropped."""
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [_uncell(cell) for cell in _CELL_SPLIT_RE.split(stripped[1:-1])]
        if len(cells) < columns:
            continue
        if all(set(cell) <= {"-", ":", " "} and cell for cell in cells):
            continue  # the |---|---| rule
        rows.append(cells[:columns])
    return rows[1:] if rows else []  # drop the header row


_PROFILE_HEADER = """---
title: Owner Profile
category: _meta
tags: [meta/profile]
sources: [conversation]
created: {created}
updated: {updated}
generated_by: obsidian-wiki memory profile
---

# Owner Profile

*Durable facts about the vault owner, injected into an agent's context at session
start. Written by `obsidian-wiki memory profile set`; safe to edit by hand — the
table round-trips. Confidence is the writer's own calibration, not a measurement.*

| Fact | Value | Confidence | Source | Updated |
|---|---|---|---|---|
"""


def load_profile(vault: Path) -> list:
    path = Path(vault) / PROFILE_REL
    if not path.is_file():
        return []
    facts = []
    for row in _parse_table(path.read_text(encoding="utf-8"), 5):
        key, value, confidence, source, updated = row
        if not key:
            continue
        try:
            score = float(confidence)
        except ValueError:
            score = 0.5
        facts.append(Fact(key, value, score, source, updated))
    return facts


def render_profile(facts: Sequence, *, created: str = "", updated: str = "") -> str:
    header = _PROFILE_HEADER.format(created=created or today(), updated=updated or today())
    rows = "\n".join(
        f"| {_cell(f.key)} | {_cell(f.value)} | {f.confidence:.2f} | {_cell(f.source)} | {_cell(f.updated)} |"
        for f in sorted(facts, key=lambda f: f.key.casefold())
    )
    return header + (rows + "\n" if rows else "")


def set_fact(
    vault: Path,
    key: str,
    value: str,
    *,
    confidence: float = 0.6,
    source: str = "conversation",
    lock: bool = True,
) -> Fact:
    """Add or replace one durable fact about the owner."""
    vault = _require_vault(vault)
    key = key.strip()
    if not key:
        raise MemoryError_("bad_key", "fact key must not be empty")
    if not 0.0 <= confidence <= 1.0:
        raise MemoryError_("bad_confidence", f"confidence must be in [0.0, 1.0]: {confidence}")
    fact = Fact(key, value.strip(), confidence, source.strip(), today())

    def _write() -> None:
        facts = [f for f in load_profile(vault) if f.key.casefold() != key.casefold()]
        facts.append(fact)
        atomic_write(vault / PROFILE_REL, render_profile(facts))

    if lock:
        with memory_lock(vault):
            _write()
    else:
        _write()
    return fact


def forget_fact(vault: Path, key: str, *, lock: bool = True) -> bool:
    vault = _require_vault(vault)

    def _write() -> bool:
        facts = load_profile(vault)
        kept = [f for f in facts if f.key.casefold() != key.strip().casefold()]
        if len(kept) == len(facts):
            return False
        atomic_write(vault / PROFILE_REL, render_profile(kept))
        return True

    if lock:
        with memory_lock(vault):
            return _write()
    return _write()


# --------------------------------------------------------------------------
# _meta/todos.md — open threads
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Todo:
    id: str
    text: str
    status: str  # open | done | dropped
    origin: str
    created: str
    touched: str

    def is_stale(self, *, days: int = DEFAULT_TODO_STALE_DAYS, now: Optional[datetime] = None) -> bool:
        if self.status != "open" or not self.touched:
            return False
        try:
            touched = datetime.strptime(self.touched, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        return (now or datetime.now(timezone.utc)) - touched > timedelta(days=days)


TODO_STATUSES = ("open", "done", "dropped")

_TODOS_HEADER = """---
title: Todo Index
category: _meta
tags: [meta/todos]
sources: [conversation]
created: {created}
updated: {updated}
generated_by: obsidian-wiki memory todo
---

# Todo Index

*Open threads carried between sessions. Written by `obsidian-wiki memory todo`;
safe to edit by hand — the table round-trips. An open item untouched for
{stale} days is reported stale rather than silently kept alive.*

| ID | Status | Thread | Origin | Created | Touched |
|---|---|---|---|---|---|
"""


def load_todos(vault: Path) -> list:
    path = Path(vault) / TODOS_REL
    if not path.is_file():
        return []
    todos = []
    for row in _parse_table(path.read_text(encoding="utf-8"), 6):
        todo_id, status, text, origin, created, touched = row
        if not todo_id:
            continue
        todos.append(Todo(todo_id, text, status or "open", origin, created, touched))
    return todos


def render_todos(todos: Sequence, *, created: str = "", updated: str = "") -> str:
    header = _TODOS_HEADER.format(
        created=created or today(), updated=updated or today(), stale=DEFAULT_TODO_STALE_DAYS
    )
    order = {status: position for position, status in enumerate(TODO_STATUSES)}
    rows = "\n".join(
        f"| {_cell(t.id)} | {_cell(t.status)} | {_cell(t.text)} | {_cell(t.origin)} "
        f"| {_cell(t.created)} | {_cell(t.touched)} |"
        for t in sorted(todos, key=lambda t: (order.get(t.status, 9), _todo_number(t.id)))
    )
    return header + (rows + "\n" if rows else "")


def _todo_number(todo_id: str) -> int:
    match = re.search(r"(\d+)$", todo_id or "")
    return int(match.group(1)) if match else 0


def _next_todo_id(todos: Sequence) -> str:
    return f"t{max((_todo_number(t.id) for t in todos), default=0) + 1}"


def add_todo(vault: Path, text: str, *, origin: str = "", lock: bool = True) -> Todo:
    vault = _require_vault(vault)
    text = text.strip()
    if not text:
        raise MemoryError_("bad_todo", "todo text must not be empty")
    holder: list = []

    def _write() -> None:
        todos = load_todos(vault)
        existing = next((t for t in todos if t.text.casefold() == text.casefold() and t.status == "open"), None)
        if existing is not None:  # idempotent: re-adding an open thread just touches it
            todo = replace(existing, touched=today())
            todos = [todo if t.id == existing.id else t for t in todos]
        else:
            todo = Todo(_next_todo_id(todos), text, "open", origin.strip(), today(), today())
            todos.append(todo)
        atomic_write(vault / TODOS_REL, render_todos(todos))
        holder.append(todo)

    if lock:
        with memory_lock(vault):
            _write()
    else:
        _write()
    return holder[0]


def set_todo_status(vault: Path, todo_id: str, status: str, *, lock: bool = True) -> Todo:
    vault = _require_vault(vault)
    if status not in TODO_STATUSES:
        raise MemoryError_("bad_status", f"status must be one of {', '.join(TODO_STATUSES)}")
    holder: list = []

    def _write() -> None:
        todos = load_todos(vault)
        match = next((t for t in todos if t.id.casefold() == todo_id.strip().casefold()), None)
        if match is None:
            raise MemoryError_("no_such_todo", f"no todo with id {todo_id!r}")
        updated = replace(match, status=status, touched=today())
        atomic_write(
            vault / TODOS_REL,
            render_todos([updated if t.id == match.id else t for t in todos]),
        )
        holder.append(updated)

    if lock:
        with memory_lock(vault):
            _write()
    else:
        _write()
    return holder[0]


def prune_todos(vault: Path, *, lock: bool = True) -> int:
    """Drop closed items from the table. Returns how many were removed."""
    vault = _require_vault(vault)
    holder: list = []

    def _write() -> None:
        todos = load_todos(vault)
        kept = [t for t in todos if t.status == "open"]
        holder.append(len(todos) - len(kept))
        if len(kept) != len(todos):
            atomic_write(vault / TODOS_REL, render_todos(kept))

    if lock:
        with memory_lock(vault):
            _write()
    else:
        _write()
    return holder[0]


# --------------------------------------------------------------------------
# hot.md — the generated session snapshot
# --------------------------------------------------------------------------


_HOT_NOTE = (
    "*Generated snapshot of recent vault activity. Rebuilt by "
    "`obsidian-wiki memory hot` — edits to the generated sections are "
    "overwritten, so put durable prose in `## Key Takeaways`, which survives "
    "every rebuild.*"
)
_TAKEAWAYS_PLACEHOLDER = "*None yet.*"


def _section_body(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE | re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return ""
    rest = text[match.end():]
    following = _HEADING_RE.search(rest)
    return (rest[: following.start()] if following else rest).strip()


def word_count(text: str) -> int:
    return len(text.split())


def content_words(text: str) -> int:
    """Words a reader actually consumes: no frontmatter, no generated note.

    The documented cap is on the snapshot's content. Counting the YAML header
    and the "this file is generated" note against it put the floor within a few
    words of the cap, so trimming could spin without ever getting under budget.
    """
    body = _split_frontmatter(text)[1].replace(_HOT_NOTE, "")
    return len(body.split())


def hot_max_words() -> int:
    raw = os.environ.get("OBSIDIAN_HOT_MAX_WORDS", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_HOT_MAX_WORDS
    return value if value > 0 else DEFAULT_HOT_MAX_WORDS


@dataclass(frozen=True)
class HotResult:
    words: int
    trimmed: bool
    activity: int
    threads: int
    contradictions: int
    text: str


def _recent_activity_lines(vault: Path, limit: int) -> list:
    return [entry.raw for entry in read_log(vault, limit=limit)]


def _contradiction_lines(pages: Sequence, limit: int, link_format: str) -> list:
    def _link(node: str) -> str:
        return f"[{node}]({node}.md)" if link_format == "markdown" else f"[[{node}]]"

    lines = []
    for page in sorted(pages, key=lambda p: p.updated, reverse=True):
        node = page.path[:-3]
        if page.lifecycle == "disputed":
            since = f" since {page.updated}" if page.updated else ""
            lines.append(f"- {_link(node)} — marked disputed{since}")
        for target in page.contradicts:
            lines.append(f"- {_link(node)} contradicts {_link(target)}")
        if len(lines) >= limit:
            break
    return lines[:limit]


def build_hot(
    vault: Path,
    *,
    takeaways: Optional[str] = None,
    link_format: str = "wikilink",
    max_words: Optional[int] = None,
    activity_limit: int = DEFAULT_RECENT_ACTIVITY,
    thread_limit: int = DEFAULT_ACTIVE_THREADS,
    contradiction_limit: int = DEFAULT_CONTRADICTIONS,
) -> HotResult:
    """Render the hot cache without writing it.

    Word-capped for real. When the render is over budget, sections are dropped
    in increasing order of value: activity lines first, then contradictions,
    then threads, and ``Key Takeaways`` is truncated last because it is the only
    part a model wrote on purpose.
    """
    vault = _require_vault(vault)
    cap = max_words or hot_max_words()
    hot = vault / "hot.md"
    existing = hot.read_text(encoding="utf-8") if hot.is_file() else ""

    if takeaways is None:
        carried = _section_body(existing, "Key Takeaways")
        takeaways = carried if carried else _TAKEAWAYS_PLACEHOLDER
    takeaways = takeaways.strip() or _TAKEAWAYS_PLACEHOLDER

    pages = scan_pages(vault)
    activity = _recent_activity_lines(vault, activity_limit)
    threads = [t for t in load_todos(vault) if t.status == "open"][:thread_limit]
    contradictions = _contradiction_lines(pages, contradiction_limit, link_format)

    def _render(act: list, con: list, thr: list, take: str) -> str:
        thread_lines = [
            f"- **{t.id}** {t.text}" + (f" — {t.origin}" if t.origin else "") + f" (touched {t.touched})"
            for t in thr
        ]
        blocks = [
            "---\ntitle: Hot Cache\n"
            f"updated: {utc_now()}\n"
            f"pages: {len(pages)}\n"
            "generated_by: obsidian-wiki memory hot\n---",
            "# Hot Cache",
            _HOT_NOTE,
            "## Recent Activity\n\n" + ("\n".join(act) if act else "*No logged operations yet.*"),
            "## Active Threads\n\n" + ("\n".join(thread_lines) if thread_lines else "*No open threads.*"),
            "## Key Takeaways\n\n" + take,
            "## Flagged Contradictions\n\n" + ("\n".join(con) if con else "*None flagged.*"),
        ]
        return "\n\n".join(blocks) + "\n"

    text = _render(activity, contradictions, threads, takeaways)
    trimmed = False
    while content_words(text) > cap:
        if len(activity) > 1:
            activity = activity[1:]
        elif contradictions:
            contradictions = contradictions[:-1]
        elif len(threads) > 1:
            threads = threads[:-1]
        else:
            words = takeaways.split()
            if len(words) <= 20:
                break  # the skeleton alone exceeds the cap; report it instead of looping
            takeaways = " ".join(words[: max(20, len(words) - 25)]) + " …"
        trimmed = True
        text = _render(activity, contradictions, threads, takeaways)

    return HotResult(
        words=content_words(text),
        trimmed=trimmed,
        activity=len(activity),
        threads=len(threads),
        contradictions=len(contradictions),
        text=text,
    )


def rebuild_hot(vault: Path, *, write: bool = True, lock: bool = True, **kwargs) -> HotResult:
    vault = _require_vault(vault)
    if lock:
        with memory_lock(vault):
            result = build_hot(vault, **kwargs)
            if write:
                atomic_write(vault / "hot.md", result.text)
            return result
    result = build_hot(vault, **kwargs)
    if write:
        atomic_write(vault / "hot.md", result.text)
    return result


# --------------------------------------------------------------------------
# recap — the block injected into a fresh session
# --------------------------------------------------------------------------


def build_recap(vault: Path, *, max_words: int = 400, min_confidence: float = 0.0) -> str:
    """Profile, open threads, and the newest activity as one injectable block.

    This is what a SessionStart or PreCompact hook feeds back into context: the
    left-hand column of the memory diagram, rendered once, instead of three
    separate file reads the model has to remember to make.
    """
    vault = _require_vault(vault)
    facts = [f for f in load_profile(vault) if f.confidence >= min_confidence]
    todos = [t for t in load_todos(vault) if t.status == "open"]
    entries = read_log(vault, limit=5)
    stale = [t for t in todos if t.is_stale()]

    lines = ["# Vault memory", ""]
    if facts:
        lines.append("## Who you are working with")
        lines.append("")
        lines += [f"- **{f.key}**: {f.value} ({f.confidence:.2f})" for f in facts]
        lines.append("")
    if todos:
        lines.append("## Open threads")
        lines.append("")
        for todo in todos:
            mark = " *(stale)*" if todo in stale else ""
            origin = f" — {todo.origin}" if todo.origin else ""
            lines.append(f"- **{todo.id}** {todo.text}{origin}{mark}")
        lines.append("")
    if entries:
        lines.append("## Recent vault activity")
        lines.append("")
        lines += [entry.raw for entry in entries]
        lines.append("")
    if not facts and not todos and not entries:
        lines.append("*No vault memory recorded yet.*")
        lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    if word_count(text) > max_words:
        words = text.split()
        text = " ".join(words[:max_words]) + " …\n"
    return text


def memory_status(vault: Path) -> dict:
    """Machine-readable health of the memory surface."""
    vault = _require_vault(vault)
    hot = vault / "hot.md"
    hot_text = hot.read_text(encoding="utf-8") if hot.is_file() else ""
    hot_values = parse_frontmatter(_split_frontmatter(hot_text)[0]) if hot_text else {}
    index_drift = rebuild_index(vault, write=False, lock=False)
    todos = load_todos(vault)
    return {
        "vault": str(vault),
        "pages": index_drift.total,
        "index_drift": {
            "added": list(index_drift.added),
            "removed": list(index_drift.removed),
            "stale": index_drift.changed,
        },
        "log_entries": len(read_log(vault)),
        "hot": {
            "exists": hot.is_file(),
            "updated": str(hot_values.get("updated") or ""),
            "words": content_words(hot_text),
            "max_words": hot_max_words(),
            "over_budget": content_words(hot_text) > hot_max_words(),
            "generated": bool(hot_values.get("generated_by")),
        },
        "profile_facts": len(load_profile(vault)),
        "todos": {
            "open": sum(1 for t in todos if t.status == "open"),
            "stale": sum(1 for t in todos if t.is_stale()),
            "closed": sum(1 for t in todos if t.status != "open"),
        },
    }
