#!/usr/bin/env python3
"""Benchmark the optional decision layer against the plain path on a vault.

Compares, per gold question, `graphrag.query` (the plain wiki-query pre-pass)
with `decisions.gated_query` (the same plus the relevance gate):

* wall time of the pre-pass, including the decision call;
* recall@1, recall@3 and MRR of the candidate list;
* pages in `should_read` and the estimated tokens of their bodies, which is
  what the agent reads next and where most of a query's time goes;
* how often the gate failed open.

It also times ingest triage on the vault's journal pages and the
contradiction screen over its entities, and reports what each returned.

Backends:

* ``--backend mock`` (default): a deterministic lexical stand-in, no network.
  Its numbers measure the plumbing only, not decision quality.
  ``--mock-latency-ms`` adds a sleep per call to model network time.
* ``--backend typesafe``: the live API. Needs ``TYPESAFE_API_KEY``. Sends the
  demo vault's titles, summaries and section text, which is sample content.

Usage:
    python tools/bench_decisions.py
    python tools/bench_decisions.py --backend typesafe --json > results.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from obsidian_wiki import decisions as d  # noqa: E402
from obsidian_wiki.context_pack import estimate_tokens  # noqa: E402
from obsidian_wiki.evaluate import _first_hit_rank, load_goldset  # noqa: E402
from obsidian_wiki.graphrag import _STOP_WORDS, query  # noqa: E402

DEFAULT_VAULT = ROOT / "examples" / "demo-vault"
DEFAULT_GOLD = ROOT / "tools" / "bench" / "demo-vault-gold.jsonl"
_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set:
    return {w for w in _WORD.findall(str(text).lower()) if len(w) > 3 and w not in _STOP_WORDS}


class LexicalMock(d.DecisionBackend):
    """Answers from word overlap. Deterministic, offline, deliberately simple."""

    name = "mock"
    model = "lexical-mock"

    def __init__(self, latency_ms: float = 0.0) -> None:
        self.latency_ms = latency_ms
        self.calls = 0

    def ask(self, state, questions):
        self.calls += 1
        started = time.perf_counter()
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000.0)
        answers: Dict[str, Any] = {}
        for qid, q in questions.items():
            if q["type"] == "noul":
                pid = re.search(r"pages\.(P\d+)", q["instructions"]).group(1)
                page = state["pages"][pid]
                overlap = len(_words(state["query"]) & _words(" ".join([page["title"], page["summary"],
                                                                        " ".join(page.get("tags", []))])))
                p = 0.97 if overlap >= 2 else (0.7 if overlap == 1 else 0.03)
                answers[qid] = {"type": "noul", "noul": p}
            else:
                options = list(q["criteria"])
                if "pages" in state:  # triage
                    pid = re.search(r"pages\.(P\d+)", q["instructions"]).group(1)
                    page = state["pages"][pid]
                    overlap = len(_words(state["source"]) & _words(page["title"] + " " + page["summary"]))
                    top = "update" if overlap >= 3 else "unrelated"
                else:  # contradiction screen
                    top = "new_detail"
                probs = {o: (0.8 if o == top else 0.2 / (len(options) - 1)) for o in options}
                answers[qid] = {"type": "choice", "choice": top, "confidence": 0.8, "probabilities": probs}
        return d.BackendAnswer(model=self.model, answers=answers, usage={},
                               latency_ms=(time.perf_counter() - started) * 1000.0)


def _read_tokens(vault: Path, pages: List[str]) -> int:
    total = 0
    for rel in pages:
        try:
            total += estimate_tokens((vault / rel).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return total


def _metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ranks = [r["rank"] for r in rows]
    return {
        "recall@1": sum(1 for k in ranks if k is not None and k <= 1) / len(rows),
        "recall@3": sum(1 for k in ranks if k is not None and k <= 3) / len(rows),
        "mrr": sum(1.0 / k for k in ranks if k) / len(rows),
        "should_read_pages_mean": statistics.mean(r["should_read"] for r in rows),
        "should_read_tokens_total": sum(r["read_tokens"] for r in rows),
        "should_read_hits": sum(r["read_hits"] for r in rows),
        "wall_ms_mean": statistics.mean(r["ms"] for r in rows),
        "wall_ms_p50": statistics.median(r["ms"] for r in rows),
    }


def _row(vault: Path, case: Dict[str, Any], result: Dict[str, Any], ms: float) -> Dict[str, Any]:
    expect = case.get("expect", [])
    wanted = {e.removesuffix(".md") for e in expect}
    reads = result.get("should_read") or []
    return {
        "q": case["q"],
        "rank": _first_hit_rank(result.get("candidates") or [], expect),
        "should_read": len(reads),
        "read_tokens": _read_tokens(vault, reads),
        "read_hits": sum(1 for p in reads if p.removesuffix(".md") in wanted),
        "ms": ms,
        "decision": result.get("decision"),
    }


def run(vault: Path, gold: Path, backend: d.DecisionBackend, cfg: d.DecisionConfig, repeat: int) -> Dict[str, Any]:
    cases = [c for c in load_goldset(gold) if c.get("expect")]
    plain_rows, gated_rows = [], []
    for case in cases:
        for _ in range(repeat):
            t0 = time.perf_counter()
            plain = query(vault, case["q"])
            plain_rows.append(_row(vault, case, plain, (time.perf_counter() - t0) * 1000.0))
            t0 = time.perf_counter()
            gated = d.gated_query(vault, case["q"], cfg, backend=backend)
            gated_rows.append(_row(vault, case, gated, (time.perf_counter() - t0) * 1000.0))
    decided = [r["decision"] for r in gated_rows if r["decision"]]
    gate_latencies = [x["latency_ms"] for x in decided if x.get("latency_ms") is not None]

    triage = []
    for src in sorted((vault / "journal").glob("*.md")):
        t0 = time.perf_counter()
        out = d.triage_source(vault, src, cfg, backend=backend)
        triage.append({"source": out["source"], "verdict": out["verdict"],
                       "shortlist": [c["page"] for c in out["shortlist"]][:5],
                       "skipped": len(out["skip"]), "failed_open": out["decision"]["failed_open"],
                       "reason": out["decision"]["reason"], "ms": (time.perf_counter() - t0) * 1000.0})

    found = d.find_section_pairs(vault)
    t0 = time.perf_counter()
    screen = d.contradiction_screen(found["pairs"], cfg, backend=backend)
    contra = {"pairs": len(found["pairs"]), "truncated": found["truncated"],
              "to_read": len(screen["to_read"]), "skipped": len(screen["skipped"]),
              "priority_1": sum(1 for r in screen["to_read"] if r["priority"] == 1),
              "failed_open": screen["decision"]["failed_open"], "errors": screen["decision"].get("errors"),
              "ms": (time.perf_counter() - t0) * 1000.0}

    return {
        "vault": str(vault.relative_to(ROOT)) if vault.is_relative_to(ROOT) else str(vault),
        "backend": backend.name,
        "model": backend.model,
        "thresholds": cfg.thresholds(),
        "order_check": cfg.order_check,
        "questions": len(cases),
        "repeat": repeat,
        "plain": _metrics(plain_rows),
        "gated": _metrics(gated_rows),
        "gate": {
            "failed_open": sum(1 for x in decided if x.get("failed_open")),
            "failed_reasons": sorted({x["reason"] for x in decided if x.get("failed_open") and x.get("reason")}),
            "not_run": sorted({x["reason"] for x in decided if not x.get("failed_open") and x.get("reason")}),
            "latency_ms_mean": statistics.mean(gate_latencies) if gate_latencies else None,
            "latency_ms_p50": statistics.median(gate_latencies) if gate_latencies else None,
            "dropped_total": sum((x.get("counts") or {}).get("dropped", 0) for x in decided),
        },
        "triage": triage,
        "contradictions": contra,
        "per_question": [
            {"q": p["q"], "plain_rank": p["rank"], "gated_rank": g["rank"],
             "plain_reads": p["should_read"], "gated_reads": g["should_read"]}
            for p, g in zip(plain_rows[::repeat], gated_rows[::repeat])
        ],
    }


def render(report: Dict[str, Any]) -> str:
    p, g = report["plain"], report["gated"]
    lines = [
        f"# Decision layer benchmark — {report['vault']}",
        "",
        f"backend `{report['backend']}` · model `{report['model']}` · thresholds {report['thresholds']} · "
        f"order_check {report['order_check']} · {report['questions']} questions × {report['repeat']}",
        "",
    ]
    if report["backend"] == "mock":
        lines += ["> Mock backend: a lexical stand-in. These numbers test the plumbing and the cost of the",
                  "> extra step; they say nothing about how well Jev judges relevance.", ""]
    lines += [
        "| metric | plain | with gate |",
        "|---|---|---|",
    ]
    for key in ("recall@1", "recall@3", "mrr", "should_read_pages_mean", "should_read_hits",
                "should_read_tokens_total", "wall_ms_mean", "wall_ms_p50"):
        fmt = "{:.3f}" if isinstance(p[key], float) else "{}"
        lines.append(f"| {key} | {fmt.format(p[key])} | {fmt.format(g[key])} |")
    gate = report["gate"]
    lat = gate["latency_ms_mean"]
    lines += [
        "",
        f"gate: failed_open {gate['failed_open']}/{report['questions'] * report['repeat']}"
        f" {gate['failed_reasons'] or ''} · not run (nothing to judge): {gate['not_run'] or 'none'}"
        f" · decision latency mean "
        f"{'n/a' if lat is None else f'{lat:.1f} ms'} · pages dropped {gate['dropped_total']}",
        "",
        "| triage source | verdict | first pages to read | skipped | ms |",
        "|---|---|---|---|---|",
    ]
    for t in report["triage"]:
        verdict = t["verdict"] + (f" (failed open: {t['reason']})" if t["failed_open"] else "")
        lines.append(f"| {t['source']} | {verdict} | {', '.join(t['shortlist'][:3])} | {t['skipped']} | {t['ms']:.0f} |")
    c = report["contradictions"]
    lines += ["", f"contradiction screen: {c['pairs']} section pairs → {c['to_read']} to read "
                  f"({c['priority_1']} priority 1), {c['skipped']} skipped, {c['ms']:.0f} ms"
                  + (f", failed open {c['errors']}" if c["failed_open"] else "")]
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--backend", choices=("mock", "typesafe"), default="mock")
    ap.add_argument("--mock-latency-ms", type=float, default=0.0)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--act", type=float, default=d.DEFAULT_ACT)
    ap.add_argument("--confirm", type=float, default=d.DEFAULT_CONFIRM)
    ap.add_argument("--model", default=d.DEFAULT_MODEL)
    ap.add_argument("--no-order-check", dest="order_check", action="store_false")
    ap.add_argument("--json", action="store_true", help="print the raw report as JSON")
    args = ap.parse_args(argv)

    cfg = d.DecisionConfig(enabled=True, backend="typesafe", model=args.model, act=args.act,
                           confirm=args.confirm, order_check=args.order_check)
    if args.backend == "mock":
        backend: d.DecisionBackend = LexicalMock(args.mock_latency_ms)
    else:
        if not os.environ.get(d.ENV_KEY):
            print(f"error: --backend typesafe needs {d.ENV_KEY}", file=sys.stderr)
            return 2
        backend = d.make_backend(cfg)
    report = run(args.vault.resolve(), args.gold, backend, cfg, max(1, args.repeat))
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
