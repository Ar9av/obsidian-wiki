"""Tests for the retrieval benchmark, plus the benchmark itself as a gate.

`test_bench_vault_meets_baseline` is the regression gate: it runs the checked-in
fixture vault against the checked-in gold set and fails if retrieval quality
drops below the measured baseline. Any ranking change has to move these numbers
deliberately.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from obsidian_wiki.evaluate import GoldError, load_goldset, render_text, run_eval

BENCH = Path(__file__).parent / "fixtures" / "bench"
BENCH_VAULT = BENCH / "vault"
BENCH_GOLD = BENCH / "gold.jsonl"

#: Measured on the checked-in fixture (2026-09, pure lexical index), minus a
#: small margin. Raise these when retrieval genuinely improves — an embedding
#: index should move recall@5 and MRR well past them.
BASELINE = {
    "recall@1": 0.80,
    "recall@5": 0.90,
    "mrr": 0.85,
    "intent_accuracy": 1.00,
}


def _write_gold(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "gold.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _page(vault: Path, relpath: str, summary: str) -> None:
    path = vault / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join([
            "---",
            f"title: {path.stem}",
            "category: concepts",
            "tags: [test]",
            "sources: [manual]",
            "created: 2026-01-01",
            "updated: 2026-01-01",
            f"summary: {summary}",
            "---",
            f"# {path.stem}",
        ]) + "\n",
        encoding="utf-8",
    )


# --- gold set parsing ------------------------------------------------------

def test_load_goldset_skips_blanks_and_comments(tmp_path: Path) -> None:
    gold = _write_gold(tmp_path, [
        "# a section header",
        "",
        '{"q": "alpha", "expect": "concepts/alpha.md"}',
        '{"q": "beta", "intent": "hubs"}',
    ])

    cases = load_goldset(gold)

    assert [c["q"] for c in cases] == ["alpha", "beta"]
    assert cases[0]["expect"] == ["concepts/alpha.md"], "a bare string becomes a list"
    assert cases[1]["expect"] == []
    assert cases[1]["intent"] == "hubs"


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("{not json}", "invalid JSON"),
        ('["alpha"]', "expected a JSON object"),
        ('{"expect": ["a.md"]}', 'no non-empty "q"'),
        ('{"q": "alpha", "expect": {"a": 1}}', '"expect" must be'),
        ('{"q": "alpha"}', "scores nothing"),
    ],
)
def test_load_goldset_reports_the_offending_line(tmp_path: Path, line: str, message: str) -> None:
    gold = _write_gold(tmp_path, ['{"q": "ok", "intent": "hubs"}', line])

    with pytest.raises(GoldError) as excinfo:
        load_goldset(gold)

    assert message in str(excinfo.value)
    assert "gold.jsonl:2" in str(excinfo.value)


def test_load_goldset_rejects_an_empty_file(tmp_path: Path) -> None:
    with pytest.raises(GoldError, match="no cases found"):
        load_goldset(_write_gold(tmp_path, ["# nothing but a comment"]))


# --- scoring ---------------------------------------------------------------

def test_expect_matches_path_stem_or_wikilink(tmp_path: Path) -> None:
    """A gold set must survive a page moving between category folders."""
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha is a distinctive topic.")

    for spelling in ("concepts/alpha.md", "concepts/alpha", "alpha", "[[alpha]]"):
        report = run_eval(vault, [{"q": "alpha", "expect": [spelling], "intent": None, "as_of": None}])
        assert report["metrics"]["recall@1"] == 1.0, spelling


def test_recall_and_mrr_reflect_rank(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha names the primary subject.")
    _page(vault, "concepts/beta.md", "Beta mentions alpha only in passing.")

    report = run_eval(vault, [
        {"q": "alpha", "expect": ["concepts/beta.md"], "intent": None, "as_of": None},
    ])

    # beta ranks second behind the title match, so it misses @1 but makes @3.
    assert report["metrics"]["recall@1"] == 0.0
    assert report["metrics"]["recall@3"] == 1.0
    assert report["metrics"]["mrr"] == 0.5


def test_a_total_miss_scores_zero_and_is_listed_as_a_failure(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha.")

    report = run_eval(vault, [
        {"q": "zzzznothing", "expect": ["concepts/alpha.md"], "intent": None, "as_of": None},
    ])

    assert report["metrics"]["recall@5"] == 0.0
    assert report["metrics"]["mrr"] == 0.0
    assert report["failures"][0]["rank"] is None


def test_intent_only_cases_score_intent_and_not_recall(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha.")

    report = run_eval(vault, [
        {"q": "what clusters do I have?", "expect": [], "intent": "clusters", "as_of": None},
    ])

    assert report["metrics"]["intent_accuracy"] == 1.0
    assert report["metrics"]["recall@5"] is None, "no retrieval cases to average"
    assert report["scored"] == {"retrieval": 0, "intent": 1, "should_read": 0}


def test_top_n_is_floored_at_the_largest_reported_cutoff(tmp_path: Path) -> None:
    """--top 1 must not report recall@5 as if ranks 2-5 came back empty."""
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha names the primary subject.")
    _page(vault, "concepts/beta.md", "Beta mentions alpha only in passing.")

    report = run_eval(
        vault,
        [{"q": "alpha", "expect": ["concepts/beta.md"], "intent": None, "as_of": None}],
        top_n=1,
    )

    assert report["metrics"]["recall@5"] == 1.0


def test_thresholds_gate_the_status(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha.")
    cases = [{"q": "zzzznothing", "expect": ["concepts/alpha.md"], "intent": None, "as_of": None}]

    assert run_eval(vault, cases)["status"] == "pass", "no thresholds means no gate"

    gated = run_eval(vault, cases, thresholds={"min_recall": 0.5})
    assert gated["status"] == "fail"
    assert gated["violations"] == [
        {"metric": "recall@5", "threshold": 0.5, "actual": 0.0}
    ]


def test_an_unmeasurable_metric_fails_its_threshold(tmp_path: Path) -> None:
    """Gating on recall with only intent cases is a broken gate, not a pass."""
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha.")

    report = run_eval(
        vault,
        [{"q": "what clusters do I have?", "expect": [], "intent": "clusters", "as_of": None}],
        thresholds={"min_recall": 0.5},
    )

    assert report["status"] == "fail"
    assert report["violations"][0]["actual"] is None


def test_render_text_survives_unmeasured_metrics(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha.")
    report = run_eval(vault, [
        {"q": "what clusters do I have?", "expect": [], "intent": "clusters", "as_of": None},
    ])

    text = render_text(report)

    assert "n/a" in text
    assert "status: pass" in text


# --- the benchmark ---------------------------------------------------------

def test_bench_vault_meets_baseline() -> None:
    report = run_eval(BENCH_VAULT, load_goldset(BENCH_GOLD))

    below = {
        metric: (report["metrics"][metric], floor)
        for metric, floor in BASELINE.items()
        if report["metrics"][metric] is None or report["metrics"][metric] < floor
    }
    assert not below, f"retrieval regressed (actual, floor): {below}"


def test_bench_gold_set_expects_pages_that_exist() -> None:
    """A typo'd `expect` path silently depresses recall forever — catch it here."""
    stems = {path.stem for path in BENCH_VAULT.rglob("*.md")}
    paths = {path.relative_to(BENCH_VAULT).as_posix() for path in BENCH_VAULT.rglob("*.md")}

    missing = [
        item
        for case in load_goldset(BENCH_GOLD)
        for item in case["expect"]
        if item not in paths and Path(item).stem not in stems
    ]

    assert missing == []


# --- CLI -------------------------------------------------------------------

def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parents[1])
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True, check=False, text=True, env=env,
    )


def test_eval_cli_emits_json_and_exits_zero() -> None:
    result = _run("eval", "--vault", str(BENCH_VAULT), "--gold", str(BENCH_GOLD), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "pass"
    assert payload["cases"] == 26
    assert payload["gold"] == str(BENCH_GOLD)


def test_eval_cli_exits_one_below_threshold() -> None:
    result = _run(
        "eval", "--vault", str(BENCH_VAULT), "--gold", str(BENCH_GOLD), "--min-recall", "1.01"
    )

    assert result.returncode == 1
    assert "below threshold" in result.stdout


def test_eval_cli_defaults_the_gold_set_to_vault_meta(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha is a distinctive topic.")
    (vault / "_meta").mkdir(parents=True)
    (vault / "_meta" / "eval.jsonl").write_text(
        '{"q": "alpha", "expect": ["concepts/alpha.md"]}\n', encoding="utf-8"
    )

    result = _run("eval", "--vault", str(vault), "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["metrics"]["recall@1"] == 1.0


def test_eval_cli_explains_a_missing_gold_set(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha.")

    result = _run("eval", "--vault", str(vault))

    assert result.returncode == 1
    assert "no gold set at" in result.stderr
    assert "_meta/eval.jsonl" in result.stderr
