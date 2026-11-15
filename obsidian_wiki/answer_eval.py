"""Answer-level evals: real questions, the right answer, every model compared.

``obsidian-wiki eval`` scores *retrieval*: did the index surface the right
pages. That number doesn't move when a new model comes out, and the model is
what changes the answer. This module scores the *answers*.

A gold file (``_meta/answers.jsonl`` by default) holds real questions and what a
correct answer must contain, must never contain, and must cite:

    {"q": "what did we decide about the api gateway?",
     "must_include": ["envoy", ["2026-04", "april 2026"]],
     "must_not_include": ["nginx is current"],
     "cite": ["gateway-envoy"]}

Each ``must_include`` item is a phrase, or a list of alternatives where any one
counts. A phrase starting with ``re:`` is a case-insensitive regular expression.
Matching ignores case, markdown emphasis and runs of whitespace.

Answers come from wherever the model ran, one JSONL file per run:

    {"q": "what did we decide about the api gateway?", "answer": "...", "model": "fable-5.2"}

Pass several runs and the report ranks them, so "switch to the winner" is a
table you read, not a hunch. Running the models is deliberately out of scope:
this stays offline, deterministic and free.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional, Sequence

from obsidian_wiki.graph_analysis import _slug

GOLD_RELATIVE_PATH = Path("_meta") / "answers.jsonl"


class AnswerEvalError(ValueError):
    """A gold or answers file that can't be scored."""


def default_gold_path(vault: Path) -> Path:
    return Path(vault) / GOLD_RELATIVE_PATH


def _norm(text: str) -> str:
    text = re.sub(r"[*_`]+", "", text)
    return " ".join(text.casefold().split())


def _question_key(question: str) -> str:
    return re.sub(r"[^\w]+", " ", question.casefold()).strip()


def _jsonl(path: Path, label: str) -> list:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AnswerEvalError(f"cannot read {label} {path}: {exc}") from exc
    rows = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AnswerEvalError(f"{path}:{lineno}: invalid JSON: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise AnswerEvalError(f"{path}:{lineno}: expected a JSON object")
        rows.append((lineno, row))
    return rows


def _phrases(value: Any, where: str) -> list:
    """Normalise to a list of alternatives-lists: ``["a", ["b", "c"]]`` -> ``[["a"], ["b", "c"]]``."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise AnswerEvalError(f"{where} must be a string or a list")
    out = []
    for item in value:
        options = item if isinstance(item, list) else [item]
        options = [str(o) for o in options if str(o).strip()]
        if not options:
            raise AnswerEvalError(f"{where} has an empty entry")
        for option in options:
            if option.startswith("re:"):
                try:
                    re.compile(option[3:])
                except re.error as exc:
                    raise AnswerEvalError(f"{where}: bad regex {option!r}: {exc}") from None
        out.append(options)
    return out


def _cites(value: Any, where: str) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise AnswerEvalError(f"{where} cite must be a string or a list")
    return [str(page).strip() for page in value if str(page).strip()]


def load_gold(path: Path) -> list:
    cases = []
    seen = set()
    for lineno, row in _jsonl(path, "gold set"):
        where = f"{path}:{lineno}"
        question = str(row.get("q", "")).strip()
        if not question:
            raise AnswerEvalError(f"{where}: case has no non-empty \"q\"")
        key = _question_key(question)
        if key in seen:
            raise AnswerEvalError(f"{where}: duplicate question {question!r}")
        seen.add(key)
        case = {
            "q": question,
            "must_include": _phrases(row.get("must_include"), f"{where} must_include"),
            "must_not_include": _phrases(row.get("must_not_include"), f"{where} must_not_include"),
            "cite": _cites(row.get("cite"), where),
            "line": lineno,
        }
        if not (case["must_include"] or case["must_not_include"] or case["cite"]):
            raise AnswerEvalError(f"{where}: case scores nothing; give it must_include, must_not_include or cite")
        cases.append(case)
    if not cases:
        raise AnswerEvalError(f"{path}: no cases found")
    return cases


def load_answers(path: Path, *, model: str = "") -> tuple:
    """(model name, {question key: answer text}). The model comes from the rows, else *model*, else the filename."""
    answers = {}
    names = set()
    for lineno, row in _jsonl(path, "answers file"):
        question = str(row.get("q", "")).strip()
        if not question or "answer" not in row:
            raise AnswerEvalError(f"{path}:{lineno}: each row needs \"q\" and \"answer\"")
        answers[_question_key(question)] = str(row.get("answer") or "")
        if row.get("model"):
            names.add(str(row["model"]).strip())
    if model:
        name = model
    elif len(names) == 1:
        name = names.pop()
    else:
        name = path.stem
    return name, answers


def _matches(option: str, text: str) -> bool:
    if option.startswith("re:"):
        return re.search(option[3:], text, re.IGNORECASE) is not None
    return _norm(option) in text


def _cited(page: str, answer: str) -> bool:
    """A citation is a wikilink or markdown link to the page (path or stem), or its full path."""
    stem = _slug(Path(page).stem)
    for target in re.findall(r"\[\[([^\]|#]+)", answer) + re.findall(r"\]\(([^)\s#]+)", answer):
        if _slug(Path(target.strip()).stem) == stem:
            return True
    # A bare mention is only a citation when it is a path ("concepts/x.md"),
    # never a word: "idempotency" in prose doesn't cite the idempotency page.
    if "/" in page or page.endswith(".md"):
        return page.casefold() in answer.casefold()
    return False


def score_answer(case: dict, answer: Optional[str]) -> dict:
    if answer is None:
        return {"q": case["q"], "line": case["line"], "status": "missing", "passed": False,
                "missing": [], "forbidden": [], "uncited": list(case["cite"])}
    text = _norm(answer)
    missing = [opts for opts in case["must_include"] if not any(_matches(o, text) for o in opts)]
    forbidden = [o for opts in case["must_not_include"] for o in opts if _matches(o, text)]
    uncited = [page for page in case["cite"] if not _cited(page, answer)]
    passed = not missing and not forbidden and not uncited
    return {
        "q": case["q"], "line": case["line"], "status": "pass" if passed else "fail", "passed": passed,
        "missing": [" | ".join(opts) for opts in missing], "forbidden": forbidden, "uncited": uncited,
        "include_hits": len(case["must_include"]) - len(missing), "include_total": len(case["must_include"]),
    }


def _ratio(num: int, den: int) -> Optional[float]:
    return round(num / den, 3) if den else None


def score_run(cases: Sequence[dict], answers: dict) -> dict:
    results = [score_answer(case, answers.get(_question_key(case["q"]))) for case in cases]
    answered = [r for r in results if r["status"] != "missing"]
    hits = sum(r.get("include_hits", 0) for r in answered)
    total = sum(r.get("include_total", 0) for r in answered)
    cite_total = sum(len(c["cite"]) for c, r in zip(cases, results) if r["status"] != "missing")
    cite_missed = sum(len(r["uncited"]) for r in answered)
    return {
        "cases": len(cases),
        "answered": len(answered),
        "passed": sum(1 for r in results if r["passed"]),
        "pass_rate": _ratio(sum(1 for r in results if r["passed"]), len(cases)),
        "include_recall": _ratio(hits, total),
        "violation_rate": _ratio(sum(1 for r in answered if r["forbidden"]), len(answered)),
        "citation_recall": _ratio(cite_total - cite_missed, cite_total),
        "results": results,
    }


def compare(cases: Sequence[dict], runs: Sequence[tuple], *, min_pass: Optional[float] = None) -> dict:
    """Score every (model, answers) run and rank them. Missing answers count as failures."""
    models = []
    for name, answers in runs:
        report = score_run(cases, answers)
        report["model"] = name
        models.append(report)

    def rank(m: dict) -> tuple:
        return (-(m["pass_rate"] or 0), -(m["include_recall"] or 0), m["violation_rate"] or 0, m["model"])

    models.sort(key=rank)
    status = "ok"
    if min_pass is not None and models and (models[0]["pass_rate"] or 0) < min_pass:
        status = "fail"
    return {"cases": len(cases), "models": models, "winner": models[0]["model"] if models else None,
            "min_pass": min_pass, "status": status}


def _fmt(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_text(report: dict, *, verbose: bool = False) -> str:
    lines = [f"{report['cases']} case(s)", ""]
    width = max([len("model")] + [len(m["model"]) for m in report["models"]])
    lines.append(f"{'model'.ljust(width)}  pass_rate  include  violations  citations  answered")
    for m in report["models"]:
        lines.append(
            f"{m['model'].ljust(width)}  {_fmt(m['pass_rate']):>9}  {_fmt(m['include_recall']):>7}  "
            f"{_fmt(m['violation_rate']):>10}  {_fmt(m['citation_recall']):>9}  {m['answered']:>4}/{m['cases']}"
        )
    if len(report["models"]) > 1:
        lines += ["", f"winner: {report['winner']}"]
    if report["min_pass"] is not None:
        lines.append(f"gate: best pass_rate >= {report['min_pass']:.3f} -> {report['status'].upper()}")
    if verbose:
        for m in report["models"]:
            failed = [r for r in m["results"] if not r["passed"]]
            if not failed:
                continue
            lines += ["", f"{m['model']}: {len(failed)} failed"]
            for r in failed:
                why = []
                if r["status"] == "missing":
                    why.append("no answer")
                if r["missing"]:
                    why.append("missing " + "; ".join(r["missing"]))
                if r["forbidden"]:
                    why.append("says " + "; ".join(r["forbidden"]))
                if r["uncited"] and r["status"] != "missing":
                    why.append("doesn't cite " + ", ".join(r["uncited"]))
                lines.append(f"  line {r['line']}: {r['q']}\n      {' / '.join(why)}")
    return "\n".join(lines) + "\n"


def questions(cases: Sequence[dict]) -> list:
    return [case["q"] for case in cases]
