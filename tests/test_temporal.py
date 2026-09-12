"""Tests for bi-temporal page validity."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from obsidian_wiki.graphrag import build_index, current_pages, query
from obsidian_wiki.lint import lint_vault
from obsidian_wiki.temporal import (
    is_current,
    parse_date,
    superseded_target,
    validity_window,
)


def _page(vault: Path, relpath: str, *, extra: str = "", summary: str = "A page.") -> Path:
    path = vault / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"title: {path.stem}",
        "category: references",
        "tags: [test]",
        "sources: [manual]",
        "created: 2026-01-01",
        "updated: 2026-01-01",
        f"summary: {summary}",
    ]
    if extra:
        lines.append(extra)
    lines += ["---", f"# {path.stem}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- parsing ---------------------------------------------------------------

def test_parse_date_accepts_dates_timestamps_and_empty() -> None:
    assert parse_date("2026-04-01") == date(2026, 4, 1)
    assert parse_date("2026-04-01T09:30:00+00:00") == date(2026, 4, 1)
    assert parse_date("2026-04-01T09:30:00Z") == date(2026, 4, 1)
    assert parse_date('  "2026-04-01"  ') == date(2026, 4, 1)
    assert parse_date("") is None
    assert parse_date(None) is None


def test_parse_date_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        parse_date("last tuesday")


def test_validity_window_rejects_inverted_window() -> None:
    with pytest.raises(ValueError, match="precedes valid_from"):
        validity_window({"valid_from": "2026-05-01", "valid_until": "2026-04-01"})


def test_superseded_target_unwraps_wikilinks_aliases_and_paths() -> None:
    assert superseded_target("[[gateway-envoy]]") == "gateway-envoy"
    assert superseded_target('"[[references/gateway-envoy.md|Envoy]]"') == "gateway-envoy"
    assert superseded_target("[[gateway-envoy#Routes]]") == "gateway-envoy"
    assert superseded_target("") == ""


# --- currency --------------------------------------------------------------

def test_page_without_temporal_fields_is_always_current() -> None:
    assert is_current({}, date(1999, 1, 1)) is True


def test_valid_until_is_inclusive_and_valid_from_is_a_floor() -> None:
    window = {"valid_from": "2026-04-01", "valid_until": "2026-06-30"}
    assert is_current(window, date(2026, 3, 31)) is False   # not yet true
    assert is_current(window, date(2026, 4, 1)) is True
    assert is_current(window, date(2026, 6, 30)) is True    # last day counts
    assert is_current(window, date(2026, 7, 1)) is False    # no longer true


def test_malformed_dates_count_as_current_so_retrieval_never_silently_drops() -> None:
    assert is_current({"valid_until": "whenever"}, date(2026, 6, 1)) is True


# --- retrieval -------------------------------------------------------------

def test_expired_page_leaves_retrieval_but_stays_in_the_graph(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "references/old-gateway.md", summary="The gateway is nginx.",
          extra="valid_until: 2026-03-31\nsuperseded_by: \"[[new-gateway]]\"")
    _page(vault, "references/new-gateway.md", summary="The gateway is envoy.",
          extra="valid_from: 2026-04-01")

    index = build_index(vault)
    assert set(index) == {"old-gateway", "new-gateway"}, "graph keeps every page"

    live = current_pages(index, date(2026, 6, 1))
    assert set(live) == {"new-gateway"}

    historical = current_pages(index, date(2026, 1, 1))
    assert set(historical) == {"old-gateway"}


def test_query_as_of_returns_the_page_that_was_true_then(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "references/old-gateway.md", summary="The gateway is nginx.",
          extra="valid_until: 2026-03-31\nsuperseded_by: \"[[new-gateway]]\"")
    _page(vault, "references/new-gateway.md", summary="The gateway is envoy.",
          extra="valid_from: 2026-04-01")

    now = query(vault, "gateway", as_of="2026-06-01")
    assert [c["page"] for c in now["candidates"]] == ["references/new-gateway.md"]
    assert now["temporal"] == {
        "as_of": "2026-06-01",
        "include_historical": False,
        "retrievable": 1,
        "excluded_historical": 1,
    }

    then = query(vault, "gateway", as_of="2026-01-15")
    assert [c["page"] for c in then["candidates"]] == ["references/old-gateway.md"]
    # The historical hit carries its own replacement, so the agent can follow it.
    assert then["candidates"][0]["superseded_by"] == "new-gateway"
    assert then["candidates"][0]["valid_until"] == "2026-03-31"


def test_include_historical_ranks_both(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "references/old-gateway.md", summary="The gateway is nginx.",
          extra="valid_until: 2026-03-31")
    _page(vault, "references/new-gateway.md", summary="The gateway is envoy.")

    result = query(vault, "gateway", as_of="2026-06-01", include_historical=True)
    assert len(result["candidates"]) == 2
    assert result["temporal"]["excluded_historical"] == 0


def test_temporal_keys_are_absent_on_pages_that_do_not_opt_in(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/plain.md", summary="No temporal fields here.")

    candidate = query(vault, "plain")["candidates"][0]
    assert "valid_until" not in candidate
    assert "valid_from" not in candidate
    assert "superseded_by" not in candidate


def test_structural_intents_still_see_historical_pages(tmp_path: Path) -> None:
    """Deleting a page breaks the historical pages linking to it, so the blast
    radius must not shrink just because a dependent is no longer current."""
    vault = tmp_path / "vault"
    (vault / "concepts").mkdir(parents=True)
    _page(vault, "concepts/redis.md", summary="A datastore.")
    old = _page(vault, "references/old-limiter.md", summary="Limiter on nginx.",
                extra="valid_until: 2026-03-31")
    old.write_text(old.read_text(encoding="utf-8") + "\n[[redis]]\n", encoding="utf-8")

    result = query(vault, "what breaks if I delete redis?", as_of="2026-06-01")
    assert result["answer_type"] == "impact"
    assert "old-limiter" in result["graph"]["direct_dependents"]


# --- lint ------------------------------------------------------------------

def test_lint_fails_on_malformed_temporal_metadata(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "references/inverted.md",
          extra="valid_from: 2026-05-01\nvalid_until: 2026-04-01")
    _page(vault, "references/garbage.md", extra="valid_until: soon")

    report = lint_vault(vault, require_trust_ledger=False)

    issues = {item["page"] for item in report["findings"]["temporal_errors"]}
    assert issues == {"references/inverted.md", "references/garbage.md"}
    assert report["status"] == "fail"


def test_lint_reports_dangling_superseded_by(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "references/old.md", extra="superseded_by: \"[[does-not-exist]]\"")
    _page(vault, "references/self.md", extra="superseded_by: \"[[self]]\"")

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["temporal_errors"] == []
    assert report["findings"]["superseded_dangling"] == [
        {"page": "references/old.md", "target": "does-not-exist", "issue": "missing_target"},
        {"page": "references/self.md", "target": "self", "issue": "self_reference"},
    ]
    # A bracketed value is a wikilink like any other, so the pre-existing
    # broken_links check fires too and the vault fails — same as a typed
    # `relationships:` target pointing at nothing.
    assert report["findings"]["broken_links"] == [
        {"page": "references/old.md", "target": "does-not-exist"}
    ]
    assert report["status"] == "fail"


def test_lint_warns_on_a_dangling_unbracketed_superseded_by(tmp_path: Path) -> None:
    """Written as a plain name it isn't a wikilink, so only the specific
    finding fires and the vault warns rather than fails."""
    vault = tmp_path / "vault"
    _page(vault, "references/old.md", extra="superseded_by: does-not-exist")

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["broken_links"] == []
    assert report["findings"]["superseded_dangling"] == [
        {"page": "references/old.md", "target": "does-not-exist", "issue": "missing_target"}
    ]
    assert report["status"] == "warn"


def test_lint_passes_a_valid_supersession_chain(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "references/old.md",
          extra="valid_until: 2026-03-31\nsuperseded_by: \"[[new]]\"")
    _page(vault, "references/new.md", extra="valid_from: 2026-04-01")

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["temporal_errors"] == []
    assert report["findings"]["superseded_dangling"] == []


# --- CLI -------------------------------------------------------------------

def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parents[1])
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True, check=False, text=True, env=env,
    )


def test_graph_query_cli_accepts_as_of(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "references/old-gateway.md", summary="The gateway is nginx.",
          extra="valid_until: 2026-03-31")
    _page(vault, "references/new-gateway.md", summary="The gateway is envoy.",
          extra="valid_from: 2026-04-01")

    result = _run("graph-query", str(vault), "gateway", "--as-of", "2026-01-15")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [c["page"] for c in payload["candidates"]] == ["references/old-gateway.md"]


def test_cli_rejects_a_malformed_as_of(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")

    result = _run("graph-query", str(vault), "alpha", "--as-of", "last tuesday")

    assert result.returncode == 1
    assert "is not a date" in result.stderr
