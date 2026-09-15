"""Every text file read/write in the package must name its encoding.

`pathlib.read_text()` and `open()` without `encoding=` fall back to the locale
encoding, which is GBK on a Chinese Windows install and cp1252 on a Western one.
A UTF-8 config, manifest key or vault page then raises UnicodeDecodeError on
read, or is written back mangled (issue #213). The check is static rather than
behavioural because the failure only reproduces under a non-UTF-8 locale, which
CI does not have — so a runtime test would pass with or without the fix.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED_DIRS = ("obsidian_wiki", "scripts", "tools")
TEXT_PATH_METHODS = {"read_text", "write_text"}


def _is_binary_mode(call: ast.Call) -> bool:
    """True if an `open()` call is in binary mode, where `encoding=` is illegal."""
    mode = next(
        (kw.value for kw in call.keywords if kw.arg == "mode"),
        call.args[1] if len(call.args) > 1 else None,
    )
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value


def _offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in TEXT_PATH_METHODS:
            name = f"Path.{func.attr}"
        elif isinstance(func, ast.Name) and func.id == "open":
            if _is_binary_mode(node):
                continue
            name = "open"
        else:
            continue
        if not any(kw.arg == "encoding" for kw in node.keywords):
            rel = path.relative_to(REPO_ROOT)
            found.append(f"{rel}:{node.lineno}: {name}() without encoding=")
    return found


def test_no_locale_dependent_text_io() -> None:
    offenders: list[str] = []
    for directory in SCANNED_DIRS:
        for path in sorted((REPO_ROOT / directory).rglob("*.py")):
            if any(part.startswith(".") for part in path.parts):
                continue  # venvs, caches, editor sidecars — not shipped source
            offenders.extend(_offenders(path))
    assert not offenders, (
        "Text I/O without an explicit encoding uses the locale default and breaks "
        "on non-UTF-8 systems (see issue #213):\n  " + "\n  ".join(offenders)
    )
