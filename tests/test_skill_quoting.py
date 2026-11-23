"""Skill examples must single-quote free text passed to `obsidian-wiki memory|facts`.

Inside double quotes the shell expands `$(...)`, backticks and `$4`, so a title
or fact an agent pastes in can run a command or lose characters. Variables meant
to expand ("$OBSIDIAN_VAULT_PATH") are fine; placeholders and dollar amounts are not.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SINGLE = re.compile(r"'[^'\n]*'")
DOUBLE = re.compile(r'"[^"\n]*"')
RISKY = re.compile(r"<[^>\n]*>|\$\d")


def _risky(line: str) -> bool:
    # Drop single-quoted spans first so only real double-quoted strings are paired.
    return any(RISKY.search(m.group()) for m in DOUBLE.finditer(SINGLE.sub("", line)))


def _risky_lines():
    for path in [*(ROOT / "skills").rglob("*.md"), *(ROOT / "docs").glob("*.md")]:
        if "/evals/" in str(path):
            continue
        cont = False
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            starts = re.search(r"obsidian-wiki (memory|facts)\b", line) and "lifecycle_changed" not in line
            if (starts or cont) and _risky(line):
                yield f"{path.relative_to(ROOT)}:{n}: {line.strip()[:100]}"
            cont = bool(starts or cont) and line.rstrip().endswith("\\")


def test_free_text_in_memory_commands_is_single_quoted():
    assert not list(_risky_lines()), "double-quoted free text in:\n" + "\n".join(_risky_lines())
