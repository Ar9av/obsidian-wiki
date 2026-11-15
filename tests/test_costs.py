"""Tests for cost per job: recording agent-run spend and the per-job report."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from obsidian_wiki import costs as cx

ROOT = Path(__file__).resolve().parents[1]
# A real `claude -p --output-format json` result, session ids stripped.
CLAUDE_RESULT = ROOT / "tests" / "fixtures" / "costs" / "claude-print-result.json"


def _log(vault: Path, *lines: str) -> None:
    (vault / "log.md").write_text("# Wiki Log\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


def test_parse_claude_result() -> None:
    figures = cx.parse_run_output(CLAUDE_RESULT.read_text(encoding="utf-8"))
    assert figures["cost_usd"] == pytest.approx(0.0054457)
    assert figures["tokens_in"] == 2 + 26219 + 11370  # cache reads and writes count as input
    assert figures["tokens_out"] == 176
    assert figures["duration_s"] == 7.5
    assert figures["turns"] == 1
    assert "error" not in figures


def test_parse_error_result_and_jsonl_events() -> None:
    error = {"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 0.05, "usage": {}}
    assert cx.parse_run_output(json.dumps(error))["error"] == "error_max_budget_usd"

    events = "\n".join([
        json.dumps({"type": "thread.started"}),
        "not json",
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}),
        json.dumps({"type": "turn.completed", "usage": {"prompt_tokens": 50, "completion_tokens": 5}}),
    ])
    figures = cx.parse_run_output(events)
    assert (figures["tokens_in"], figures["tokens_out"]) == (150, 25)
    assert "cost_usd" not in figures

    with pytest.raises(cx.CostError, match="no run result"):
        cx.parse_run_output('{"hello": "world"}')
    with pytest.raises(cx.CostError, match="empty"):
        cx.parse_run_output("  ")


def test_record_writes_a_cost_line(tmp_path: Path) -> None:
    line = cx.record_cost(tmp_path, "playbook_review", {"cost_usd": 0.0054457, "tokens_out": 176.0, "turns": 1.0},
                          {"source": "cron"})
    assert "COST job=PLAYBOOK_REVIEW cost_usd=0.005446 tokens_out=176 turns=1 source=cron" in line
    assert line in (tmp_path / "log.md").read_text(encoding="utf-8")

    with pytest.raises(cx.CostError, match="nothing to record"):
        cx.record_cost(tmp_path, "INGEST", {})
    with pytest.raises(cx.CostError, match="log verb"):
        cx.record_cost(tmp_path, "rm -rf", {"cost_usd": 1})


def test_report_joins_spend_with_output(tmp_path: Path) -> None:
    _log(
        tmp_path,
        "- [2026-10-01T09:00:00Z] INGEST source=old.pdf pages_created=9",  # outside the window
        "- [2026-11-10T09:00:00Z] INGEST source=a.pdf pages_created=3 pages_updated=2",
        "- [2026-11-10T09:05:00Z] COST job=INGEST cost_usd=0.50 tokens_in=1000 tokens_out=200 duration_s=60",
        "- [2026-11-11T09:00:00Z] INGEST source=b.pdf pages_created=1",
        "- [2026-11-11T09:05:00Z] COST job=INGEST cost_usd=0.30 duration_s=30",
        "- [2026-11-12T09:00:00Z] PLAYBOOK_REVIEW since=2026-11-05 staged=0",
        "- [2026-11-12T09:10:00Z] COST job=PLAYBOOK_REVIEW cost_usd=1.20",
        "- [2026-11-13T09:00:00Z] DIGEST period=7d cost_usd=0.05",       # cost on the job's own line
        "- [2026-11-14T03:00:00Z] COST job=NIGHTLY_SYNC cost_usd=0.10 error=error_during_execution",
        "- [2026-11-14T09:00:00Z] QUERY q=x",                              # never priced
    )
    report = cx.cost_report(tmp_path, since=date(2026, 11, 1), max_cost_per_output=0.25)
    rows = {r["job"]: r for r in report["jobs"]}

    ingest = rows["INGEST"]
    assert (ingest["runs"], ingest["priced_runs"], ingest["output"]) == (2, 2, 6)
    assert ingest["cost_usd"] == 0.8 and ingest["cost_per_run"] == 0.4
    assert ingest["cost_per_output"] == pytest.approx(0.1333, abs=1e-4)
    assert (ingest["tokens_in"], ingest["tokens_out"], ingest["duration_s"]) == (1000, 200, 90.0)
    assert ingest["flags"] == []

    assert rows["PLAYBOOK_REVIEW"]["flags"] == ["no_output"]
    assert rows["DIGEST"]["cost_usd"] == 0.05 and rows["DIGEST"]["flags"] == ["no_output"]
    nightly = rows["NIGHTLY_SYNC"]
    assert nightly["runs"] == 1 and nightly["errors"] == 1 and "errors" in nightly["flags"]
    assert rows["QUERY"]["cost_usd"] is None and rows["QUERY"]["flags"] == []

    assert report["total_cost_usd"] == pytest.approx(2.15)
    assert [r["job"] for r in report["jobs"]][0] == "PLAYBOOK_REVIEW"  # most spend first
    assert set(report["flagged"]) == {"PLAYBOOK_REVIEW", "DIGEST", "NIGHTLY_SYNC"}


def test_over_budget_flag(tmp_path: Path) -> None:
    _log(
        tmp_path,
        "- [2026-11-10T09:00:00Z] INGEST pages_created=1",
        "- [2026-11-10T09:05:00Z] COST job=INGEST cost_usd=2.00",
    )
    rows = cx.cost_report(tmp_path, since=date(2026, 11, 1), max_cost_per_output=0.5)["jobs"]
    assert rows[0]["flags"] == ["over_budget"]
    assert cx.cost_report(tmp_path, since=date(2026, 11, 1))["jobs"][0]["flags"] == []


def test_empty_log(tmp_path: Path) -> None:
    report = cx.cost_report(tmp_path, since=date(2026, 11, 1))
    assert report["jobs"] == [] and report["total_cost_usd"] is None
    assert "no log entries" in cx.render_text(report)


@pytest.mark.parametrize(("value", "expected"), [("30d", date(2026, 10, 16)), ("4w", date(2026, 10, 18)), ("2026-11-01", date(2026, 11, 1))])
def test_parse_window(value: str, expected: date) -> None:
    assert cx.parse_window(value, today=date(2026, 11, 15)) == expected


def _cli(vault: Path, *argv: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, CI="true", PYTHONPATH=str(ROOT))
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "costs", *argv, "--vault", str(vault)],
        input=stdin, capture_output=True, text=True, cwd=ROOT, env=env,
    )


def test_cli_record_and_report(tmp_path: Path) -> None:
    (tmp_path / "log.md").write_text("# Wiki Log\n\n", encoding="utf-8")
    recorded = _cli(tmp_path, "record", "PLAYBOOK_REVIEW", "source=cron", "--from-json", str(CLAUDE_RESULT))
    assert recorded.returncode == 0, recorded.stderr
    assert "COST job=PLAYBOOK_REVIEW cost_usd=0.005446" in recorded.stdout

    piped = _cli(tmp_path, "record", "INGEST", "--from-json", "-", "--cost-usd", "0.25",
                 stdin=CLAUDE_RESULT.read_text(encoding="utf-8"))
    assert "cost_usd=0.25" in piped.stdout  # the flag overrides the JSON

    report = _cli(tmp_path, "report", "--since", "1d", "--json")
    assert report.returncode == 0, report.stderr
    payload = json.loads(report.stdout)
    assert {r["job"] for r in payload["jobs"]} == {"PLAYBOOK_REVIEW", "INGEST"}

    gated = _cli(tmp_path, "report", "--since", "1d", "--fail-on-flagged")
    assert gated.returncode == 2
    assert "fix or kill: " in gated.stdout

    assert _cli(tmp_path, "record").returncode == 1
    assert _cli(tmp_path, "record", "INGEST").returncode == 1
    assert _cli(tmp_path, "report", "--since", "lately").returncode == 1
