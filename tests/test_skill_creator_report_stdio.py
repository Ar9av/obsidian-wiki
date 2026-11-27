"""generate_report.py must read stdin and write stdout as UTF-8.

The report HTML always contains the check and cross marks (U+2713 / U+2717), and
a query or description can hold any script. When stdin/stdout are a pipe or a
redirect, Python uses the locale code page (cp1252 on Western Windows), so the
script crashed with UnicodeEncodeError or decoded the JSON as mojibake. The
child process is forced to a cp1252 stream encoding so the test fails the same
way on any OS.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "skill-creator" / "scripts" / "generate_report.py"

QUERY = "résumé de 日本語"


def _run(args: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "0"
    env["PYTHONIOENCODING"] = "cp1252"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=60,
    )


def _loop_output() -> dict:
    return {
        "original_description": "d",
        "best_description": "d",
        "best_score": "1/1",
        "iterations_run": 1,
        "holdout": 0,
        "train_size": 1,
        "test_size": 0,
        "history": [
            {
                "iteration": 1,
                "description": QUERY,
                "train_passed": 1,
                "train_total": 1,
                "train_results": [
                    {"query": QUERY, "should_trigger": True, "pass": True, "triggers": 1, "runs": 1}
                ],
            }
        ],
    }


def test_stdout_is_utf8_when_redirected(tmp_path: Path) -> None:
    src = tmp_path / "loop.json"
    src.write_text(json.dumps(_loop_output(), ensure_ascii=False), encoding="utf-8")
    result = _run([str(src)])
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    html = result.stdout.decode("utf-8")
    assert "✓" in html
    assert QUERY in html


def test_stdin_is_read_as_utf8() -> None:
    payload = json.dumps(_loop_output(), ensure_ascii=False).encode("utf-8")
    result = _run(["-"], stdin=payload)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert QUERY in result.stdout.decode("utf-8")
