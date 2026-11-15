"""Cost per job: what each recurring wiki job spends, and what it produces.

Scheduled agent runs (the daily update, the weekly playbook review, a nightly
meeting ingest) cost real money every time they fire, and nothing in the vault
said how much, or whether the run produced anything. A job that costs more than
it earns should be fixed or killed, and that takes a number.

Two halves, both over ``log.md``:

``record``
    Appends one ``COST job=<VERB> cost_usd=... tokens_in=... tokens_out=...
    duration_s=... turns=...`` line. The numbers come from the agent CLI's own
    JSON result (``claude -p --output-format json``: ``total_cost_usd``,
    ``usage``, ``duration_ms``, ``num_turns``), from any JSON/JSONL with a
    ``usage`` object, or from flags.
``report``
    Joins the COST lines with the job's own log lines in a window. Cost comes
    from COST lines, or from cost fields a job put on its own line. Output is the
    pages the job says it wrote (``pages_created``, ``pages_updated``, ``staged``,
    ...). Per job: runs, spend, tokens, time, output, cost per output, and a flag
    when a job spent money and produced nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from obsidian_wiki.memory import append_log, read_log

COST_VERB = "COST"
#: Log fields that count as a job's output.
OUTPUT_FIELDS = ("pages_created", "pages_updated", "pages_written", "staged", "promoted", "todos_added")
#: Fields that carry spend, on a COST line or on a job's own line.
COST_FIELDS = ("cost_usd", "tokens_in", "tokens_out", "duration_s", "turns")


class CostError(ValueError):
    """Run output that can't be read as a cost record."""


def parse_window(value: str, *, today: date) -> date:
    """``30d`` / ``4w`` / ``YYYY-MM-DD`` -> the first day of the report window."""
    value = value.strip().lower()
    match = re.fullmatch(r"(\d+)\s*([dw])", value)
    if match:
        return today - timedelta(days=int(match.group(1)) * (7 if match.group(2) == "w" else 1))
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise CostError(f"--since must be like 30d, 4w or YYYY-MM-DD: {value!r}") from None


def vault_today(vault: Path) -> date:
    from obsidian_wiki import clock

    return date.fromisoformat(clock.today(clock.wiki_timezone(vault)))


def _number(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip().strip("\"'"))
    except ValueError:
        return None


def _usage_tokens(usage: dict) -> tuple:
    """(input incl. cache, output) from an Anthropic- or OpenAI-style usage object."""
    tokens_in = sum(
        _number(usage.get(key)) or 0
        for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "prompt_tokens")
    )
    tokens_out = sum(_number(usage.get(key)) or 0 for key in ("output_tokens", "completion_tokens"))
    return tokens_in, tokens_out


def parse_run_output(text: str) -> dict:
    """Spend figures from an agent CLI's JSON result, or from JSONL events with ``usage``.

    Returns any of ``cost_usd``, ``tokens_in``, ``tokens_out``, ``duration_s``,
    ``turns``, plus ``error`` when the run reported one. Raises when nothing in
    *text* looks like a run result.
    """
    text = text.strip()
    if not text:
        raise CostError("run output is empty")
    objects = []
    try:
        parsed = json.loads(text)
        objects = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                objects.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    objects = [o for o in objects if isinstance(o, dict)]
    # A Claude Code result object carries the run's totals; prefer it over summing events.
    results = [o for o in objects if o.get("type") == "result" and "total_cost_usd" in o]
    out: dict = {}
    if results:
        result = results[-1]
        out["cost_usd"] = _number(result.get("total_cost_usd"))
        tokens_in, tokens_out = _usage_tokens(result.get("usage") or {})
        out["tokens_in"], out["tokens_out"] = tokens_in, tokens_out
        duration = _number(result.get("duration_ms"))
        if duration is not None:
            out["duration_s"] = round(duration / 1000, 1)
        turns = _number(result.get("num_turns"))
        if turns is not None:
            out["turns"] = turns
        if result.get("is_error"):
            out["error"] = str(result.get("subtype") or "error")
    else:
        tokens_in = tokens_out = 0.0
        found = False
        for obj in objects:
            usage = obj.get("usage")
            if not isinstance(usage, dict):
                usage = (obj.get("msg") or {}).get("usage") if isinstance(obj.get("msg"), dict) else None
            if isinstance(usage, dict):
                found = True
                add_in, add_out = _usage_tokens(usage)
                tokens_in += add_in
                tokens_out += add_out
            cost = _number(obj.get("cost_usd") or obj.get("total_cost_usd"))
            if cost is not None:
                found = True
                out["cost_usd"] = (out.get("cost_usd") or 0) + cost
        if not found:
            raise CostError("no run result found: expected a JSON result with total_cost_usd, or events with usage")
        out["tokens_in"], out["tokens_out"] = tokens_in, tokens_out
    return {k: v for k, v in out.items() if v is not None}


def _fmt_field(value) -> str:
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".") if not value.is_integer() else str(int(value))
    return str(value)


def record_cost(vault: Path, job: str, figures: dict, extra: Optional[dict] = None) -> str:
    """Append a COST line for *job*. Returns the line written."""
    job = job.strip().upper()
    if not job or not job.replace("_", "").replace("-", "").isalnum():
        raise CostError(f"job must be a log verb like INGEST or PLAYBOOK_REVIEW, got {job!r}")
    fields = {"job": job}
    for key in (*COST_FIELDS, "error"):
        if key in figures and figures[key] is not None:
            fields[key] = _fmt_field(figures[key])
    if len(fields) == 1:
        raise CostError("nothing to record: pass --from-json, or one of --cost-usd / --tokens-in / --tokens-out / --duration-s")
    for key, value in (extra or {}).items():
        fields.setdefault(key, value)
    return append_log(vault, COST_VERB, fields)


@dataclass
class JobCost:
    job: str
    runs: int = 0
    cost_runs: int = 0
    cost_usd: float = 0.0
    tokens_in: float = 0.0
    tokens_out: float = 0.0
    duration_s: float = 0.0
    output: float = 0.0
    errors: int = 0
    last: str = ""
    priced: bool = field(default=False)

    def as_dict(self, *, max_cost_per_output: Optional[float] = None) -> dict:
        per_run = self.cost_usd / self.cost_runs if self.cost_runs else None
        per_output = self.cost_usd / self.output if self.output and self.priced else None
        flags = []
        if self.priced and self.cost_usd > 0 and self.output == 0:
            flags.append("no_output")
        if max_cost_per_output is not None and per_output is not None and per_output > max_cost_per_output:
            flags.append("over_budget")
        if self.errors:
            flags.append("errors")
        return {
            "job": self.job,
            "runs": self.runs,
            "priced_runs": self.cost_runs,
            "cost_usd": round(self.cost_usd, 4) if self.priced else None,
            "cost_per_run": round(per_run, 4) if per_run is not None else None,
            "tokens_in": int(self.tokens_in),
            "tokens_out": int(self.tokens_out),
            "duration_s": round(self.duration_s, 1),
            "output": int(self.output),
            "cost_per_output": round(per_output, 4) if per_output is not None else None,
            "errors": self.errors,
            "last": self.last,
            "flags": flags,
        }


def _entry_date(stamp: str) -> Optional[date]:
    try:
        return date.fromisoformat(stamp.strip()[:10])
    except ValueError:
        return None


def cost_report(vault: Path, *, since: date, max_cost_per_output: Optional[float] = None) -> dict:
    jobs: dict = {}

    def job(name: str) -> JobCost:
        return jobs.setdefault(name, JobCost(name))

    def add_spend(target: JobCost, fields: dict) -> None:
        values = {key: _number(fields.get(key)) for key in COST_FIELDS}
        if all(v is None for v in values.values()):
            return
        target.cost_runs += 1
        if values["cost_usd"] is not None:
            target.cost_usd += values["cost_usd"]
            target.priced = True
        target.tokens_in += values["tokens_in"] or 0
        target.tokens_out += values["tokens_out"] or 0
        target.duration_s += values["duration_s"] or 0
        if fields.get("error"):
            target.errors += 1

    cost_only: dict = {}
    for entry in read_log(vault):
        stamp = _entry_date(entry.timestamp)
        if stamp is None or stamp < since:
            continue
        if entry.verb == COST_VERB:
            name = str(entry.fields.get("job", "")).strip().upper() or "UNKNOWN"
            target = job(name)
            add_spend(target, entry.fields)
            cost_only[name] = cost_only.get(name, 0) + 1
            target.last = max(target.last, entry.timestamp)
            continue
        target = job(entry.verb)
        target.runs += 1
        target.last = max(target.last, entry.timestamp)
        target.output += sum(_number(entry.fields.get(key)) or 0 for key in OUTPUT_FIELDS)
        add_spend(target, entry.fields)
    # A job that only ever logged COST lines still ran.
    for name, count in cost_only.items():
        if jobs[name].runs == 0:
            jobs[name].runs = count

    rows = [j.as_dict(max_cost_per_output=max_cost_per_output) for j in jobs.values()]
    rows.sort(key=lambda r: (-(r["cost_usd"] or 0), -r["runs"], r["job"]))
    priced = [r for r in rows if r["cost_usd"] is not None]
    return {
        "since": since.isoformat(),
        "total_cost_usd": round(sum(r["cost_usd"] for r in priced), 4) if priced else None,
        "max_cost_per_output": max_cost_per_output,
        "jobs": rows,
        "flagged": [r["job"] for r in rows if {"no_output", "over_budget"} & set(r["flags"])],
    }


def render_text(report: dict) -> str:
    def money(value) -> str:
        return "-" if value is None else f"${value:,.2f}" if value >= 0.01 or value == 0 else f"${value:.4f}"

    lines = [f"since {report['since']}: total {money(report['total_cost_usd'])}", ""]
    if not report["jobs"]:
        return lines[0] + "\nno log entries in this window\n"
    width = max(len("job"), *(len(r["job"]) for r in report["jobs"]))
    lines.append(f"{'job'.ljust(width)}  runs  {'spend':>9}  {'per run':>9}  output  {'per output':>10}  flags")
    for r in report["jobs"]:
        lines.append(
            f"{r['job'].ljust(width)}  {r['runs']:>4}  {money(r['cost_usd']):>9}  {money(r['cost_per_run']):>9}  "
            f"{r['output']:>6}  {money(r['cost_per_output']):>10}  {', '.join(r['flags']) or '-'}"
        )
    unpriced = [r["job"] for r in report["jobs"] if r["cost_usd"] is None]
    if unpriced:
        lines += ["", "no cost recorded for: " + ", ".join(unpriced)]
    if report["flagged"]:
        lines += ["", "fix or kill: " + ", ".join(report["flagged"])]
    return "\n".join(lines) + "\n"
