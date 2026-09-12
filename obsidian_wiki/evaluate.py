"""Retrieval benchmark for the vault query index.

`obsidian-wiki eval` scores what `graph-query` actually returns against a
hand-labelled gold set: recall@k, MRR, intent-classification accuracy, and
`should_read` precision. The point is a number to regress against — a ranking
change (or a future embedding index) gets compared instead of eyeballed.

The gold set is JSONL, one case per line:

    {"q": "what do I know about rate limiting?",
     "expect": ["concepts/rate-limiting.md", "token-bucket"],
     "intent": "direct"}

`expect` entries match either a page's vault-relative path or its slugged
stem, so a gold set survives a page moving between category folders. Both
`intent` and `expect` are optional — a case with only `intent` scores
classification alone (that is how the structural intents are covered), and a
case with only `expect` scores retrieval alone. `as_of` is passed through to
the temporal filter, which is how a historical page's gold case pins the date
it was still current.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from obsidian_wiki.graph_analysis import _slug

#: Cutoffs reported for recall. 5 is the one to quote — it is what comparable
#: systems report (LongMemEval-style recall@5) and what an agent actually
#: consumes before it starts opening pages.
RECALL_KS = (1, 3, 5)

#: Metric name -> the `run_eval(thresholds=...)` key that gates it.
THRESHOLD_METRICS = {
    "min_recall": "recall@5",
    "min_mrr": "mrr",
    "min_intent": "intent_accuracy",
    "min_should_read_precision": "should_read_precision",
}

__all__ = [
    "RECALL_KS",
    "THRESHOLD_METRICS",
    "GoldError",
    "default_goldset_path",
    "load_goldset",
    "render_text",
    "run_eval",
]

#: Where a vault keeps its own gold set, alongside the other `_meta` state.
GOLDSET_RELATIVE_PATH = Path("_meta") / "eval.jsonl"


class GoldError(ValueError):
    """A gold set that can't be read as a benchmark."""


def default_goldset_path(vault: Path) -> Path:
    return vault / GOLDSET_RELATIVE_PATH


def load_goldset(path: Path) -> "list[dict[str, Any]]":
    """Parse a JSONL gold set, reporting the offending line number on error.

    Blank lines and `#` comment lines are skipped so a gold set can carry
    section headers for the human maintaining it.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GoldError(f"cannot read gold set {path}: {exc}") from exc

    cases: list[dict[str, Any]] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            case = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GoldError(f"{path}:{lineno}: invalid JSON: {exc.msg}") from exc
        if not isinstance(case, dict):
            raise GoldError(f"{path}:{lineno}: expected a JSON object, got {type(case).__name__}")
        question = str(case.get("q", "")).strip()
        if not question:
            raise GoldError(f"{path}:{lineno}: case has no non-empty \"q\"")
        expect = case.get("expect", [])
        if isinstance(expect, str):
            expect = [expect]
        if not isinstance(expect, list):
            raise GoldError(f"{path}:{lineno}: \"expect\" must be a string or a list")
        if not expect and not case.get("intent"):
            raise GoldError(
                f"{path}:{lineno}: case scores nothing — give it \"expect\", \"intent\", or both"
            )
        cases.append(
            {
                "q": question,
                "expect": [str(item) for item in expect],
                "intent": str(case["intent"]).strip() if case.get("intent") else None,
                "as_of": str(case["as_of"]).strip() if case.get("as_of") else None,
                "line": lineno,
            }
        )
    if not cases:
        raise GoldError(f"{path}: no cases found")
    return cases


def _page_keys(page_path: str) -> "set[str]":
    """Every identifier a gold `expect` entry may legitimately use for a page."""
    text = str(page_path).replace("\\", "/").strip()
    text = text.removeprefix("[[").removesuffix("]]")
    text = text.split("|", 1)[0].split("#", 1)[0].strip()
    bare = text.removesuffix(".md")
    return {text, bare, _slug(Path(bare).name)}


def _first_hit_rank(candidates: Sequence[dict], expect: Iterable[str]) -> "int | None":
    """1-based rank of the first candidate matching any expected page."""
    wanted: set[str] = set()
    for item in expect:
        wanted |= _page_keys(item)
    for rank, candidate in enumerate(candidates, start=1):
        if _page_keys(candidate.get("page", "")) & wanted:
            return rank
    return None


def _mean(values: Sequence[float]) -> "float | None":
    return round(sum(values) / len(values), 4) if values else None


def run_eval(
    vault: Path,
    cases: Sequence[dict],
    *,
    top_n: int = 10,
    max_read: int = 3,
    thresholds: "dict[str, float] | None" = None,
) -> "dict[str, Any]":
    """Score `cases` against the vault's query index.

    `top_n` bounds how deep recall can look, so it is floored at the largest
    reported cutoff — a `--top 1` run would otherwise report recall@5 as if
    the index had returned nothing at ranks 2-5.
    """
    from obsidian_wiki.graphrag import query

    top_n = max(top_n, max(RECALL_KS))
    reciprocal_ranks: list[float] = []
    hits_at: dict[int, list[float]] = {k: [] for k in RECALL_KS}
    intent_scores: list[float] = []
    precision_scores: list[float] = []
    details: list[dict[str, Any]] = []

    for case in cases:
        result = query(
            vault,
            case["q"],
            top_n=top_n,
            max_should_read=max_read,
            as_of=case.get("as_of"),
        )
        candidates = result.get("candidates", [])
        detail: dict[str, Any] = {
            "q": case["q"],
            "line": case.get("line"),
            "got": [c.get("page") for c in candidates[: max(RECALL_KS)]],
            "failed": False,
        }

        if case["expect"]:
            rank = _first_hit_rank(candidates, case["expect"])
            reciprocal_ranks.append(1.0 / rank if rank else 0.0)
            for k in RECALL_KS:
                hits_at[k].append(1.0 if rank and rank <= k else 0.0)
            detail["expect"] = case["expect"]
            detail["rank"] = rank
            if rank is None or rank > max(RECALL_KS):
                detail["failed"] = True

            should_read = result.get("should_read") or []
            if should_read:
                wanted: set[str] = set()
                for item in case["expect"]:
                    wanted |= _page_keys(item)
                hit = sum(1 for page in should_read if _page_keys(page) & wanted)
                precision_scores.append(hit / len(should_read))

        if case["intent"]:
            got_intent = result.get("answer_type")
            detail["intent_expected"] = case["intent"]
            detail["intent_got"] = got_intent
            matched = got_intent == case["intent"]
            intent_scores.append(1.0 if matched else 0.0)
            if not matched:
                detail["failed"] = True

        details.append(detail)

    metrics: dict[str, Any] = {f"recall@{k}": _mean(hits_at[k]) for k in RECALL_KS}
    metrics["mrr"] = _mean(reciprocal_ranks)
    metrics["intent_accuracy"] = _mean(intent_scores)
    metrics["should_read_precision"] = _mean(precision_scores)

    thresholds = thresholds or {}
    violations = [
        {
            "metric": metric,
            "threshold": limit,
            "actual": metrics.get(metric),
        }
        for flag, metric in THRESHOLD_METRICS.items()
        if (limit := thresholds.get(flag)) is not None
        and (metrics.get(metric) is None or metrics[metric] < limit)
    ]

    return {
        "status": "fail" if violations else "pass",
        "vault": str(vault),
        "cases": len(cases),
        "scored": {
            "retrieval": len(reciprocal_ranks),
            "intent": len(intent_scores),
            "should_read": len(precision_scores),
        },
        "metrics": metrics,
        "thresholds": {
            THRESHOLD_METRICS[flag]: limit
            for flag, limit in thresholds.items()
            if flag in THRESHOLD_METRICS and limit is not None
        },
        "violations": violations,
        "failures": [d for d in details if d["failed"]],
        "cases_detail": details,
    }


def _fmt(value: "float | None") -> str:
    return "  n/a " if value is None else f"{value:.3f}"


def render_text(report: "dict[str, Any]", *, verbose: bool = False) -> str:
    """Human-readable report. `verbose` lists the cases that missed."""
    metrics = report["metrics"]
    scored = report["scored"]
    lines = [
        f"vault: {report['vault']}",
        f"cases: {report['cases']}  "
        f"(retrieval {scored['retrieval']}, intent {scored['intent']})",
        "",
    ]
    lines.extend(f"recall@{k}            {_fmt(metrics[f'recall@{k}'])}" for k in RECALL_KS)
    lines.append(f"mrr                  {_fmt(metrics['mrr'])}")
    lines.append(f"intent_accuracy      {_fmt(metrics['intent_accuracy'])}")
    lines.append(f"should_read_precision {_fmt(metrics['should_read_precision'])}")

    failures = report["failures"]
    if failures:
        lines.append("")
        lines.append(f"missed: {len(failures)} case(s)")
        shown = failures if verbose else failures[:5]
        for item in shown:
            lines.append(f"- {item['q']}")
            if "expect" in item:
                rank = item["rank"] if item["rank"] else "not in top 5"
                lines.append(f"    expected {item['expect']} -> {rank}")
                lines.append(f"    got      {item['got']}")
            if "intent_expected" in item and item["intent_expected"] != item["intent_got"]:
                lines.append(
                    f"    intent   expected {item['intent_expected']}, got {item['intent_got']}"
                )
        if not verbose and len(failures) > len(shown):
            lines.append(f"  ... {len(failures) - len(shown)} more (--verbose to list)")

    for violation in report["violations"]:
        lines.append(
            f"below threshold: {violation['metric']} "
            f"{_fmt(violation['actual'])} < {violation['threshold']:.3f}"
        )

    lines.append("")
    lines.append(f"status: {report['status']}")
    return "\n".join(lines) + "\n"
