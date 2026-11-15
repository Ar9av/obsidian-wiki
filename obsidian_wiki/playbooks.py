"""Which playbooks does this week's evidence touch?

A playbook is a how-to page: anything under a ``skills/`` folder (top level or
inside a project), or any page tagged ``playbook``. Playbooks go stale quietly.
A meeting shows the sales script's second step no longer lands, a postmortem
finds a missing check in the deploy runbook, and the playbook never hears about
it.

:func:`playbook_evidence` is the mechanical half of the weekly review that
``wiki-playbook-review`` runs. For each playbook it lists the pages written or
updated in the window that are connected to it, and why: a link from the
evidence to the playbook, a link from the playbook to the evidence, a shared
domain tag, or a log line naming the playbook. Deciding what the evidence means
for the playbook, and drafting the revision, is the skill's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from obsidian_wiki.context_pack import PageRecord, load_pages
from obsidian_wiki.links import PageIndex, strip_code

PLAYBOOK_TAGS = frozenset({"playbook", "type/playbook", "runbook", "type/runbook"})
#: Tags too broad to say two pages are about the same thing.
_GENERIC_TAG_PREFIXES = ("visibility/", "meta/", "type/", "lifecycle/", "status/")
_GENERIC_TAGS = frozenset({"playbook", "runbook", "meeting", "journal", "digest", "draft", "todo"})

WEIGHT_LINK_TO = 3     # evidence links to the playbook: it is explicitly about it
WEIGHT_LINK_FROM = 2   # the playbook links to the evidence: a page it depends on changed
WEIGHT_TAG = 1         # per shared domain tag
WEIGHT_LOG = 2         # a log entry in the window names the playbook
MIN_SCORE = 2          # one shared tag alone is not evidence

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")
_MDLINK_RE = re.compile(r"\]\(([^)#\s]+?\.md)(?:#[^)]*)?\)")


@dataclass(frozen=True)
class Evidence:
    path: str
    title: str
    summary: str
    updated: str
    score: int
    reasons: tuple

    def as_dict(self) -> dict:
        return {
            "path": self.path, "title": self.title, "summary": self.summary,
            "updated": self.updated, "score": self.score, "reasons": list(self.reasons),
        }


def is_playbook(page: PageRecord) -> bool:
    parts = page.path.split("/")
    return "skills" in parts[:-1] or bool(PLAYBOOK_TAGS & {t.lower() for t in page.tags})


def _domain_tags(page: PageRecord) -> set:
    return {
        t.lower() for t in page.tags
        if t.lower() not in _GENERIC_TAGS and not t.lower().startswith(_GENERIC_TAG_PREFIXES)
    }


def _date_of(stamp: str) -> Optional[date]:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", stamp.strip().strip("\"'"))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def parse_since(value: str, *, today: Optional[date] = None) -> date:
    """``7d`` / ``2w`` / ``YYYY-MM-DD`` -> the first day of the window."""
    today = today or date.today()
    value = value.strip().lower()
    match = re.fullmatch(r"(\d+)\s*([dw])", value)
    if match:
        days = int(match.group(1)) * (7 if match.group(2) == "w" else 1)
        return today - timedelta(days=days)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"--since must be like 7d, 2w or YYYY-MM-DD: {value!r}") from None


def _links(page: PageRecord, index: PageIndex) -> set:
    body = strip_code(page.body)
    targets = _WIKILINK_RE.findall(body) + _MDLINK_RE.findall(body)
    out = set()
    for target in targets:
        page_id = index.resolve(target.strip(), page.path)
        if page_id:
            path = index.path_for(page_id)
            if path and path != page.path:
                out.add(path)
    return out


def _log_mentions(vault: Path, since: date) -> list:
    from obsidian_wiki.memory import read_log

    lines = []
    for entry in read_log(vault):
        stamp = _date_of(entry.timestamp)
        if stamp and stamp >= since:
            lines.append(entry.raw)
    return lines


def playbook_evidence(
    vault: Path,
    *,
    since: date,
    limit: int = 10,
    playbook: str = "",
) -> dict:
    """Playbooks ranked by how much connected evidence landed since *since*."""
    vault = Path(vault)
    pages = load_pages(vault)
    by_path = {p.path: p for p in pages}
    index = PageIndex(by_path)
    links = {p.path: _links(p, index) for p in pages}
    playbooks = [p for p in pages if is_playbook(p)]
    if playbook:
        wanted = index.match(playbook)
        wanted_path = index.path_for(wanted) if wanted else None
        playbooks = [p for p in playbooks if p.path == wanted_path]
        if not playbooks:
            raise ValueError(f"no playbook matches {playbook!r}")

    recent = [p for p in pages if (_date_of(p.updated) or date.min) >= since]
    log_lines = _log_mentions(vault, since)

    results = []
    for book in playbooks:
        stem = Path(book.path).stem
        book_tags = _domain_tags(book)
        found = []
        for page in recent:
            if page.path == book.path:
                continue
            reasons = []
            score = 0
            if book.path in links[page.path]:
                reasons.append("links to the playbook")
                score += WEIGHT_LINK_TO
            if page.path in links[book.path]:
                reasons.append("linked from the playbook")
                score += WEIGHT_LINK_FROM
            shared = sorted(book_tags & _domain_tags(page))
            if shared:
                reasons.append("shares tags: " + ", ".join(shared))
                score += WEIGHT_TAG * len(shared)
            if score >= MIN_SCORE:
                found.append(Evidence(page.path, page.title, page.summary[:200], page.updated, score, tuple(reasons)))
        mention = re.compile(rf"(?<![\w-]){re.escape(stem)}(?![\w-])", re.IGNORECASE)
        logged = [line for line in log_lines if mention.search(line)]
        found.sort(key=lambda e: (-e.score, e.path))
        total = sum(e.score for e in found) + WEIGHT_LOG * len(logged)
        changed_itself = (_date_of(book.updated) or date.min) >= since
        if not found and not logged and not playbook:
            continue
        results.append({
            "playbook": book.path,
            "title": book.title,
            "updated": book.updated,
            "updated_in_window": changed_itself,
            "score": total,
            "evidence": [e.as_dict() for e in found[:limit]],
            "evidence_total": len(found),
            "log": logged[-limit:],
        })
    results.sort(key=lambda r: (-r["score"], r["playbook"]))
    return {
        "since": since.isoformat(),
        "playbooks_total": len(playbooks),
        "recent_pages": len(recent),
        "playbooks": results,
    }


def today_in(vault: Path) -> date:
    from obsidian_wiki import clock

    return date.fromisoformat(clock.today(clock.wiki_timezone(vault)))


__all__ = ["playbook_evidence", "parse_since", "is_playbook", "today_in"]
