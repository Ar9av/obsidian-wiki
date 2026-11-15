"""Normalise meeting and voice-note transcripts before an agent distils them.

Call recorders and dictation tools each export a different shape: WebVTT and
SRT caption files, ``Speaker: text`` lines with or without timestamps, Otter's
"name and time on one line, text below", and markdown exports with bold
speaker names. An agent reading the raw file spends most of its context on cue
numbers, timing arrows and "um"s, and still has to guess who said what.

:func:`parse_transcript` turns any of them into one record — title, date,
speakers, and a list of turns — and :func:`render_condensed` writes that back
as compact markdown with consecutive turns by the same speaker merged and
filler words removed. The condensed form is what the meeting branch of
``wiki-ingest`` reads; the original file stays in ``_raw/`` as the snapshot.

Everything here is deterministic and offline. It never decides what matters in
a meeting; that is the distilling agent's job.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from obsidian_wiki.vault import split_frontmatter

#: Spoken filler that carries no content. Removed only as whole words, and only
#: in condensed output; the parsed turns keep the original text.
FILLERS = ("um", "uh", "erm", "uhm", "hmm", "mm-hmm", "you know", "i mean", "sort of", "kind of", "like,")

_TIME = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
_CUE_RE = re.compile(rf"^\s*({_TIME})\s*-->\s*({_TIME})")
_VTT_VOICE_RE = re.compile(r"<v(?:\.[^ >]*)?\s+([^>]+)>(.*?)(?:</v>|$)")
_TAG_RE = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)
_STAMP_PREFIX_RE = re.compile(rf"^\s*[\[(]?({_TIME})[\])]?\s*[-–—]?\s*")
_SPEAKER_RE = re.compile(
    r"^\s*(?:\*\*|__)?(?P<name>[A-Z][\w.'’-]*(?:\s+[\w.'’-]+){0,3}?)(?:\*\*|__)?\s*"
    r"(?:\((?P<paren>[^)]*)\))?\s*(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*(?P<text>.*)$"
)
_OTTER_HEADER_RE = re.compile(rf"^\s*(?P<name>[A-Z][\w.'’-]*(?:\s+[\w.'’-]+){{0,3}})\s+(?P<time>{_TIME})\s*$")
#: Lines a fetching tool wraps around a transcript: ``<<<END TRANSCRIPT>>>``
#: envelopes and ``(...truncated, N chars remaining ...)`` pagination markers.
_ENVELOPE_RE = re.compile(r"^\s*(?:<<<.*>>>|\(\.\.\.\s*truncated\b.*\))\s*$", re.IGNORECASE)
_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_NOT_SPEAKERS = frozenset({
    "note", "notes", "summary", "action items", "agenda", "date", "time", "attendees",
    "participants", "title", "meeting", "transcript", "location", "duration", "http", "https",
})


@dataclass
class Turn:
    speaker: str
    text: str
    start: Optional[float] = None  # seconds from the start of the recording

    def as_dict(self) -> dict:
        return {"speaker": self.speaker, "start": self.start, "text": self.text}


@dataclass
class Transcript:
    format: str
    title: str = ""
    date: str = ""
    turns: list = field(default_factory=list)
    meeting_id: str = ""

    @property
    def speakers(self) -> list:
        seen: dict = {}
        for turn in self.turns:
            if turn.speaker:
                seen[turn.speaker] = seen.get(turn.speaker, 0) + len(turn.text.split())
        return sorted(seen, key=lambda name: (-seen[name], name))

    @property
    def words(self) -> int:
        return sum(len(turn.text.split()) for turn in self.turns)

    @property
    def duration(self) -> Optional[float]:
        stamps = [t.start for t in self.turns if t.start is not None]
        return max(stamps) if stamps else None

    def as_dict(self) -> dict:
        return {
            "format": self.format,
            "meeting_id": self.meeting_id,
            "title": self.title,
            "date": self.date,
            "speakers": self.speakers,
            "words": self.words,
            "duration_seconds": self.duration,
            "turns": [t.as_dict() for t in self.turns],
        }


def _seconds(stamp: str) -> float:
    parts = stamp.replace(",", ".").split(":")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return total


def _clean(text: str) -> str:
    return " ".join(_TAG_RE.sub("", text).split())


def _speaker_candidate(line: str) -> tuple:
    """(speaker, text, bold) when *line* opens with a plausible ``Name:``; else ("", line, False)."""
    match = _SPEAKER_RE.match(line)
    if not match:
        return "", line, False
    name = match.group("name").strip()
    if name.lower() in _NOT_SPEAKERS or "://" in line[: match.end("name") + 3]:
        return "", line, False
    if match.group("paren"):
        name = f"{name} ({match.group('paren').strip()})"
    bold = line.lstrip().startswith(("**", "__"))
    return name, match.group("text").strip(), bold


def _speaker_split(line: str, known: Optional[set] = None) -> tuple:
    """(speaker, text). With *known*, an unbolded label must be a known speaker.

    Dictated notes are full of "Idea: ..." and "Next step: ..."; a real speaker
    label recurs, or is marked up as one.
    """
    name, text, bold = _speaker_candidate(line)
    if not name:
        return "", line
    if known is not None and not bold and name not in known:
        return "", line
    return name, text


def _append(turns: list, speaker: str, text: str, start: Optional[float]) -> None:
    text = _clean(text)
    if not text:
        return
    if turns and not speaker and turns[-1].speaker:
        # A continuation line under the same speaker.
        turns[-1].text = f"{turns[-1].text} {text}"
        return
    turns.append(Turn(speaker, text, start))


def _parse_cues(lines: list, fmt: str) -> list:
    """WebVTT / SRT: timing line, then one or more text lines, blank line ends a cue."""
    turns: list = []
    start: Optional[float] = None
    in_cue = False
    for line in lines:
        cue = _CUE_RE.match(line)
        if cue:
            start, in_cue = _seconds(cue.group(1)), True
            continue
        if not line.strip():
            in_cue = False
            continue
        if not in_cue:
            continue  # WEBVTT header, NOTE blocks, SRT cue numbers, cue identifiers
        voice = _VTT_VOICE_RE.search(line)
        if voice:
            speaker, text = voice.group(1).strip(), voice.group(2)
        else:
            speaker, text = _speaker_split(_clean(line))
        if speaker or not turns:
            _append(turns, speaker, text, start)
        elif turns[-1].start == start:
            turns[-1].text = f"{turns[-1].text} {_clean(text)}"
        else:
            # A new cue with no speaker label: the previous speaker is still talking.
            _append(turns, turns[-1].speaker, text, start)
    return _merge(turns)


def _parse_lines(lines: list) -> tuple:
    """Speaker-line and Otter formats. Returns (format, turns)."""
    turns: list = []
    otter = sum(1 for line in lines if _OTTER_HEADER_RE.match(line))
    labelled = 0
    counts: dict = {}
    for line in lines:
        stripped = _STAMP_PREFIX_RE.sub("", line.strip(), count=1)
        name, _, _ = _speaker_candidate(re.sub(r"^\s*[-*+]\s+", "", stripped))
        if name:
            counts[name] = counts.get(name, 0) + 1
    known = {name for name, count in counts.items() if count >= 2}
    pending: Optional[tuple] = None  # Otter: (speaker, start) awaiting its text
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "---", "|")):
            pending = None if not stripped else pending
            continue
        header = _OTTER_HEADER_RE.match(line) if otter else None
        if header:
            pending = (header.group("name").strip(), _seconds(header.group("time")))
            continue
        start = None
        stamp = _STAMP_PREFIX_RE.match(stripped)
        rest = stripped
        if stamp:
            start, rest = _seconds(stamp.group(1)), stripped[stamp.end():]
        rest = re.sub(r"^\s*[-*+]\s+", "", rest)
        speaker, text = _speaker_split(rest, known)
        if speaker:
            labelled += 1
            _append(turns, speaker, text, start)
            pending = None
        elif pending:
            _append(turns, pending[0], rest, pending[1])
            pending = None
        else:
            _append(turns, "", rest, start)
    fmt = "otter" if otter and otter >= labelled else ("speaker-lines" if labelled else "plain")
    return fmt, _merge(turns)


def _merge(turns: list) -> list:
    """Join consecutive turns by the same speaker; caption files split every few seconds."""
    merged: list = []
    for turn in turns:
        if merged and merged[-1].speaker == turn.speaker:
            merged[-1].text = f"{merged[-1].text} {turn.text}"
        else:
            merged.append(Turn(turn.speaker, turn.text, turn.start))
    return merged


def _meta_value(frontmatter: str, *keys: str) -> str:
    for key in keys:
        match = re.search(rf"^{key}:\s*(.+?)\s*$", frontmatter, re.MULTILINE | re.IGNORECASE)
        if match:
            return match.group(1).strip().strip("\"'")
    return ""


def _transcript_body(body: str) -> str:
    """For a markdown export with a ``## Transcript`` section, only that section."""
    match = re.search(r"^#{1,3}\s+Transcript\s*$", body, re.MULTILINE | re.IGNORECASE)
    if not match:
        return body
    rest = body[match.end():]
    end = re.search(r"^#{1,3}\s+\S", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def parse_transcript(text: str, *, name: str = "") -> Transcript:
    """Parse *text* (the file's contents); *name* is its filename, used for title/date fallback."""
    text = text.lstrip("﻿")
    frontmatter, body = split_frontmatter(text)
    body = "\n".join(line for line in body.splitlines() if not _ENVELOPE_RE.match(line))
    lines = body.splitlines()
    head ="\n".join(lines[:5])
    if lines and lines[0].strip().startswith("WEBVTT"):
        fmt, turns = "vtt", _parse_cues(lines, "vtt")
    elif re.search(r"^\s*\d+\s*$\n\s*" + _TIME + r"\s*-->", head, re.MULTILINE):
        fmt, turns = "srt", _parse_cues(lines, "srt")
    else:
        fmt, turns = _parse_lines(_transcript_body(body).splitlines())

    title = _meta_value(frontmatter, "title", "meeting", "subject")
    if not title:
        heading = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
        title = heading.group(1) if heading else ""
    if (
        not title and fmt in ("otter", "speaker-lines") and len(turns) > 1
        and not turns[0].speaker and len(turns[0].text.split()) <= 10
    ):
        title = turns.pop(0).text  # the heading line of a plain-text export
    stem = Path(name).stem if name else ""
    if not title and stem:
        title = re.sub(r"[-_]+", " ", _DATE_RE.sub("", stem)).strip()

    date_value = _meta_value(frontmatter, "date", "created", "start", "started_at", "meeting_date")
    found = _DATE_RE.search(date_value) or _DATE_RE.search(head) or (_DATE_RE.search(stem) if stem else None)
    meeting_id = _meta_value(frontmatter, "meeting_id", "id", "granola_id", "uid")
    transcript = Transcript(fmt, title, "-".join(found.groups()) if found else "", turns, meeting_id)
    if not transcript.meeting_id:
        digest = hashlib.sha256(
            "\n".join(f"{t.speaker}\t{t.text}" for t in turns).encode("utf-8")
        ).hexdigest()[:16]
        transcript.meeting_id = f"sha256:{digest}"
    return transcript


def _filler_pattern(filler: str) -> re.Pattern:
    # "like," only counts as filler when a comma follows it; "I like it" stays.
    needs_comma = filler.endswith(",")
    words = r"\s+".join(re.escape(w) for w in filler.rstrip(",").split())
    tail = r"\s*," if needs_comma else r"(?![\w'-])\s*,?"
    # A comma just before the filler goes with it: "we, uh, ship" -> "we ship".
    return re.compile(r"(?:,\s*)?(?<![\w'-])" + words + tail, re.IGNORECASE)


_FILLER_PATTERNS = tuple(_filler_pattern(f) for f in FILLERS)


def strip_fillers(text: str) -> str:
    """Drop spoken filler words, then tidy the punctuation they leave behind."""
    out = text
    for pattern in _FILLER_PATTERNS:
        out = pattern.sub(" ", out)
    out = re.sub(r"\s+([,.!?;:])", r"\1", out)
    out = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", out)
    out = re.sub(r"^[\s,;:]+", "", out)
    out = " ".join(out.split())
    if not re.search(r"\w", out):
        return ""
    return out[:1].upper() + out[1:] if out and text[:1].isupper() else out


def _clock(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def render_condensed(transcript: Transcript, *, fillers: bool = False) -> str:
    """Compact markdown: a header, then one paragraph per speaker turn."""
    lines = [f"# {transcript.title or 'Untitled meeting'}", ""]
    meta = [f"date: {transcript.date or 'unknown'}", f"format: {transcript.format}", f"id: {transcript.meeting_id}"]
    if transcript.speakers:
        meta.append("speakers: " + ", ".join(transcript.speakers))
    if transcript.duration is not None:
        meta.append(f"duration: {_clock(transcript.duration)}")
    meta.append(f"words: {transcript.words}")
    lines += [f"- {item}" for item in meta] + [""]
    for turn in transcript.turns:
        text = turn.text if fillers else strip_fillers(turn.text)
        if not text:
            continue
        stamp = f"[{_clock(turn.start)}] " if turn.start is not None else ""
        who = f"**{turn.speaker}:** " if turn.speaker else ""
        lines.append(f"{stamp}{who}{text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
