"""Tell the user when a newer obsidian-wiki is on PyPI.

Checks PyPI at most once a day and caches the answer next to the global
config. Every failure is silent: no network, a slow PyPI or an unreadable cache
only mean no notice, never a broken command. Set
``OBSIDIAN_WIKI_NO_UPDATE_CHECK=1`` to switch the check off; CI runs skip it too.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

PYPI_URL = "https://pypi.org/pypi/obsidian-wiki/json"
CHECK_INTERVAL = 24 * 60 * 60
TIMEOUT = 2.0
UPGRADE_HINT = "pipx upgrade obsidian-wiki  (or: uv tool upgrade obsidian-wiki / pip install -U obsidian-wiki)"


def _key(version: str) -> tuple:
    """Order release versions; a dev/pre build sorts below its release.

    ``2026.11.4.dev4+gabc`` -> ((2026, 11, 4), 0), ``2026.11.4`` -> ((2026, 11, 4), 1).
    """
    m = re.match(r"(\d+(?:\.\d+)*)(.*)", version.strip())
    if not m:
        return ((), 0)
    release = tuple(int(p) for p in m.group(1).split("."))
    return (release, 0 if m.group(2).lstrip(".+") else 1)


def is_newer(latest: str, current: str) -> bool:
    return bool(latest) and _key(latest) > _key(current)


def _fetch_latest() -> str:
    req = urllib.request.Request(PYPI_URL, headers={"User-Agent": "obsidian-wiki-update-check"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return str(json.load(resp)["info"]["version"])


def latest_version(cache_file: Path, now: float | None = None) -> str:
    """The newest PyPI version, from a cache younger than a day or a fresh fetch."""
    now = time.time() if now is None else now
    cached: dict = {}
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if "checked_at" in cached and now - float(cached["checked_at"]) < CHECK_INTERVAL:
        return str(cached.get("latest", ""))
    try:
        latest = _fetch_latest()
    except Exception:
        latest = str(cached.get("latest", ""))
    # Record the attempt even when it failed, so an offline machine pays the
    # timeout once a day rather than on every command.
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"checked_at": now, "latest": latest}), encoding="utf-8")
    except OSError:
        pass
    return latest


def notice(current: str, cache_file: Path) -> str:
    """One line to print when an upgrade exists, else ``""``."""
    if os.environ.get("OBSIDIAN_WIKI_NO_UPDATE_CHECK", "").strip() not in ("", "0", "false") or os.environ.get("CI"):
        return ""
    latest = latest_version(cache_file)
    if not is_newer(latest, current):
        return ""
    return f"⬆️  obsidian-wiki {latest} is available (you have {current}). Upgrade: {UPGRADE_HINT}"

