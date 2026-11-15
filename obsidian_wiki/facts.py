"""``_meta/facts.md`` — the claims an agent is allowed to make.

The owner profile (``_meta/profile.md``) says who the owner *is* so an agent can
tailor its work. This file is different: it is the short list of things that are
true about the owner and their company and may be said out loud — in a readout,
a digest, a post, a reply to a customer. Every row carries a source and an
"as of" date, so a number that was right in March is visibly from March.

``check`` is the point of the file. Agents invent figures ("trusted by 500
teams") and absolutes ("the first", "the only") when they write about a person
or a company. ``check`` finds the claim-shaped sentences in a draft — the ones
with a number or an absolute in them — and reports each one no approved fact
backs. It is a heuristic and deliberately loud; it never edits the draft.

The table is plain markdown so Obsidian renders it and a human can edit it in
place. Rows a human adds without an ID get one on the next write.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional, Sequence

from obsidian_wiki import clock
from obsidian_wiki.memory import (
    MemoryError_,
    _cell,
    _parse_table,
    _require_vault,
    atomic_write,
    memory_lock,
    today,
)
from obsidian_wiki.vault import split_frontmatter

FACTS_REL = "_meta/facts.md"
DEFAULT_STALE_DAYS = 180
STATUSES = ("approved", "retired")

_HEADER = """---
title: Approved Facts
category: _meta
tags: [meta/facts]
sources: [owner]
created: {created}
updated: {updated}
generated_by: obsidian-wiki facts
---

# Approved Facts

*True things about the owner and the company that agents may say in public
writing. Each claim has a source and the date it was last true. A retired claim
stays here so `obsidian-wiki facts check` can flag drafts that still use it.
Written by `obsidian-wiki facts add`; safe to edit by hand, and rows added
without an ID get one on the next write.*

| ID | Claim | Source | As of | Status | Note |
|---|---|---|---|---|---|
"""


@dataclass(frozen=True)
class Claim:
    id: str
    text: str
    source: str
    as_of: str
    status: str = "approved"
    note: str = ""

    @property
    def approved(self) -> bool:
        return self.status == "approved"

    def is_stale(self, on: Optional[str] = None, days: int = DEFAULT_STALE_DAYS) -> bool:
        if not self.approved or not self.as_of:
            return False
        try:
            stamp = date.fromisoformat(self.as_of[:10])
        except ValueError:
            return False
        return stamp < date.fromisoformat(on or today()) - timedelta(days=days)


def facts_path(vault: Path) -> Path:
    return Path(vault) / FACTS_REL


def _id_number(claim_id: str) -> int:
    match = re.fullmatch(r"f(\d+)", claim_id.strip().lower())
    return int(match.group(1)) if match else 0


def load_facts(vault: Path) -> list:
    path = facts_path(vault)
    if not path.is_file():
        return []
    claims = []
    for row in _parse_table(path.read_text(encoding="utf-8"), 5, optional=1):
        claim_id, text, source, as_of, status, note = row
        if not text:
            continue
        status = status.strip().lower() or "approved"
        if status not in STATUSES:
            status = "approved"
        claims.append(Claim(claim_id.strip(), text, source, as_of, status, note))
    return _assign_ids(claims)


def _assign_ids(claims: Sequence) -> list:
    """Give hand-added rows (blank ID) the next free ``fN``."""
    next_id = max((_id_number(c.id) for c in claims), default=0)
    out = []
    for claim in claims:
        if not claim.id:
            next_id += 1
            claim = replace(claim, id=f"f{next_id}")
        out.append(claim)
    return out


def render_facts(claims: Sequence, *, created: str = "", updated: str = "", tz=None) -> str:
    header = _HEADER.format(created=created or today(tz), updated=updated or today(tz))
    order = {"approved": 0, "retired": 1}
    rows = "\n".join(
        f"| {_cell(c.id)} | {_cell(c.text)} | {_cell(c.source)} | {_cell(c.as_of)} | {c.status} | {_cell(c.note)} |"
        for c in sorted(claims, key=lambda c: (order.get(c.status, 9), _id_number(c.id)))
    )
    return header + (rows + "\n" if rows else "")


def _created_of(vault: Path) -> str:
    path = facts_path(vault)
    if not path.is_file():
        return ""
    frontmatter, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    match = re.search(r"^created:\s*(\S+)", frontmatter, re.MULTILINE)
    return match.group(1) if match else ""


def _write(vault: Path, claims: Sequence) -> None:
    tz = clock.wiki_timezone(vault)
    atomic_write(facts_path(vault), render_facts(claims, created=_created_of(vault), tz=tz))


def add_fact(vault: Path, text: str, *, source: str, as_of: str = "", note: str = "") -> Claim:
    """Approve one claim. Re-adding the same text refreshes its source and date."""
    vault = _require_vault(vault)
    text = " ".join(text.split())
    if not text:
        raise MemoryError_("bad_claim", "claim text must not be empty")
    if not source.strip():
        raise MemoryError_("bad_source", "a claim needs --source: where it can be checked")
    tz = clock.wiki_timezone(vault)
    as_of = as_of.strip() or today(tz)
    try:
        as_of = date.fromisoformat(as_of).isoformat()
    except ValueError:
        raise MemoryError_("bad_as_of", f"as-of must be YYYY-MM-DD: {as_of}") from None

    with memory_lock(vault):
        claims = load_facts(vault)
        existing = next((c for c in claims if c.text.casefold() == text.casefold()), None)
        if existing:
            claim = replace(existing, source=source.strip(), as_of=as_of, status="approved", note=note.strip())
            claims = [claim if c.id == existing.id else c for c in claims]
        else:
            next_id = max((_id_number(c.id) for c in claims), default=0) + 1
            claim = Claim(f"f{next_id}", text, source.strip(), as_of, "approved", note.strip())
            claims.append(claim)
        _write(vault, claims)
    return claim


def retire_fact(vault: Path, claim_id: str, *, reason: str = "") -> Claim:
    """Mark a claim no longer true. The row stays so drafts using it get flagged."""
    vault = _require_vault(vault)
    with memory_lock(vault):
        claims = load_facts(vault)
        match = next((c for c in claims if c.id.casefold() == claim_id.strip().casefold()), None)
        if match is None:
            raise MemoryError_("no_such_fact", f"no fact with id {claim_id!r}")
        tz = clock.wiki_timezone(vault)
        note = f"retired {today(tz)}" + (f": {reason.strip()}" if reason.strip() else "")
        retired = replace(match, status="retired", note=note)
        _write(vault, [retired if c.id == match.id else c for c in claims])
    return retired


# --------------------------------------------------------------------------
# check — which sentences in a draft does no approved fact back?
# --------------------------------------------------------------------------

#: Words that turn a sentence into a claim someone could call false.
ABSOLUTES = frozenset({
    "first", "only", "largest", "biggest", "leading", "fastest", "best", "cheapest",
    "guaranteed", "certified", "compliant", "award-winning", "unmatched", "unrivaled",
    "unrivalled", "#1", "no.1",
})
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
_NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<cur>[$€£])?(?P<num>\d+(?:[,.]\d+)*)\s?"
    r"(?P<unit>%|x\b|k\b|mm\b|m\b|bn\b|b\b|thousand\b|million\b|billion\b)?",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-z][a-z0-9'-]+|#1|no\.1")
_STOP = frozenset(
    "the a an and or but of to in on for with by at from as is are was were be been "
    "our we us you your it its this that these those than then has have had over into "
    "more most per across about".split()
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[*_])")
_SKIP_SPAN_RE = re.compile(r"`[^`]*`|\[\[[^\]]*\]\]|\]\([^)]*\)|https?://\S+")


def _number_tokens(text: str) -> dict:
    """Canonical value -> the spelling it first appeared as."""
    found: dict = {}
    for match in _NUMBER_RE.finditer(_SKIP_SPAN_RE.sub(" ", text)):
        raw = match.group("num")
        unit = (match.group("unit") or "").lower()
        # A thousands separator is a comma followed by exactly three digits.
        digits = re.sub(r",(?=\d{3}\b)", "", raw)
        if "," in digits:
            digits = digits.replace(",", ".")  # decimal comma
        if digits.count(".") > 1:
            digits = digits.replace(".", "")  # 1.000.000
        try:
            value = float(digits)
        except ValueError:
            continue
        if unit in ("%", "x"):
            canonical = f"{value:.12g}{unit}"
        else:
            canonical = f"{value * _SCALE.get(unit, 1):.12g}"
        found.setdefault(canonical, match.group(0).strip())
    return found


def numbers_in(text: str) -> set:
    """Canonical number tokens: ``$2M``, ``2 million`` and ``2,000,000`` are one value."""
    return set(_number_tokens(text))


def _words(text: str) -> set:
    return set(_WORD_RE.findall(_SKIP_SPAN_RE.sub(" ", text.lower())))


def _content_words(text: str) -> set:
    return {w for w in _words(text) if len(w) >= 3 and w not in _STOP and w not in ABSOLUTES}


def _sentences(text: str) -> Iterable[tuple]:
    """(line number, sentence) for prose lines, skipping frontmatter, fences and tables."""
    frontmatter, body = split_frontmatter(text)
    offset = text[: len(text) - len(body)].count("\n") if frontmatter else 0
    fence = ""
    for number, line in enumerate(body.splitlines(), start=offset + 1):
        stripped = line.strip()
        marker = re.match(r"(`{3,}|~{3,})", stripped)
        if marker:
            if not fence:
                fence = marker.group(1)
            elif stripped.startswith(fence):
                fence = ""
            continue
        if fence or not stripped or stripped.startswith(("|", "#", ">")):
            continue
        prose = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)
        for sentence in _SENTENCE_SPLIT_RE.split(prose.strip()):
            if sentence.strip():
                yield number, sentence.strip()


def check_text(text: str, claims: Sequence) -> list:
    """Claim-shaped sentences in *text* that no approved fact backs.

    A sentence is claim-shaped when it has a number or an absolute word in it.
    It is backed when every number in it appears in some approved fact, and
    every absolute appears in an approved fact that also shares a content word
    with the sentence ("the first SOC 2 tool" needs a fact about SOC 2, not just
    any fact containing "first"). A sentence whose numbers only match a retired
    fact is reported as ``retired``, naming the fact.
    """
    approved = [c for c in claims if c.approved]
    retired = [c for c in claims if not c.approved]
    approved_numbers = set().union(*(numbers_in(c.text) for c in approved)) if approved else set()
    findings = []
    for line, sentence in _sentences(text):
        tokens = _number_tokens(sentence)
        numbers = set(tokens)
        absolutes = _words(sentence) & ABSOLUTES
        if not numbers and not absolutes:
            continue
        content = _content_words(sentence)
        unbacked = numbers - approved_numbers
        missing = [tokens[n] for n in sorted(unbacked)]
        for word in sorted(absolutes):
            backed = any(word in _words(c.text) and (_content_words(c.text) & content) for c in approved)
            if not backed:
                missing.append(word)
        if not missing:
            continue
        finding = {"line": line, "text": sentence, "status": "unsupported", "missing": missing}
        stale_numbers = unbacked
        if stale_numbers:
            for claim in retired:
                if stale_numbers <= numbers_in(claim.text):
                    finding.update(status="retired", fact=claim.id, fact_text=claim.text)
                    break
        findings.append(finding)
    return findings


def check_file(vault: Path, text: str) -> dict:
    claims = load_facts(vault)
    findings = check_text(text, claims)
    return {
        "facts_file": str(facts_path(vault)),
        "approved": sum(1 for c in claims if c.approved),
        "findings": findings,
        "unsupported": sum(1 for f in findings if f["status"] == "unsupported"),
        "retired": sum(1 for f in findings if f["status"] == "retired"),
    }
