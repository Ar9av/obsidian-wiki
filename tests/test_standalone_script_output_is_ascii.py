"""Standalone helper scripts must print ASCII.

`obsidian_wiki.cli.main` calls `_configure_console_output()`, which sets
`errors="replace"` on stdout/stderr so a non-UTF-8 console degrades the status
emoji instead of crashing. The scripts under `scripts/` and `tools/` are
separate entry points that never reach that guard, so a non-ASCII character in
anything they print raises UnicodeEncodeError under an ASCII or GBK locale —
`scripts/manifest.py migrate` exited 1 on an em dash. Keeping their printed
strings ASCII is cheaper than giving every script a console guard.

Only string literals passed to `print()` are checked; comments, docstrings and
data are free to use whatever they like.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED_DIRS = ("scripts", "tools")


def _non_ascii_prints(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "print":
            continue
        for part in ast.walk(node):
            if not (isinstance(part, ast.Constant) and isinstance(part.value, str)):
                continue
            offenders = sorted({c for c in part.value if ord(c) > 127})
            if offenders:
                rel = path.relative_to(REPO_ROOT)
                glyphs = " ".join(f"{c!r} (U+{ord(c):04X})" for c in offenders)
                found.append(f"{rel}:{node.lineno}: {glyphs}")
    return found


def test_standalone_scripts_print_ascii_only() -> None:
    offenders: list[str] = []
    for directory in SCANNED_DIRS:
        for path in sorted((REPO_ROOT / directory).rglob("*.py")):
            if any(part.startswith(".") for part in path.parts):
                continue
            offenders.extend(_non_ascii_prints(path))
    assert not offenders, (
        "These scripts run outside the CLI's console guard, so a non-ASCII "
        "character in printed output raises UnicodeEncodeError on a non-UTF-8 "
        "console (see issue #219):\n  " + "\n  ".join(offenders)
    )
