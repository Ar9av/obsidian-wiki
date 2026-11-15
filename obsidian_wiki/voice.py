"""``_meta/voice.md`` — how the vault owner sounds, and the words they never use.

``WRITING.md`` governs how wiki pages read. This file is about the owner's own
public voice: the posts they are proud of, the ones they can't stand, and a list
of words and phrases that must never appear in something written for them. An
agent drafting a post, a readout or an email in the owner's name reads the
examples for tone and runs ``check`` for the hard rules.

The file is a plain page with ``##`` sections, so it is written in Obsidian like
anything else. Sections are recognised by their heading:

``## Never use`` (also "banned", "avoid words")
    One word or phrase per bullet. ``leverage -> use`` adds a suggested
    replacement. Entries made of punctuation (``—``) are matched literally.
``## Posts I love`` (also "best", "like", "good examples")
    Bullets: a ``[[wikilink]]`` to a page or a quoted excerpt.
``## Posts I hate`` (also "worst", "bad examples")
    Same shape. What *not* to sound like.

Anything else in the file is kept as free-form notes on tone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from obsidian_wiki.vault import split_frontmatter

VOICE_REL = "_meta/voice.md"

TEMPLATE = """---
title: Voice
category: _meta
tags: [meta/voice]
sources: [owner]
created: {created}
updated: {created}
---

# Voice

*How I sound when I write in public, read by agents that draft in my name.
`obsidian-wiki voice check <draft>` enforces the "Never use" list; the examples
set the tone. Edit freely.*

## Never use

<!-- One word or phrase per bullet. `leverage -> use` suggests a replacement. -->

## Posts I love

<!-- Links to pages ([[my-best-post]]) or short quoted excerpts. Aim for the 50 best. -->

## Posts I hate

<!-- What not to sound like: your own misfires or other people's posts. -->

## Notes on tone

"""

_BANNED_HEADINGS = ("never use", "banned", "avoid words", "words i never use", "do not use", "don't use")
_LOVE_HEADINGS = ("love", "best", "like", "good example", "exemplar")
_HATE_HEADINGS = ("hate", "worst", "dislike", "bad example", "anti")
_ARROW_RE = re.compile(r"\s*(?:->|→|=>)\s*")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*\S)\s*$")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SKIP_SPAN_RE = re.compile(r"`[^`]*`|\[\[[^\]]*\]\]|\]\([^)]*\)|https?://\S+")


@dataclass(frozen=True)
class Banned:
    phrase: str
    replacement: str = ""

    def pattern(self) -> re.Pattern:
        escaped = r"\s+".join(re.escape(part) for part in self.phrase.split())
        # Whole-word boundaries only where the entry starts/ends with a word character,
        # so `—` or `!!` still match inside text.
        left = r"(?<![\w])" if re.match(r"\w", self.phrase) else ""
        right = r"(?![\w])" if re.search(r"\w$", self.phrase) else ""
        return re.compile(left + escaped + right, re.IGNORECASE)


@dataclass
class Voice:
    banned: list = field(default_factory=list)
    love: list = field(default_factory=list)
    hate: list = field(default_factory=list)
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "banned": [{"phrase": b.phrase, "replacement": b.replacement} for b in self.banned],
            "love": list(self.love),
            "hate": list(self.hate),
            "notes": self.notes,
        }


def voice_path(vault: Path) -> Path:
    return Path(vault) / VOICE_REL


def _strip_item(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "`\"'":
        text = text[1:-1].strip()
    return text


def _kind(heading: str) -> str:
    lowered = heading.lower()
    if any(key in lowered for key in _BANNED_HEADINGS):
        return "banned"
    if any(key in lowered for key in _HATE_HEADINGS):
        return "hate"
    if any(key in lowered for key in _LOVE_HEADINGS):
        return "love"
    return "notes"


def parse_voice(text: str) -> Voice:
    _, body = split_frontmatter(text)
    body = _COMMENT_RE.sub("", body)
    voice = Voice()
    kind = ""
    notes: list = []
    seen: set = set()
    for line in body.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            kind = _kind(heading.group(1))
            if kind == "notes":
                notes.append(line)
            continue
        if not kind:
            continue  # title and intro before the first section
        bullet = _BULLET_RE.match(line)
        if kind == "banned":
            if not bullet:
                continue
            parts = _ARROW_RE.split(bullet.group(1), maxsplit=1)
            phrase = _strip_item(parts[0])
            replacement = _strip_item(parts[1]) if len(parts) > 1 else ""
            if phrase and phrase.casefold() not in seen:
                seen.add(phrase.casefold())
                voice.banned.append(Banned(phrase, replacement))
        elif kind in ("love", "hate"):
            if bullet:
                getattr(voice, kind).append(bullet.group(1).strip())
        else:
            notes.append(line)
    voice.notes = "\n".join(notes).strip()
    return voice


def load_voice(vault: Path) -> Voice:
    path = voice_path(vault)
    if not path.is_file():
        return Voice()
    return parse_voice(path.read_text(encoding="utf-8"))


def _prose_lines(text: str) -> Iterable[tuple]:
    """(line number, text) outside frontmatter and fenced code, inline code and links blanked."""
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
        if fence or not stripped:
            continue
        yield number, _SKIP_SPAN_RE.sub(lambda m: " " * len(m.group(0)), line)


def check_text(text: str, voice: Voice) -> list:
    """Every occurrence of a banned word or phrase, with line and column."""
    patterns = [(entry, entry.pattern()) for entry in voice.banned]
    findings = []
    for number, line in _prose_lines(text):
        for entry, pattern in patterns:
            for match in pattern.finditer(line):
                finding = {
                    "line": number,
                    "column": match.start() + 1,
                    "match": match.group(0),
                    "phrase": entry.phrase,
                }
                if entry.replacement:
                    finding["replacement"] = entry.replacement
                findings.append(finding)
    findings.sort(key=lambda f: (f["line"], f["column"]))
    return findings


def check_file(vault: Path, text: str) -> dict:
    voice = load_voice(vault)
    findings = check_text(text, voice)
    return {
        "voice_file": str(voice_path(vault)),
        "banned": len(voice.banned),
        "findings": findings,
    }
