"""Regression tests for manually reviewed confidence and relationship linting."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from obsidian_wiki.lint import lint_vault
from obsidian_wiki.trust import (
    build_trust_ledger,
    check_trust_ledger,
    page_fingerprint,
    update_trust_ledger,
    write_trust_ledger,
)


def _page(
    vault: Path,
    relpath: str,
    *,
    confidence: float = 0.80,
    updated: str = "2026-07-12T17:38:39+07:00",
    body: str = "Reviewed material claim.",
    relationships: list[tuple[str, str]] | None = None,
) -> Path:
    path = vault / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"title: {path.stem}",
        f"category: {path.parts[-2] if len(path.parts) > 1 else 'concepts'}",
        "tags: [test]",
        "sources:",
        "  - github.com/example/repo@0123456789abcdef0123456789abcdef01234567",
        "created: 2026-07-01",
        f"updated: {updated}",
        f"base_confidence: {confidence:.2f}",
        "lifecycle: reviewed",
    ]
    if relationships:
        lines.append("relationships:")
        for relation_type, target in relationships:
            lines.extend([f"  - type: {relation_type}", f'    target: "[[{target}]]"'])
    lines.extend(["---", f"# {path.stem}", "", body, ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_ledger(vault: Path) -> Path:
    ledger = build_trust_ledger(vault, reviewed_at="2026-07-12T17:38:39+07:00")
    path = vault / "_meta" / "trust-ledger.json"
    write_trust_ledger(path, ledger)
    return path


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_reviewed_ledger_is_authoritative_instead_of_reclassifying_sources(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", confidence=0.53)
    _page(vault, "skills/beta.md", confidence=0.80)
    ledger_path = _write_ledger(vault)

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "pass"
    assert report["counts"] == {
        "reviewed": 2,
        "not_applicable": 0,
        "stale": 0,
        "unreviewed": 0,
        "score_mismatches": 0,
        "missing_pages": 0,
        "errors": 0,
    }
    assert {item["page"] for item in report["reviewed"]} == {
        "concepts/alpha.md",
        "skills/beta.md",
    }


def test_claim_change_invalidates_review_but_updated_timestamp_does_not(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md", confidence=0.53)
    ledger_path = _write_ledger(vault)

    page.write_text(page.read_text().replace("updated: 2026-07-12T17:38:39+07:00", "updated: 2026-07-13T09:00:00+07:00"))
    assert check_trust_ledger(vault, ledger_path)["counts"]["reviewed"] == 1

    page.write_text(page.read_text().replace("Reviewed material claim.", "Changed material claim."))
    report = check_trust_ledger(vault, ledger_path)
    assert report["status"] == "warn"
    assert report["stale"] == [{"page": "concepts/alpha.md", "reason": "material_fingerprint_changed"}]


def test_material_change_marks_review_stale(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md", confidence=0.53)
    ledger_path = _write_ledger(vault)
    page.write_text(page.read_text().replace("Reviewed material claim.", "Changed material claim."))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "warn"
    assert report["stale"] == [
        {"page": "concepts/alpha.md", "reason": "material_fingerprint_changed"}
    ]


def test_duplicate_confidence_field_fails_instead_of_bypassing_fingerprint(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md", confidence=0.53)
    ledger_path = _write_ledger(vault)
    page.write_text(page.read_text().replace("lifecycle: reviewed", "base_confidence: 0.99\nlifecycle: reviewed"))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"] == [
        {"page": "concepts/alpha.md", "issue": "duplicate top-level field: base_confidence"}
    ]


def test_volatile_field_with_nested_content_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    page.write_text(page.read_text().replace("updated: 2026-07-12T17:38:39+07:00", "updated: 2026-07-12T17:38:39+07:00\n  hidden: material"))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"] == [
        {"page": "concepts/alpha.md", "issue": "updated must be a scalar"}
    ]


def test_invalid_confidence_is_checked_before_stale_short_circuit(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    changed = page.read_text().replace("Reviewed material claim.", "Changed material claim.")
    page.write_text(changed.replace("base_confidence: 0.80", "base_confidence: nan"))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["stale"] == []
    assert report["errors"] == [
        {"page": "concepts/alpha.md", "issue": "base_confidence is not finite"}
    ]


def test_invalid_lifecycle_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    page.write_text(page.read_text().replace("lifecycle: reviewed", "lifecycle: totally-invalid"))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"] == [
        {"page": "concepts/alpha.md", "issue": "invalid lifecycle: totally-invalid"}
    ]


def test_owner_trust_schema_accepts_lifecycle_and_optional_fields(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    page.write_text(page.read_text().replace("base_confidence: 0.80\n", "").replace("lifecycle: reviewed", "lifecycle: active"))

    report = check_trust_ledger(
        vault,
        ledger_path,
        allowed_lifecycles={"active", "confirmed", "stub"},
        required_trust_keys=("updated",),
        schema_source="wiki/AGENTS.md",
    )

    assert report["status"] == "warn"
    assert report["errors"] == []
    assert report["not_applicable"] == [
        {
            "page": "concepts/alpha.md",
            "reason": "base_confidence_absent_by_owner_schema",
        }
    ]
    assert report["stale"] == [
        {
            "page": "concepts/alpha.md",
            "reason": "confidence_not_applicable_but_ledger_entry_exists",
        }
    ]
    assert report["schema"] == {
        "source": "wiki/AGENTS.md",
        "allowed_lifecycles": ["active", "confirmed", "stub"],
        "required_trust_fields": ["updated"],
    }


def test_owner_schema_build_excludes_no_confidence_page_as_not_applicable(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(page.read_text().replace("base_confidence: 0.80\n", ""))

    ledger = build_trust_ledger(
        vault,
        reviewed_at="2026-08-05T12:00:00+09:00",
        required_trust_keys=("updated",),
    )

    assert ledger["pages"] == {}
    assert ledger["not_applicable"] == ["concepts/alpha.md"]
    assert page_fingerprint(page, required_trust_keys=("updated",)).startswith("sha256:")


def test_owner_schema_update_removes_stale_no_confidence_entry(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    page.write_text(page.read_text().replace("base_confidence: 0.80\n", ""))

    before = check_trust_ledger(
        vault,
        ledger_path,
        required_trust_keys=("updated",),
    )
    assert before["status"] == "warn"
    assert before["stale"] == [
        {
            "page": "concepts/alpha.md",
            "reason": "confidence_not_applicable_but_ledger_entry_exists",
        }
    ]

    ledger = update_trust_ledger(
        vault,
        ledger_path,
        reviewed_at="2026-08-05T13:00:00+09:00",
        page_paths=["concepts/alpha.md"],
        required_trust_keys=("updated",),
    )
    assert ledger["pages"] == {}
    assert ledger["not_applicable"] == ["concepts/alpha.md"]
    assert ledger["removed_not_applicable"] == ["concepts/alpha.md"]
    write_trust_ledger(ledger_path, ledger, vault=vault)

    after = check_trust_ledger(
        vault,
        ledger_path,
        required_trust_keys=("updated",),
    )
    assert after["status"] == "pass"
    assert after["counts"]["not_applicable"] == 1
    assert after["stale"] == []


def test_owner_trust_schema_rejects_unknown_lifecycle_typo(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    page.write_text(page.read_text().replace("lifecycle: reviewed", "lifecycle: activ"))

    report = check_trust_ledger(
        vault,
        ledger_path,
        allowed_lifecycles={"active", "confirmed", "stub"},
        required_trust_keys=("updated",),
        schema_source="wiki/AGENTS.md",
    )

    assert report["status"] == "fail"
    assert report["errors"] == [
        {"page": "concepts/alpha.md", "issue": "invalid lifecycle: activ"}
    ]


def test_owner_lifecycle_propagates_through_record_update_and_check(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(page.read_text().replace("lifecycle: reviewed", "lifecycle: active"))
    schema = {
        "allowed_lifecycles": {"active", "confirmed", "stub"},
        "required_trust_keys": ("base_confidence", "lifecycle", "updated"),
    }

    ledger = build_trust_ledger(
        vault,
        reviewed_at="2026-08-05T12:00:00+09:00",
        **schema,
    )
    ledger_path = vault / "_meta" / "trust-ledger.json"
    write_trust_ledger(ledger_path, ledger, vault=vault)
    assert check_trust_ledger(vault, ledger_path, schema_source="wiki/AGENTS.md", **schema)["status"] == "pass"

    page.write_text(page.read_text().replace("Reviewed material claim.", "Reviewed updated claim."))
    updated = update_trust_ledger(
        vault,
        ledger_path,
        reviewed_at="2026-08-05T13:00:00+09:00",
        page_paths=["concepts/alpha.md"],
        **schema,
    )
    write_trust_ledger(ledger_path, updated, vault=vault)
    assert check_trust_ledger(vault, ledger_path, schema_source="wiki/AGENTS.md", **schema)["status"] == "pass"


def test_owner_lifecycle_cli_record_then_check(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(page.read_text().replace("lifecycle: reviewed", "lifecycle: active"))
    schema_args = (
        "--allow-lifecycle",
        "active",
        "--schema-source",
        "wiki/AGENTS.md",
    )

    record = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--all",
        "--reviewed-at",
        "2026-08-05T12:00:00+09:00",
        "--approved",
        "--json",
        *schema_args,
    )
    assert record.returncode == 0, record.stderr
    assert json.loads(record.stdout)["schema"]["source"] == "wiki/AGENTS.md"

    check = _run_cli(home, "trust-check", str(vault), "--json", *schema_args)
    assert check.returncode == 0, check.stderr
    assert json.loads(check.stdout)["status"] == "pass"


def test_mismatched_scalar_quotes_fail_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    page.write_text(page.read_text().replace("lifecycle: reviewed", 'lifecycle: "reviewed\''))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"] == [
        {"page": "concepts/alpha.md", "issue": 'invalid lifecycle: "reviewed\''}
    ]


def test_invalid_updated_timestamp_fails_before_fingerprint_match(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    page.write_text(
        page.read_text().replace(
            "updated: 2026-07-12T17:38:39+07:00",
            "updated: definitely-not-a-timestamp",
        )
    )

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"] == [
        {"page": "concepts/alpha.md", "issue": "updated is not an ISO-8601 date or timestamp"}
    ]


def test_inline_comments_on_scalar_trust_fields_remain_valid(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(
        page.read_text()
        .replace("base_confidence: 0.80", "base_confidence: 0.80 # reviewed score")
        .replace("lifecycle: reviewed", "lifecycle: reviewed # human-reviewed")
    )

    ledger_path = _write_ledger(vault)
    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "pass"
    assert report["counts"]["reviewed"] == 1


def test_score_only_change_is_a_failing_mismatch_not_stale(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md", confidence=0.53)
    ledger_path = _write_ledger(vault)
    page.write_text(page.read_text().replace("base_confidence: 0.53", "base_confidence: 0.88"))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["stale"] == []
    assert report["score_mismatches"] == [
        {"page": "concepts/alpha.md", "stored": 0.88, "reviewed": 0.53}
    ]


def test_new_page_requires_manual_review_instead_of_formula_guess(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    _page(vault, "concepts/new.md", confidence=0.95)

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "warn"
    assert report["unreviewed"] == [{"page": "concepts/new.md", "reason": "not_in_manual_ledger"}]


def test_standalone_trust_check_fails_for_page_missing_trust_fields(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(
        "\n".join(
            line
            for line in page.read_text().splitlines()
            if not line.startswith(("base_confidence:", "lifecycle:"))
        )
        + "\n"
    )
    ledger_path = vault / "_meta" / "trust-ledger.json"
    write_trust_ledger(
        ledger_path,
        {
            "schema_version": 1,
            "method": "manual-lineage-and-claim-coverage-v1",
            "reviewed_at": "2026-07-12T17:38:39+07:00",
            "pages": {},
        },
        vault=vault,
    )

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"] == [
        {"page": "concepts/alpha.md", "issue": "missing base_confidence"}
    ]


def test_lint_vault_requires_trust_ledger_by_default(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")

    report = lint_vault(vault)

    # Staged migration (#28, #146): a missing ledger only warns until the
    # vault owner opts into strict_trust.
    assert report["status"] == "warn"
    assert report["findings"]["confidence_ledger_errors"] == [
        {"issue": "ledger_missing", "path": str(vault / "_meta" / "trust-ledger.json")}
    ]

    strict_report = lint_vault(vault, strict_trust=True)
    assert strict_report["status"] == "fail"


def test_non_object_ledger_fails_cleanly(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = vault / "_meta" / "trust-ledger.json"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text("[]\n")

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"] == [{"issue": "ledger_must_be_an_object"}]


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    text = ledger_path.read_text()
    ledger_path.write_text(text.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"][0]["issue"] == "ledger_unreadable"
    assert "duplicate JSON key" in report["errors"][0]["detail"]


def test_boolean_schema_version_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    ledger = json.loads(ledger_path.read_text())
    ledger["schema_version"] = True
    ledger_path.write_text(json.dumps(ledger))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"][0]["issue"] == "unsupported_schema_version"


def test_invalid_utf8_ledger_returns_structured_failure(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = vault / "_meta" / "trust-ledger.json"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_bytes(b"\xff\xfe")

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"][0]["issue"] == "ledger_unreadable"


def test_invalid_review_timestamp_is_rejected_by_record_cli(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")

    record = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--all",
        "--reviewed-at",
        "not-an-iso-timestamp",
        "--approved",
        "--json",
    )

    assert record.returncode == 1
    assert "reviewed_at must be an ISO-8601 timestamp with timezone" in record.stderr
    assert "Traceback" not in record.stderr
    assert not (vault / "_meta" / "trust-ledger.json").exists()


def test_invalid_ledger_review_timestamp_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    ledger = json.loads(ledger_path.read_text())
    ledger["reviewed_at"] = "yesterday"
    ledger_path.write_text(json.dumps(ledger))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"] == [{"issue": "invalid_reviewed_at"}]


def test_trust_writer_rejects_symlinked_meta_directory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    (vault / "_meta").symlink_to(outside, target_is_directory=True)
    ledger = {"schema_version": 1, "method": "manual-lineage-and-claim-coverage-v1", "pages": {}}

    try:
        write_trust_ledger(vault / "_meta" / "trust-ledger.json", ledger, vault=vault)
    except RuntimeError as exc:
        assert "outside the resolved vault" in str(exc) or "symlink" in str(exc)
    else:
        raise AssertionError("symlinked _meta directory was accepted")

    assert not (outside / "trust-ledger.json").exists()


def test_trust_writer_never_follows_predictable_temp_symlink(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    meta = vault / "_meta"
    meta.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel\n")
    (meta / "trust-ledger.json.tmp").symlink_to(outside)
    ledger = {"schema_version": 1, "method": "manual-lineage-and-claim-coverage-v1", "pages": {}}

    write_trust_ledger(meta / "trust-ledger.json", ledger, vault=vault)

    assert outside.read_text() == "sentinel\n"
    assert json.loads((meta / "trust-ledger.json").read_text())["schema_version"] == 1


def test_trust_writer_rejects_symlinked_ledger_destination(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    meta = vault / "_meta"
    meta.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel\n")
    destination = meta / "trust-ledger.json"
    destination.symlink_to(outside)
    ledger = {"schema_version": 1, "method": "manual-lineage-and-claim-coverage-v1", "pages": {}}

    try:
        write_trust_ledger(destination, ledger, vault=vault)
    except RuntimeError as exc:
        assert "outside the resolved vault" in str(exc) or "symlink" in str(exc)
    else:
        raise AssertionError("symlinked ledger destination was accepted")

    assert outside.read_text() == "sentinel\n"


def test_out_of_range_reviewed_confidence_is_invalid_ledger_data(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    ledger = json.loads(ledger_path.read_text())
    ledger["pages"]["concepts/alpha.md"]["reviewed_confidence"] = 2.0
    ledger_path.write_text(json.dumps(ledger))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"] == [{"page": "concepts/alpha.md", "issue": "invalid_ledger_entry"}]


def test_boolean_reviewed_confidence_is_invalid_ledger_data(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    ledger = json.loads(ledger_path.read_text())
    ledger["pages"]["concepts/alpha.md"]["reviewed_confidence"] = True
    ledger_path.write_text(json.dumps(ledger))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"] == [{"page": "concepts/alpha.md", "issue": "invalid_ledger_entry"}]


def test_non_standard_json_number_is_unreadable_not_approved(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    ledger = json.loads(ledger_path.read_text())
    ledger["pages"]["concepts/alpha.md"]["reviewed_confidence"] = float("nan")
    ledger_path.write_text(json.dumps(ledger))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"][0]["issue"] == "ledger_unreadable"


def test_malformed_fingerprint_and_entry_timestamp_fail_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    ledger = json.loads(ledger_path.read_text())
    entry = ledger["pages"]["concepts/alpha.md"]
    entry["material_fingerprint"] = "garbage"
    entry["reviewed_at"] = "yesterday"
    ledger_path.write_text(json.dumps(ledger))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["errors"] == [{"page": "concepts/alpha.md", "issue": "invalid_ledger_entry"}]


def test_non_object_page_entry_is_invalid_not_unreviewed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = _write_ledger(vault)
    ledger = json.loads(ledger_path.read_text())
    ledger["pages"]["concepts/alpha.md"] = []
    ledger_path.write_text(json.dumps(ledger))

    report = check_trust_ledger(vault, ledger_path)

    assert report["status"] == "fail"
    assert report["unreviewed"] == []
    assert report["errors"] == [{"page": "concepts/alpha.md", "issue": "invalid_ledger_entry"}]


def test_lint_vault_surfaces_manual_trust_status_without_formula_drift(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", confidence=0.53, relationships=[("related_to", "skills/beta")])
    _page(vault, "skills/beta.md", confidence=0.80, relationships=[("related_to", "concepts/alpha")])
    _write_ledger(vault)

    report = lint_vault(vault)

    assert report["findings"]["confidence_review_stale"] == []
    assert report["findings"]["confidence_unreviewed"] == []
    assert report["findings"]["confidence_mismatches"] == []
    assert report["findings"]["typed_relationship_issues"] == []
    assert report["stats"]["trust"]["reviewed"] == 2


def test_typed_relationship_resolver_uses_exact_vault_paths(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "projects/demo/alpha.md", relationships=[("implements", "projects/demo/beta")])
    _page(vault, "projects/demo/beta.md", relationships=[("related_to", "projects/demo/alpha")])
    _page(vault, "concepts/broken.md", relationships=[("related_to", "skills/missing")])

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["typed_relationship_issues"] == [
        {
            "page": "concepts/broken.md",
            "index": 0,
            "issue": "missing_target",
            "target": "skills/missing",
        }
    ]


def test_target_first_relationship_order_is_parsed_and_validated(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    _page(vault, "skills/beta.md")
    page.write_text(
        page.read_text().replace(
            "lifecycle: reviewed",
            'lifecycle: reviewed\nrelationships:\n  - target: "[[skills/missing]]"\n    type: related_to',
        )
    )

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["typed_relationship_issues"] == [
        {
            "page": "concepts/alpha.md",
            "index": 0,
            "issue": "missing_target",
            "target": "skills/missing",
        }
    ]


def test_dash_only_relationship_item_is_parsed_and_validated(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(
        page.read_text().replace(
            "lifecycle: reviewed",
            'lifecycle: reviewed\nrelationships:\n  -\n    target: "[[skills/missing]]"\n    type: related_to',
        )
    )

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["typed_relationship_issues"] == [
        {
            "page": "concepts/alpha.md",
            "index": 0,
            "issue": "missing_target",
            "target": "skills/missing",
        }
    ]


def test_unknown_relationship_field_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    _page(vault, "skills/beta.md")
    page.write_text(
        page.read_text().replace(
            "lifecycle: reviewed",
            'lifecycle: reviewed\nrelationships:\n  - target: "[[skills/beta]]"\n    type: related_to\n    weight: 5',
        )
    )

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["typed_relationship_issues"] == [
        {
            "page": "concepts/alpha.md",
            "index": 0,
            "issue": "malformed_relationship_entry",
        }
    ]


def test_basename_only_relationship_is_rejected_when_ambiguous(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", relationships=[("related_to", "beta")])
    _page(vault, "skills/beta.md")
    _page(vault, "projects/demo/beta.md")

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["typed_relationship_issues"] == [
        {
            "page": "concepts/alpha.md",
            "index": 0,
            "issue": "ambiguous_target",
            "target": "beta",
        }
    ]


def test_qualified_relationship_is_ambiguous_when_normalized_paths_collide(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", relationships=[("related_to", "skills/foo-bar")])
    _page(vault, "skills/Foo Bar.md")
    _page(vault, "skills/foo-bar.md")

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["typed_relationship_issues"] == [
        {
            "page": "concepts/alpha.md",
            "index": 0,
            "issue": "ambiguous_target",
            "target": "skills/foo-bar",
        }
    ]


def test_empty_inline_relationship_list_is_valid(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(page.read_text().replace("lifecycle: reviewed", "lifecycle: reviewed\nrelationships: []"))

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["typed_relationship_issues"] == []


def test_lint_excludes_bootstrap_scaffolding_from_page_health(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", relationships=[("related_to", "concepts/beta")])
    _page(vault, "concepts/beta.md", relationships=[("related_to", "concepts/alpha")])
    bootstrap = vault / "_bootstrap" / "README.md"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text("# Setup instructions\n")

    report = lint_vault(vault)

    serialized = json.dumps(report)
    assert "_bootstrap/README.md" not in serialized


def test_lint_flags_content_page_missing_trust_schema(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(
        "\n".join(
            line
            for line in page.read_text().splitlines()
            if not line.startswith(("base_confidence:", "lifecycle:"))
        )
        + "\n"
    )

    report = lint_vault(vault)

    # Staged migration (#28, #146): legacy pages predating the trust schema
    # warn instead of failing lint until the owner opts into strict_trust.
    assert report["status"] == "warn"
    assert report["findings"]["missing_frontmatter"] == []
    assert report["findings"]["confidence_missing_fields"] == [
        {"page": "concepts/alpha.md", "missing": ["base_confidence", "lifecycle"]}
    ]

    strict_report = lint_vault(vault, strict_trust=True)
    assert strict_report["status"] == "fail"


def test_required_trust_ledger_fails_closed_when_missing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")

    report = lint_vault(vault, require_trust_ledger=True)

    # require_trust_ledger controls whether the ledger check runs at all (and
    # is thus reported); strict_trust controls whether its findings fail lint.
    assert report["status"] == "warn"
    assert report["findings"]["confidence_ledger_errors"] == [
        {"issue": "ledger_missing", "path": str(vault / "_meta" / "trust-ledger.json")}
    ]

    strict_report = lint_vault(vault, require_trust_ledger=True, strict_trust=True)
    assert strict_report["status"] == "fail"


def test_trust_record_cli_requires_explicit_approval(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")

    proc = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--all",
        "--reviewed-at",
        "2026-07-12T17:38:39+07:00",
        "--json",
    )

    assert proc.returncode == 2
    assert "--approved" in proc.stderr
    assert not (vault / "_meta" / "trust-ledger.json").exists()


def test_trust_record_and_check_cli_round_trip(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", confidence=0.53)

    record = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--all",
        "--reviewed-at",
        "2026-07-12T17:38:39+07:00",
        "--approved",
        "--json",
    )
    check = _run_cli(home, "trust-check", str(vault), "--json")

    assert record.returncode == 0, record.stderr
    assert json.loads(record.stdout)["recorded_pages"] == 1
    assert check.returncode == 0, check.stderr
    payload = json.loads(check.stdout)
    assert payload["status"] == "pass"
    assert payload["counts"]["reviewed"] == 1


def test_owner_schema_cli_excludes_then_removes_no_confidence_ledger_entry(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    _write_ledger(vault)
    page.write_text(page.read_text().replace("base_confidence: 0.80\n", ""))
    schema_args = ("--required-trust-field", "updated")

    stale = _run_cli(home, "trust-check", str(vault), "--json", *schema_args)
    assert stale.returncode == 0, stale.stderr
    stale_payload = json.loads(stale.stdout)
    assert stale_payload["status"] == "warn"
    assert stale_payload["stale"] == [
        {
            "page": "concepts/alpha.md",
            "reason": "confidence_not_applicable_but_ledger_entry_exists",
        }
    ]

    record = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--page",
        "concepts/alpha.md",
        "--reviewed-at",
        "2026-08-05T13:00:00+09:00",
        "--approved",
        "--json",
        *schema_args,
    )
    assert record.returncode == 0, record.stderr
    record_payload = json.loads(record.stdout)
    assert record_payload["recorded_pages"] == 0
    assert record_payload["not_applicable_pages"] == ["concepts/alpha.md"]
    assert record_payload["removed_not_applicable"] == ["concepts/alpha.md"]

    clean = _run_cli(home, "trust-check", str(vault), "--json", *schema_args)
    assert clean.returncode == 0, clean.stderr
    clean_payload = json.loads(clean.stdout)
    assert clean_payload["status"] == "pass"
    assert clean_payload["counts"]["not_applicable"] == 1
    assert clean_payload["stale"] == []

    rebuilt = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--all",
        "--reviewed-at",
        "2026-08-05T14:00:00+09:00",
        "--approved",
        "--json",
        *schema_args,
    )
    assert rebuilt.returncode == 0, rebuilt.stderr
    rebuilt_payload = json.loads(rebuilt.stdout)
    assert rebuilt_payload["recorded_pages"] == 0
    assert rebuilt_payload["not_applicable_pages"] == ["concepts/alpha.md"]


def test_trust_record_all_human_output_lists_no_confidence_without_removal(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(page.read_text().replace("base_confidence: 0.80\n", ""))

    record = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--all",
        "--reviewed-at",
        "2026-08-05T14:00:00+09:00",
        "--approved",
        "--required-trust-field",
        "updated",
    )

    assert record.returncode == 0
    assert "removed obsolete trust ledger entries" not in record.stderr
    assert record.stdout == (
        f"recorded 0 reviewed page(s) in {vault.resolve() / '_meta' / 'trust-ledger.json'}\n"
        "not applicable (excluded from trust review): 1 page(s)\n"
        "  - concepts/alpha.md\n"
        "obsolete ledger entries removed: 0 page(s)\n"
    )


def test_trust_record_all_human_output_warns_when_rebuild_removes_stale_entry(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    _write_ledger(vault)
    page.write_text(page.read_text().replace("base_confidence: 0.80\n", ""))

    record = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--all",
        "--reviewed-at",
        "2026-08-05T14:00:00+09:00",
        "--approved",
        "--required-trust-field",
        "updated",
    )

    assert record.returncode == 0
    assert "not applicable (excluded from trust review): 1 page(s)" in record.stdout
    assert "obsolete ledger entries removed: 1 page(s)\n  - concepts/alpha.md" in record.stdout
    assert record.stderr.endswith(
        "warning: removed obsolete trust ledger entries because base_confidence is not "
        "applicable: concepts/alpha.md\n"
    )
    assert record.stderr.count("warning: removed obsolete trust ledger entries") == 1
    ledger = json.loads((vault / "_meta" / "trust-ledger.json").read_text())
    assert ledger["pages"] == {}
    assert ledger["removed_not_applicable"] == ["concepts/alpha.md"]


def test_trust_record_page_human_output_warns_when_stale_entry_is_removed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    _write_ledger(vault)
    page.write_text(page.read_text().replace("base_confidence: 0.80\n", ""))

    record = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--page",
        "concepts/alpha.md",
        "--reviewed-at",
        "2026-08-05T14:00:00+09:00",
        "--approved",
        "--required-trust-field",
        "updated",
    )

    assert record.returncode == 0
    assert "not applicable (excluded from trust review): 1 page(s)\n  - concepts/alpha.md" in record.stdout
    assert "obsolete ledger entries removed: 1 page(s)\n  - concepts/alpha.md" in record.stdout
    assert "warning: removed obsolete trust ledger entries" in record.stderr
    assert "concepts/alpha.md" in record.stderr


def test_trust_record_page_human_output_reports_zero_removals_without_warning(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(page.read_text().replace("base_confidence: 0.80\n", ""))

    record = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--page",
        "concepts/alpha.md",
        "--reviewed-at",
        "2026-08-05T14:00:00+09:00",
        "--approved",
        "--required-trust-field",
        "updated",
    )

    assert record.returncode == 0
    assert "not applicable (excluded from trust review): 1 page(s)\n  - concepts/alpha.md" in record.stdout
    assert "obsolete ledger entries removed: 0 page(s)" in record.stdout
    assert "removed obsolete trust ledger entries" not in record.stderr


def test_explicit_vault_cli_override_reports_cli_schema_source(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "explicit-vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(page.read_text().replace("base_confidence: 0.80\n", ""))

    record = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--all",
        "--reviewed-at",
        "2026-08-05T14:00:00+09:00",
        "--approved",
        "--required-trust-field",
        "updated",
        "--json",
    )

    assert record.returncode == 0, record.stderr
    assert "removed obsolete trust ledger entries" not in record.stderr
    assert json.loads(record.stdout)["schema"]["source"] == "cli:explicit-vault"


def test_partial_trust_record_does_not_approve_other_stale_pages(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    alpha = _page(vault, "concepts/alpha.md", confidence=0.53)
    beta = _page(vault, "skills/beta.md", confidence=0.80)
    _write_ledger(vault)
    alpha.write_text(alpha.read_text().replace("Reviewed material claim.", "Reviewed alpha change."))
    beta.write_text(beta.read_text().replace("Reviewed material claim.", "Unreviewed beta change."))

    record = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--page",
        "concepts/alpha.md",
        "--reviewed-at",
        "2026-07-13T09:00:00+07:00",
        "--approved",
        "--json",
    )
    check = _run_cli(home, "trust-check", str(vault), "--json")

    assert record.returncode == 0, record.stderr
    assert json.loads(record.stdout)["recorded_pages"] == 1
    payload = json.loads(check.stdout)
    assert payload["counts"]["reviewed"] == 1
    assert payload["stale"] == [
        {"page": "skills/beta.md", "reason": "material_fingerprint_changed"}
    ]


def test_partial_trust_record_reports_malformed_ledger_without_traceback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    ledger_path = vault / "_meta" / "trust-ledger.json"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text("[]\n")

    record = _run_cli(
        home,
        "trust-record",
        str(vault),
        "--page",
        "concepts/alpha.md",
        "--reviewed-at",
        "2026-07-13T09:00:00+07:00",
        "--approved",
        "--json",
    )

    assert record.returncode == 1
    assert "error: cannot update trust ledger" in record.stderr
    assert "Traceback" not in record.stderr
    assert ledger_path.read_text() == "[]\n"
