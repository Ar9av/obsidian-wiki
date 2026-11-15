"""Tests for answer-level evals (eval-answers)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from obsidian_wiki import answer_eval as ae

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "fixtures" / "bench" / "answers.jsonl"

GOOD = {
    "which api gateway do we run today?": "We run **Envoy** ([[gateway-envoy]]); nginx was retired.",
    "when did we stop using nginx as the gateway?": "At the end of March 2026, see [[gateway-nginx]].",
    "where are rate limit counters stored?": "In Redis ([Redis](entities/redis.md)).",
    "how does a token bucket allow bursts?": "Tokens accumulate in a refilling bucket [[token-bucket]].",
    "how do I trace a 429 back to the caller?": "Find the limiter bucket, then the caller. [[debugging-429s]]",
    "what makes a retried write safe?": "An idempotency key makes the write idempotent [[idempotency]].",
}
WEAK = dict(
    GOOD,
    **{
        "which api gateway do we run today?": "We use nginx with Lua. [[gateway-nginx]]",
        "what makes a retried write safe?": "Exactly-once delivery with an idempotency key.",
    },
)
del WEAK["how do I trace a 429 back to the caller?"]


def _run(tmp_path: Path, name: str, answers: dict, *, model: str = "") -> Path:
    path = tmp_path / f"{name}.jsonl"
    path.write_text(
        "\n".join(json.dumps({"q": q, "answer": a, **({"model": model} if model else {})}) for q, a in answers.items()),
        encoding="utf-8",
    )
    return path


def test_bundled_gold_set_loads() -> None:
    cases = ae.load_gold(GOLD)
    assert len(cases) == 6
    assert cases[1]["must_include"] == [["2026-03-31", "march 2026", "end of march"]]


def test_a_correct_run_passes_everything() -> None:
    report = ae.score_run(ae.load_gold(GOLD), {ae._question_key(q): a for q, a in GOOD.items()})
    assert report["pass_rate"] == 1.0
    assert report["include_recall"] == 1.0
    assert report["citation_recall"] == 1.0
    assert report["violation_rate"] == 0.0


def test_failures_are_explained() -> None:
    report = ae.score_run(ae.load_gold(GOLD), {ae._question_key(q): a for q, a in WEAK.items()})
    by_q = {r["q"]: r for r in report["results"]}
    gateway = by_q["which api gateway do we run today?"]
    assert gateway["missing"] == ["envoy"]
    assert gateway["forbidden"] == [r"re:\bwe (?:run|use) nginx\b"]
    assert gateway["uncited"] == ["gateway-envoy"]
    assert by_q["what makes a retried write safe?"]["forbidden"] == ["exactly-once delivery"]
    assert by_q["what makes a retried write safe?"]["uncited"] == ["idempotency"]
    assert by_q["how do I trace a 429 back to the caller?"]["status"] == "missing"
    assert report["answered"] == 5 and report["passed"] == 3
    assert report["pass_rate"] == 0.5
    assert report["violation_rate"] == 0.4


def test_matching_ignores_case_emphasis_and_whitespace() -> None:
    case = {"q": "x", "line": 1, "must_include": [["Idempotency  Key"]], "must_not_include": [], "cite": []}
    assert ae.score_answer(case, "Use an *idempotency*\nkey.")["passed"] is True
    assert ae.score_answer(case, "Use an **idempotency key**.")["passed"] is True
    assert ae.score_answer(case, "use an IDEMPOTENCY\n  KEY")["passed"] is True


def test_a_bare_word_is_not_a_citation() -> None:
    case = {"q": "x", "line": 1, "must_include": [], "must_not_include": [], "cite": ["idempotency"]}
    assert ae.score_answer(case, "Idempotency matters.")["uncited"] == ["idempotency"]
    assert ae.score_answer(case, "See [[concepts/idempotency|this]].")["uncited"] == []
    path_case = dict(case, cite=["concepts/idempotency.md"])
    assert ae.score_answer(path_case, "Source: concepts/idempotency.md")["uncited"] == []


def test_questions_match_loosely() -> None:
    cases = ae.load_gold(GOLD)
    answers = {ae._question_key("Which API gateway do we run today"): "Envoy [[gateway-envoy]]"}
    assert ae.score_run(cases, answers)["results"][0]["passed"] is True


def test_compare_ranks_runs_and_gates(tmp_path: Path) -> None:
    cases = ae.load_gold(GOLD)
    weak = ae.load_answers(_run(tmp_path, "weak", WEAK, model="cheap-model"))
    good = ae.load_answers(_run(tmp_path, "good", GOOD))
    assert weak[0] == "cheap-model" and good[0] == "good"
    report = ae.compare(cases, [weak, good], min_pass=0.9)
    assert [m["model"] for m in report["models"]] == ["good", "cheap-model"]
    assert report["winner"] == "good" and report["status"] == "ok"
    assert ae.compare(cases, [weak], min_pass=0.9)["status"] == "fail"


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ('{"q": ""}', "no non-empty"),
        ('{"q": "a"}', "scores nothing"),
        ('{"q": "a", "must_include": [[]]}', "empty entry"),
        ('{"q": "a", "must_include": ["re:("]}', "bad regex"),
        ('{"q": "a", "cite": 3}', "cite must be"),
        ('[1]', "JSON object"),
        ('{"q": "a", "cite": "x"}\n{"q": "A?", "cite": "y"}', "duplicate"),
    ],
)
def test_gold_validation(tmp_path: Path, line: str, message: str) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ae.AnswerEvalError, match=message):
        ae.load_gold(gold)


def test_answers_validation(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"q": "a"}\n', encoding="utf-8")
    with pytest.raises(ae.AnswerEvalError, match="needs"):
        ae.load_answers(bad)


def _cli(*argv: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, CI="true", PYTHONPATH=str(ROOT))
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "eval-answers", "--gold", str(GOLD), *argv],
        capture_output=True, text=True, cwd=ROOT, env=env,
    )


def test_cli_compare_and_gate(tmp_path: Path) -> None:
    good = _run(tmp_path, "good", GOOD)
    weak = _run(tmp_path, "weak", WEAK)
    result = _cli("--answers", f"opus={good}", "--answers", str(weak), "--verbose")
    assert result.returncode == 0, result.stderr
    assert "winner: opus" in result.stdout
    assert "doesn't cite gateway-envoy" in result.stdout

    gated = _cli("--answers", str(weak), "--min-pass", "0.9", "--json")
    assert gated.returncode == 1
    assert json.loads(gated.stdout)["status"] == "fail"


def test_cli_questions_and_errors(tmp_path: Path) -> None:
    listed = _cli("--questions")
    assert listed.returncode == 0
    assert listed.stdout.splitlines()[0] == "which api gateway do we run today?"
    assert json.loads(_cli("--questions", "--json").stdout.splitlines()[0]) == {"q": "which api gateway do we run today?"}
    assert _cli().returncode == 1
    assert _cli("--answers", str(tmp_path / "nope.jsonl")).returncode == 1
