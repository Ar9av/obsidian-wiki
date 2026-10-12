"""The wiki clock: every stamp the memory writer puts in a vault comes from here.

A vault keeps its timezone in the frontmatter of its ``index.md``::

    ---
    title: Wiki Index
    timezone: America/Detroit
    ---

Without the key the writer keeps its original behavior: UTC, in the ``Z``
spelling (``2026-10-10T18:40:37Z``), and bare dates are UTC calendar days.
With it, every stamp carries the zone's own offset for that instant
(``2026-10-10T14:40:37-04:00``), so daylight-saving transitions are right by
construction, and a bare date (``created:`` on a profile fact, ``touched`` on a
todo) is the calendar day *there* rather than in UTC — the difference that
puts an evening's work on tomorrow's date for anyone west of Greenwich.

The setting lives in the file it governs, like ``index_folder_hubs``: it
travels with the vault and applies to every writer — CLI, server, Python API —
whatever ``.env`` the caller resolved. ``rebuild_index`` preserves the
frontmatter, so the key survives every regeneration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from obsidian_wiki.vault import split_frontmatter

TIMEZONE_KEY = "timezone"
_TIMEZONE_LINE = re.compile(rf"^{TIMEZONE_KEY}:[ \t]*(?P<value>.*)$", re.MULTILINE)


class TimezoneError(ValueError):
    """``timezone:`` names a zone this Python cannot resolve."""


def parse_timezone(name: str) -> Optional[tzinfo]:
    """IANA name → tzinfo. Empty or ``UTC`` → ``None``, meaning the default.

    ``None`` rather than ``timezone.utc`` so callers can tell "nothing
    configured" from a zone, and keep writing the ``Z`` spelling for it.
    """
    value = (name or "").strip().strip("\"'")
    if not value or value.upper() in {"UTC", "Z"}:
        return None
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise TimezoneError(
            f"unknown timezone {value!r} in index.md; use an IANA name such as America/Detroit"
        ) from exc


def timezone_name(vault: Union[str, Path]) -> str:
    """The configured zone name, or ``""`` when the vault runs on the default."""
    index = Path(vault) / "index.md"
    if not index.is_file():
        return ""
    frontmatter, _body = split_frontmatter(index.read_text(encoding="utf-8", errors="replace"))
    match = _TIMEZONE_LINE.search(frontmatter)
    return match.group("value").strip().strip("\"'") if match else ""


def wiki_timezone(vault: Union[str, Path]) -> Optional[tzinfo]:
    """The vault's zone from ``index.md``, or ``None`` for the UTC default.

    Raises :class:`TimezoneError` when the key names a zone that does not
    exist — a typo must not silently write UTC under a local label.
    """
    return parse_timezone(timezone_name(vault))


def set_timezone(vault: Union[str, Path], name: str) -> str:
    """Write ``timezone: <name>`` into the frontmatter of the vault's ``index.md``.

    Validates the name first, so a typo never lands in the file. Replaces an
    existing key, otherwise inserts it after ``title:``; an ``index.md`` with
    no frontmatter gets one. An empty name is a no-op. Returns the stored name.
    """
    value = (name or "").strip().strip("\"'")
    if not value:
        return ""
    parse_timezone(value)  # raises TimezoneError on an unknown zone
    index = Path(vault) / "index.md"
    if not index.is_file():
        raise FileNotFoundError(f"no index.md in {vault}; scaffold the vault first")
    from obsidian_wiki.memory import atomic_write  # lazy: memory imports this module

    text = index.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    line = f"{TIMEZONE_KEY}: {value}"
    if _TIMEZONE_LINE.search(frontmatter):
        frontmatter = _TIMEZONE_LINE.sub(line, frontmatter, count=1)
    elif frontmatter.strip():
        lines = frontmatter.rstrip("\n").split("\n")
        at = next((i + 1 for i, l in enumerate(lines) if l.startswith("title:")), len(lines))
        lines.insert(at, line)
        frontmatter = "\n".join(lines)
    else:
        frontmatter = f"title: Wiki Index\n{line}"
    if text.startswith("---"):
        rest = text.split("---", 2)[2] if text.count("---") >= 2 else body
        atomic_write(index, f"---\n{frontmatter.strip()}\n---{rest}")
    else:
        atomic_write(index, f"---\n{frontmatter.strip()}\n---\n\n{text}")
    return value


def _moment(now: Optional[datetime]) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("clock needs an aware datetime; attach a timezone first")
    return moment


def stamp(tz: Optional[tzinfo] = None, *, now: Optional[datetime] = None) -> str:
    """Full timestamp to the second: ``…Z`` on the default, ``…-04:00`` in a zone."""
    moment = _moment(now)
    if tz is None:
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return moment.astimezone(tz).isoformat(timespec="seconds")


def today(tz: Optional[tzinfo] = None, *, now: Optional[datetime] = None) -> str:
    """Bare calendar date in the zone (UTC on the default)."""
    return _moment(now).astimezone(tz or timezone.utc).date().isoformat()


def compact(tz: Optional[tzinfo] = None, *, now: Optional[datetime] = None) -> str:
    """Filesystem-safe form for backup directory names: ``20261010T184037Z``."""
    moment = _moment(now)
    if tz is None:
        return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return moment.astimezone(tz).strftime("%Y%m%dT%H%M%S%z")


# --------------------------------------------------------------------------
# converting the stamps already in a vault
# --------------------------------------------------------------------------

#: A full ISO-8601 timestamp with a zone: ``2026-10-10T18:40:37Z``,
#: ``2026-10-10T14:40:37-04:00``, ``2026-10-10T14:40:37.123-0400``. Bare dates,
#: naive stamps (no zone) and the compact backup-directory form
#: (``20261010T184037Z``) deliberately do not match: the first two cannot be
#: converted without guessing, the last names a directory that exists.
STAMP_RE = re.compile(
    r"(?<![\w/])"
    r"(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)"
    r"(?P<zone>Z|[+-]\d{2}:?\d{2})"
    r"(?!\w)"
)
_NAIVE_RE = re.compile(r"(?<![\w/])\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?![\w:+-])")


@dataclass(frozen=True)
class StampChange:
    line: int   # 1-based
    old: str
    new: str


def convert_stamp(text: str, tz: Optional[tzinfo]) -> Optional[str]:
    """Re-render one full stamp in *tz* (``Z`` form when *tz* is ``None``).

    Returns ``None`` when the text is not a parseable zoned stamp. The instant
    is preserved; only the spelling changes, so a stamp already in the zone
    comes back unchanged and a second run is a no-op.
    """
    match = STAMP_RE.fullmatch(text.strip())
    if not match:
        return None
    time = match.group("time")
    if time.count(":") == 1:
        time += ":00"
    zone = match.group("zone")
    if zone == "Z":
        zone = "+00:00"
    elif ":" not in zone:
        zone = f"{zone[:3]}:{zone[3:]}"
    try:
        moment = datetime.fromisoformat(f"{match.group('date')}T{time}{zone}")
    except ValueError:
        return None
    return stamp(tz, now=moment)


def convert_text(text: str, tz: Optional[tzinfo]) -> "tuple[str, list, int]":
    """Every zoned stamp in *text* re-rendered in *tz*.

    Returns ``(new_text, changes, naive)``: the converted text, one
    :class:`StampChange` per stamp whose spelling changed, and how many naive
    stamps (no zone, so no conversion possible) were seen and left alone.
    """
    changes: list = []
    out_lines = []
    naive = 0
    for number, line in enumerate(text.split("\n"), start=1):
        naive += len(_NAIVE_RE.findall(line))

        def _swap(match: "re.Match[str]") -> str:
            old = match.group(0)
            new = convert_stamp(old, tz)
            if new is None or new == old:
                return old
            changes.append(StampChange(number, old, new))
            return new

        out_lines.append(STAMP_RE.sub(_swap, line))
    return "\n".join(out_lines), changes, naive
