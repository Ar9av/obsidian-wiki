"""Bi-temporal validity for vault pages.

`created`/`updated` are *ingestion* time — when the vault learned something.
`valid_from`/`valid_until` are *event* time — when the claim itself was true.
Together they make a page's history answerable: a page whose `valid_until` has
passed is historical, not wrong, and it stays in the vault (and in the graph)
instead of being overwritten. `superseded_by` names what replaced it.

All three fields are optional. A page carrying none of them is current,
always — which is every page in a vault that predates this module.

Retrieval reads these through `is_current`; `lint` reads them through
`validity_window` to report malformed dates.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Mapping

TEMPORAL_FIELDS = ("valid_from", "valid_until")
SUPERSEDED_FIELD = "superseded_by"

__all__ = [
    "SUPERSEDED_FIELD",
    "TEMPORAL_FIELDS",
    "is_current",
    "parse_date",
    "superseded_target",
    "validity_window",
]


def parse_date(raw: str) -> "date | None":
    """Parse `YYYY-MM-DD` or a full ISO 8601 timestamp down to a date.

    Returns None for an empty value. Raises ValueError on a non-empty value
    that isn't a date, so callers can report it as malformed metadata rather
    than guessing.
    """
    value = (raw or "").strip().strip("\"'")
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        # `2026-04-01T09:30:00+00:00`. The `Z` spelling is rejected by
        # fromisoformat before 3.11, so normalise it first.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def validity_window(values: Mapping[str, str]) -> "tuple[date | None, date | None]":
    """`(valid_from, valid_until)` for a frontmatter mapping.

    Raises ValueError if either date is malformed or the window is inverted.
    """
    start = parse_date(values.get("valid_from", ""))
    end = parse_date(values.get("valid_until", ""))
    if start and end and end < start:
        raise ValueError(
            f"valid_until ({end.isoformat()}) precedes valid_from ({start.isoformat()})"
        )
    return start, end


def is_current(values: Mapping[str, str], as_of: "date | None" = None) -> bool:
    """Was this page's claim true at `as_of` (default today)?

    `valid_until` is inclusive — the last day the claim held, the way a person
    writing the date means it. A page with malformed dates counts as current:
    retrieval must never silently drop a page over a typo, and `lint` is what
    reports the typo.
    """
    try:
        start, end = validity_window(values)
    except ValueError:
        return True
    when = as_of or date.today()
    if start and when < start:
        return False
    if end and when > end:
        return False
    return True


def superseded_target(raw: str) -> str:
    """Bare page name from a `superseded_by` value, `[[wikilink]]` or plain.

    Returns the last path segment with any `.md`, alias, and heading anchor
    stripped. Callers apply their own slugging.
    """
    target = (raw or "").strip().strip("\"'")
    target = target.removeprefix("[[").removesuffix("]]")
    target = target.split("|", 1)[0].split("#", 1)[0].strip()
    return target.removesuffix(".md").split("/")[-1].strip()
