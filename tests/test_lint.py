"""Tests for vault linting."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from obsidian_wiki.lint import lint_vault
from obsidian_wiki.trust import build_trust_ledger, write_trust_ledger


def _page(
    vault: Path,
    relpath: str,
    *,
    title: str | None = None,
    summary: str | None = "Short summary.",
    tags: str = "[test]",
    sources: str = "[manual]",
    created: str = "2026-07-01",
    updated: str = "2026-07-01",
    links: list[str] | None = None,
    include_frontmatter: bool = True,
    include_trust_fields: bool = True,
) -> Path:
    path = vault / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if include_frontmatter:
        lines.extend(
            [
                "---",
                f"title: {title or path.stem}",
                "category: concepts",
                f"tags: {tags}",
                f"sources: {sources}",
                f"created: {created}",
                f"updated: {updated}",
            ]
        )
        if include_trust_fields:
            lines.extend(["base_confidence: 0.80", "lifecycle: reviewed"])
        if summary is not None:
            lines.append(f"summary: {summary}")
        lines.append("---")
    lines.append(f"# {title or path.stem}")
    for link in links or []:
        lines.append(f"[[{link}]]")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    # Run from the fake HOME, not the repo: config resolution walks up from cwd
    # looking for a `.env`, and a developer's own .env at the repo root would
    # otherwise override the fixture config and point at their real vault.
    home.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        env=env,
        cwd=home,
    )


def _run_at(home: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PYTHONPATH"] = str(Path(__file__).parents[1])
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        env=env,
        cwd=cwd,
    )


def test_lint_vault_passes_clean_graph(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "index.md", links=["alpha"])
    _page(vault, "log.md", links=["alpha"])
    _page(vault, "hot.md", links=["alpha"])
    _page(vault, "concepts/alpha.md", links=["beta"])
    _page(vault, "concepts/beta.md", links=["alpha"])
    ledger = build_trust_ledger(vault, reviewed_at="2026-07-12T17:38:39+07:00")
    write_trust_ledger(vault / "_meta" / "trust-ledger.json", ledger, vault=vault)

    report = lint_vault(vault)

    assert report["status"] == "pass"
    assert report["findings"]["broken_links"] == []
    assert report["findings"]["missing_frontmatter"] == []


def test_lint_vault_fails_on_broken_links_and_missing_frontmatter(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", links=["ghost"])
    _page(vault, "concepts/beta.md", include_frontmatter=False)

    report = lint_vault(vault)

    assert report["status"] == "fail"
    assert report["findings"]["broken_links"] == [{"page": "concepts/alpha.md", "target": "ghost"}]
    assert any(item["page"] == "concepts/beta.md" for item in report["findings"]["missing_frontmatter"])


def test_lint_vault_broken_links_ignores_embeds_and_normalises_md_and_escaped_pipe(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    _page(vault, "concepts/beta.md")
    (vault / "diagram.png").write_text("not a real png\n", encoding="utf-8")
    _page(
        vault,
        "concepts/index.md",
        links=["alpha.md", "diagram.png", "ghost"],
    )
    # A Markdown-table cell escapes a literal pipe, which _WIKILINK_RE's own
    # alternation consumes into the alias group it does not capture.
    index = vault / "concepts" / "index.md"
    index.write_text(index.read_text(encoding="utf-8") + "| [[beta\\|B]] | note |\n", encoding="utf-8")

    report = lint_vault(vault)

    assert report["findings"]["broken_links"] == [{"page": "concepts/index.md", "target": "ghost"}]


def test_lint_vault_keeps_links_to_pages_whose_name_contains_a_dot(tmp_path: Path) -> None:
    """A dot in a page name ("Node.js", "v1.2 notes") is not a file extension —
    dropping those links would report the target as an orphan."""
    vault = tmp_path / "vault"
    for name in ("Node.js", "v1.2 release notes"):
        _page(vault, f"entities/{name}.md")
    _page(vault, "concepts/index.md", links=["Node.js", "v1.2 release notes"])

    report = lint_vault(vault)

    assert report["findings"]["broken_links"] == []
    assert report["findings"]["orphan_pages"] == []
    assert report["stats"]["link_count"] == 2


def test_lint_vault_warns_on_duplicates_missing_summaries_and_orphans(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", title="Same Title", summary=None)
    _page(vault, "references/beta.md", title="Same Title")
    ledger = build_trust_ledger(vault, reviewed_at="2026-07-12T17:38:39+07:00")
    write_trust_ledger(vault / "_meta" / "trust-ledger.json", ledger, vault=vault)

    report = lint_vault(vault)

    assert report["status"] == "warn"
    assert report["findings"]["duplicate_titles"]
    assert "concepts/alpha.md" in report["findings"]["missing_summaries"]
    assert "references/beta.md" in report["findings"]["orphan_pages"]


def test_lint_cli_uses_configured_vault_and_strict_mode(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", summary=None)

    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(f'OBSIDIAN_VAULT_PATH="{vault}"\n', encoding="utf-8")
    ledger = build_trust_ledger(vault, reviewed_at="2026-07-12T17:38:39+07:00")
    write_trust_ledger(vault / "_meta" / "trust-ledger.json", ledger)

    proc = _run(home, "lint", "--json", "--strict")

    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["status"] == "warn"
    assert "concepts/alpha.md" in data["findings"]["missing_summaries"]


def test_lint_vault_legacy_pages_without_trust_schema_warn_by_default(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", include_trust_fields=False)

    report = lint_vault(vault)

    assert report["status"] == "warn"
    assert report["findings"]["missing_frontmatter"] == []
    assert report["findings"]["confidence_missing_fields"] == [
        {"page": "concepts/alpha.md", "missing": ["base_confidence", "lifecycle"]}
    ]
    assert any(item["issue"] == "ledger_missing" for item in report["findings"]["confidence_ledger_errors"])


def test_lint_vault_missing_ledger_is_warning_not_failure_by_default(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")

    report = lint_vault(vault)

    assert report["status"] == "warn"
    assert report["findings"]["confidence_ledger_errors"]


def test_lint_vault_strict_trust_fails_on_missing_fields_and_ledger(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", include_trust_fields=False)

    report = lint_vault(vault, strict_trust=True)

    assert report["status"] == "fail"


def test_lint_vault_strict_trust_still_passes_clean_reviewed_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", links=["beta"])
    _page(vault, "concepts/beta.md", links=["alpha"])
    ledger = build_trust_ledger(vault, reviewed_at="2026-07-12T17:38:39+07:00")
    write_trust_ledger(vault / "_meta" / "trust-ledger.json", ledger, vault=vault)

    report = lint_vault(vault, strict_trust=True)

    assert report["status"] == "pass"


def test_lint_cli_strict_trust_flag_fails_legacy_vault(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", include_trust_fields=False)

    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(f'OBSIDIAN_VAULT_PATH="{vault}"\n', encoding="utf-8")

    default_proc = _run(home, "lint", "--json")
    assert default_proc.returncode == 0
    assert json.loads(default_proc.stdout)["status"] == "warn"

    strict_proc = _run(home, "lint", "--json", "--strict-trust")
    assert strict_proc.returncode == 1
    assert json.loads(strict_proc.stdout)["status"] == "fail"


def test_owner_schema_accepts_extensions_optional_trust_and_reports_source(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    extensions = [
        ("active", "synthesizes"),
        ("confirmed", "builds_on"),
        ("stub", "complements"),
        ("active", "refines"),
        ("confirmed", "contrasts_with"),
    ]
    names = [f"page-{index}" for index in range(len(extensions))]
    for index, ((lifecycle, relationship), name) in enumerate(zip(extensions, names)):
        target = names[(index + 1) % len(names)]
        page = _page(vault, f"concepts/{name}.md", links=[target])
        text = page.read_text()
        text = text.replace("base_confidence: 0.80\n", "")
        text = text.replace(
            "lifecycle: reviewed",
            f'lifecycle: {lifecycle}\nrelationships:\n  - type: {relationship}\n    target: "[[concepts/{target}]]"',
        )
        page.write_text(text)

    report = lint_vault(
        vault,
        require_trust_ledger=False,
        allowed_lifecycles={"active", "confirmed", "stub"},
        allowed_relationship_types={item[1] for item in extensions},
        required_trust_fields=("updated",),
        schema_source="wiki/AGENTS.md",
    )

    assert report["findings"]["confidence_missing_fields"] == []
    assert report["findings"]["typed_relationship_issues"] == []
    assert report["schema"] == {
        "source": "wiki/AGENTS.md",
        "allowed_lifecycles": ["active", "confirmed", "stub"],
        "allowed_relationship_types": sorted(item[1] for item in extensions),
        "required_trust_fields": ["updated"],
    }


def test_invalid_configured_required_trust_field_fails_closed_for_all_cli_paths(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    vault = tmp_path / "vault"
    project.mkdir()
    _page(vault, "concepts/alpha.md")
    (project / ".env").write_text(
        f'OBSIDIAN_VAULT_PATH="{vault}"\n'
        "OBSIDIAN_REQUIRED_TRUST_FIELDS=updated,base_confidnce\n",
        encoding="utf-8",
    )
    expected = (
        "error: invalid OBSIDIAN_REQUIRED_TRUST_FIELDS value(s): base_confidnce; "
        "allowed values: base_confidence, lifecycle, lifecycle_changed, updated"
    )
    commands = (
        ("lint", "--json"),
        (
            "trust-record",
            "--all",
            "--reviewed-at",
            "2026-08-05T12:00:00+09:00",
            "--approved",
            "--json",
        ),
        ("trust-check", "--json"),
    )

    for command in commands:
        proc = _run_at(home, project, *command)
        assert proc.returncode == 1, (command, proc.stdout, proc.stderr)
        assert proc.stdout == ""
        assert expected in proc.stderr
        assert "Traceback" not in proc.stderr

    assert not (vault / "_meta" / "trust-ledger.json").exists()


def test_empty_relationship_cli_extension_cannot_hide_missing_relation_type(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    alpha = _page(vault, "concepts/alpha.md", links=["beta"])
    _page(vault, "concepts/beta.md", links=["alpha"])
    alpha.write_text(
        alpha.read_text().replace(
            "summary: Short summary.",
            'summary: Short summary.\nrelationships:\n  - type:\n    target: "[[concepts/beta]]"',
        )
    )

    baseline = _run(home, "lint", str(vault), "--json")
    assert baseline.returncode == 0
    assert json.loads(baseline.stdout)["findings"]["typed_relationship_issues"] == [
        {"page": "concepts/alpha.md", "index": 0, "issue": "invalid_type", "type": ""}
    ]

    for value in ("", "   "):
        invalid = _run(
            home,
            "lint",
            str(vault),
            "--json",
            "--allow-relationship-type",
            value,
        )
        assert invalid.returncode == 1
        assert invalid.stdout == ""
        assert "error: invalid --allow-relationship-type value: must not be empty" in invalid.stderr
        assert "Traceback" not in invalid.stderr


def test_empty_cli_lifecycle_and_required_field_overrides_fail_closed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")

    for value in ("", "   "):
        lifecycle = _run(
            home,
            "lint",
            str(vault),
            "--json",
            "--allow-lifecycle",
            value,
        )
        assert lifecycle.returncode == 1
        assert lifecycle.stdout == ""
        assert "error: invalid --allow-lifecycle value: must not be empty" in lifecycle.stderr
        assert "Traceback" not in lifecycle.stderr

    required = _run(
        home,
        "lint",
        str(vault),
        "--json",
        "--required-trust-field",
        "",
    )
    assert required.returncode == 2
    assert required.stdout == ""
    assert "invalid choice" in required.stderr
    assert "Traceback" not in required.stderr

    for value in ("", "   "):
        source = _run(
            home,
            "lint",
            str(vault),
            "--json",
            "--schema-source",
            value,
        )
        assert source.returncode == 1
        assert source.stdout == ""
        assert "error: invalid --schema-source value: must not be empty" in source.stderr
        assert "Traceback" not in source.stderr


def test_empty_configured_schema_values_fail_closed_for_all_cli_paths(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    commands = (
        ("lint", "--json"),
        (
            "trust-record",
            "--all",
            "--reviewed-at",
            "2026-08-05T12:00:00+09:00",
            "--approved",
            "--json",
        ),
        ("trust-check", "--json"),
    )

    for key in (
        "OBSIDIAN_ALLOWED_LIFECYCLES",
        "OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES",
        "OBSIDIAN_REQUIRED_TRUST_FIELDS",
        "OBSIDIAN_SCHEMA_SOURCE",
    ):
        project = tmp_path / key.lower()
        project.mkdir()
        (project / ".env").write_text(
            f'OBSIDIAN_VAULT_PATH="{vault}"\n{key}=   \n',
            encoding="utf-8",
        )
        for command in commands:
            invalid = _run_at(home, project, *command)
            assert invalid.returncode == 1, (key, command, invalid.stdout, invalid.stderr)
            assert invalid.stdout == ""
            detail = (
                "must not be empty"
                if key == "OBSIDIAN_SCHEMA_SOURCE"
                else "entries must not be empty"
            )
            assert f"error: invalid {key} value: {detail}" in invalid.stderr
            assert "Traceback" not in invalid.stderr

    assert not (vault / "_meta" / "trust-ledger.json").exists()


def test_blank_config_schema_source_cannot_be_masked_by_valid_cli_source(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(
        f'OBSIDIAN_VAULT_PATH="{vault}"\nOBSIDIAN_SCHEMA_SOURCE=   \n',
        encoding="utf-8",
    )
    ledger = vault / "_meta" / "trust-ledger.json"
    before = {
        path.relative_to(vault): path.read_bytes()
        for path in vault.rglob("*")
        if path.is_file()
    }
    commands = (
        ("lint", "--json", "--schema-source", "owner/AGENTS.md"),
        (
            "trust-record",
            "--all",
            "--reviewed-at",
            "2026-08-05T12:00:00+09:00",
            "--approved",
            "--json",
            "--schema-source",
            "owner/AGENTS.md",
        ),
        ("trust-check", "--json", "--schema-source", "owner/AGENTS.md"),
    )

    for command in commands:
        invalid = _run_at(home, project, *command)
        assert invalid.returncode == 1, (command, invalid.stdout, invalid.stderr)
        assert invalid.stdout == ""
        assert "error: invalid OBSIDIAN_SCHEMA_SOURCE value: must not be empty" in invalid.stderr
        assert "Traceback" not in invalid.stderr
        after = {
            path.relative_to(vault): path.read_bytes()
            for path in vault.rglob("*")
            if path.is_file()
        }
        assert after == before
        assert not ledger.exists()


def test_distributed_schema_config_contract_names_all_four_variables(tmp_path: Path) -> None:
    assert tmp_path.is_dir()
    root = Path(__file__).parents[1]
    variables = (
        "OBSIDIAN_ALLOWED_LIFECYCLES",
        "OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES",
        "OBSIDIAN_REQUIRED_TRUST_FIELDS",
        "OBSIDIAN_SCHEMA_SOURCE",
    )
    env_example = (root / ".env.example").read_text(encoding="utf-8")
    configuration = (root / "docs" / "configuration.md").read_text(encoding="utf-8")
    lint_skill = (root / ".skills" / "wiki-lint" / "SKILL.md").read_text(encoding="utf-8")
    llm_skill = (root / ".skills" / "llm-wiki" / "SKILL.md").read_text(encoding="utf-8")
    capture_skill = (root / ".skills" / "wiki-capture" / "SKILL.md").read_text(encoding="utf-8")

    for variable in variables:
        assert variable in env_example
        assert variable in configuration
        assert variable in lint_skill
        assert variable in llm_skill
        assert variable in capture_skill
    assert "CLI flags > these environment/config values >" in env_example
    assert "CLI flags > resolved environment/config values > framework defaults" in lint_skill
    assert "Empty or whitespace-only values fail closed" in env_example
    assert "fails closed" in lint_skill


def test_owner_schema_still_rejects_unknown_typos(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md", links=["beta"])
    _page(vault, "concepts/beta.md", links=["alpha"])
    page.write_text(
        page.read_text()
        .replace("lifecycle: reviewed", "lifecycle: activ")
        .replace(
            "---\n# alpha",
            'relationships:\n  - type: synthesizez\n    target: "[[concepts/beta]]"\n---\n# alpha',
        )
    )

    report = lint_vault(
        vault,
        require_trust_ledger=False,
        allowed_lifecycles={"active", "confirmed", "stub"},
        allowed_relationship_types={"synthesizes"},
        required_trust_fields=("updated",),
        schema_source="wiki/AGENTS.md",
    )

    assert report["findings"]["typed_relationship_issues"][0]["issue"] == "invalid_type"


def test_default_schema_remains_framework_compatible(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["schema"]["source"] == "framework-defaults"
    assert report["schema"]["required_trust_fields"] == ["base_confidence", "lifecycle"]
    assert "related_to" in report["schema"]["allowed_relationship_types"]


def test_lifecycle_typo_fails_without_ledger_when_ledger_is_not_required(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(page.read_text().replace("lifecycle: reviewed", "lifecycle: reveiwed"))

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["status"] == "fail"
    assert report["findings"]["trust_metadata_errors"] == [
        {"page": "concepts/alpha.md", "issue": "invalid lifecycle: reveiwed"}
    ]


def test_present_invalid_confidence_fails_without_ledger_when_not_required(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = _page(vault, "concepts/alpha.md")
    page.write_text(page.read_text().replace("base_confidence: 0.80", "base_confidence: 1.4"))

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["status"] == "fail"
    assert report["findings"]["trust_metadata_errors"] == [
        {"page": "concepts/alpha.md", "issue": "base_confidence is outside [0.0, 1.0]"}
    ]


def test_schema_config_is_scoped_to_explicit_cwd_and_named_vaults(tmp_path: Path) -> None:
    home = tmp_path / "home"
    global_vault = tmp_path / "global-vault"
    local_vault = tmp_path / "local-vault"
    explicit_vault = tmp_path / "explicit-vault"
    for vault in (global_vault, local_vault, explicit_vault):
        page = _page(vault, "concepts/alpha.md")
        page.write_text(page.read_text().replace("lifecycle: reviewed", "lifecycle: active"))

    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir(parents=True)
    (config_dir / "config").write_text(
        f'OBSIDIAN_VAULT_PATH="{global_vault}"\nOBSIDIAN_ALLOWED_LIFECYCLES=active\n',
        encoding="utf-8",
    )
    (config_dir / "config.owner").write_text(
        f'OBSIDIAN_VAULT_PATH="{local_vault}"\nOBSIDIAN_ALLOWED_LIFECYCLES=active\n',
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(
        f'OBSIDIAN_VAULT_PATH="{local_vault}"\nOBSIDIAN_ALLOWED_LIFECYCLES=active\n',
        encoding="utf-8",
    )

    explicit = _run_at(home, project, "lint", str(explicit_vault), "--json")
    assert explicit.returncode == 1
    assert json.loads(explicit.stdout)["findings"]["trust_metadata_errors"][0]["issue"] == "invalid lifecycle: active"

    local = _run_at(home, project, "lint", "--json")
    assert local.returncode == 0, local.stderr
    local_source = json.loads(local.stdout)["schema"]["source"]
    assert Path(local_source.removeprefix("config:")).resolve() == (project / ".env").resolve()

    named = _run_at(home, tmp_path, "lint", "@owner", "--json")
    assert named.returncode == 0, named.stderr
    named_source = json.loads(named.stdout)["schema"]["source"]
    assert Path(named_source.removeprefix("config:")).resolve() == (config_dir / "config.owner").resolve()


def test_correction_contract_requires_temporal_authority_and_immutable_hash_check(tmp_path: Path) -> None:
    skill = (Path(__file__).parents[1] / ".skills" / "wiki-capture" / "SKILL.md").read_text()
    for field in (
        "authority_class:",
        "verification_state:",
        "asserted_at:",
        "effective_at:",
        "as_of:",
        "consumer_propagation:",
        "source_pre_sha256",
        "source_post_sha256",
    ):
        assert field in skill

    source = tmp_path / "immutable.jsonl"
    source.write_text('{"role":"user","content":"tool result"}\n', encoding="utf-8")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    correction = {
        "source_text_sha256": before,
        "speaker_type": "tool_result",
        "authority_class": "runtime",
        "verification_state": "verified",
        "asserted_at": "2026-08-05T10:00:00+09:00",
        "effective_at": "2026-08-05T10:00:00+09:00",
        "as_of": "2026-08-05T11:00:00+09:00",
        "consumer_propagation": {"ob": "complete", "kw": "open"},
    }
    assert correction["speaker_type"] != "user"
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert before == after == correction["source_text_sha256"]


# ---------------------------------------------------------------------------
# Lifecycle transition validation (state machine enforcement)
# ---------------------------------------------------------------------------

def _vault_with_ledger(tmp_path: Path, lifecycle: str = "reviewed") -> Path:
    """A clean two-page vault whose ledger records *lifecycle* for alpha."""
    vault = tmp_path / "vault"
    _page(vault, "index.md", links=["alpha"])
    _page(vault, "concepts/alpha.md", links=["beta"])
    _page(vault, "concepts/beta.md", links=["alpha"])
    if lifecycle != "reviewed":
        _set_lifecycle(vault / "concepts" / "alpha.md", lifecycle)
    ledger = build_trust_ledger(vault, reviewed_at="2026-07-12T17:38:39+07:00")
    write_trust_ledger(vault / "_meta" / "trust-ledger.json", ledger, vault=vault)
    return vault


def _set_lifecycle(page: Path, lifecycle: str) -> None:
    text = page.read_text(encoding="utf-8")
    for existing in ("draft", "reviewed", "verified", "disputed", "archived"):
        if f"lifecycle: {existing}" in text:
            page.write_text(
                text.replace(f"lifecycle: {existing}", f"lifecycle: {lifecycle}"),
                encoding="utf-8",
            )
            return
    raise AssertionError("page has no lifecycle field")


def test_ledger_records_lifecycle(tmp_path: Path) -> None:
    vault = _vault_with_ledger(tmp_path)
    ledger = json.loads(
        (vault / "_meta" / "trust-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["pages"]["concepts/alpha.md"]["lifecycle"] == "reviewed"


def test_demotion_to_draft_is_flagged(tmp_path: Path) -> None:
    vault = _vault_with_ledger(tmp_path, lifecycle="verified")
    _set_lifecycle(vault / "concepts" / "alpha.md", "draft")

    report = lint_vault(vault)

    findings = report["findings"]["illegal_lifecycle_transitions"]
    assert findings == [{"page": "concepts/alpha.md", "from": "verified", "to": "draft"}]
    assert report["status"] == "warn"


def test_exit_from_archived_is_flagged(tmp_path: Path) -> None:
    vault = _vault_with_ledger(tmp_path, lifecycle="archived")
    _set_lifecycle(vault / "concepts" / "alpha.md", "reviewed")

    report = lint_vault(vault)

    assert report["findings"]["illegal_lifecycle_transitions"] == [
        {"page": "concepts/alpha.md", "from": "archived", "to": "reviewed"}
    ]


def test_draft_to_verified_is_not_flagged(tmp_path: Path) -> None:
    """Sparse ledger snapshots may hide a legitimate intermediate `reviewed`."""
    vault = _vault_with_ledger(tmp_path, lifecycle="draft")
    _set_lifecycle(vault / "concepts" / "alpha.md", "verified")

    report = lint_vault(vault)

    assert report["findings"]["illegal_lifecycle_transitions"] == []


def test_illegal_transition_fails_under_strict_trust(tmp_path: Path) -> None:
    vault = _vault_with_ledger(tmp_path, lifecycle="verified")
    _set_lifecycle(vault / "concepts" / "alpha.md", "draft")

    assert lint_vault(vault, strict_trust=True)["status"] == "fail"


def test_legacy_ledger_without_lifecycle_is_skipped(tmp_path: Path) -> None:
    """Old ledgers carry no baseline — the check stays silent, not noisy."""
    vault = _vault_with_ledger(tmp_path, lifecycle="verified")
    ledger_path = vault / "_meta" / "trust-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for entry in ledger["pages"].values():
        entry.pop("lifecycle", None)
    ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    _set_lifecycle(vault / "concepts" / "alpha.md", "draft")

    report = lint_vault(vault)

    assert report["findings"]["illegal_lifecycle_transitions"] == []


def test_no_ledger_means_no_transition_findings(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "index.md", links=["alpha"])
    _page(vault, "concepts/alpha.md", links=["index"])

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["illegal_lifecycle_transitions"] == []


def test_lint_vault_warns_on_pages_sharing_a_stem(tmp_path: Path) -> None:
    """`graph_analysis` keys a page by its bare stem, so these two are one node.

    Nothing in the vault references the stem: the collision is the defect, not
    the reference to it.
    """
    vault = tmp_path / "vault"
    _page(vault, "concepts/mercury.md", title="Mercury the concept", links=["alpha"])
    _page(vault, "entities/mercury.md", title="Mercury the planet", links=["beta"])
    _page(vault, "concepts/alpha.md", title="Alpha")
    _page(vault, "concepts/beta.md", title="Beta")

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["status"] == "warn"
    assert report["findings"]["duplicate_stems"] == [
        {"stem": "mercury", "pages": ["concepts/mercury.md", "entities/mercury.md"]}
    ]


def test_duplicate_stems_ignores_how_the_link_was_written(tmp_path: Path) -> None:
    """Both documented link formats carry a folder; neither creates a collision."""
    vault = tmp_path / "vault"
    _page(vault, "concepts/vector-search.md", title="Vector Search")
    _page(
        vault,
        "projects/renewal.md",
        title="Renewal",
        links=["concepts/vector-search|Vector Search"],
    )
    _page(vault, "projects/rollout.md", title="Rollout")
    (vault / "projects/rollout.md").write_text(
        (vault / "projects/rollout.md").read_text(encoding="utf-8")
        + "\n[Vector Search](../concepts/vector-search.md)\n",
        encoding="utf-8",
    )

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["duplicate_stems"] == []
    assert report["status"] == "pass"


def test_duplicate_stems_follows_the_graph_page_selection(tmp_path: Path) -> None:
    """Root `index.md` is not a graph page; `_bootstrap/` is."""
    vault = tmp_path / "vault"
    _page(vault, "index.md", title="Index")
    _page(vault, "concepts/index.md", title="Concepts index")
    _page(vault, "_bootstrap/vector-search.md", title="Bootstrap copy")
    _page(vault, "concepts/vector-search.md", title="Vector Search")

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["duplicate_stems"] == [
        {
            "stem": "vector-search",
            "pages": ["_bootstrap/vector-search.md", "concepts/vector-search.md"],
        }
    ]


def test_duplicate_stems_rows_and_pages_are_sorted(tmp_path: Path) -> None:
    """Neither ordering follows the page walk: `concepts/` precedes `concepts-x/`
    by path but not by string, and `zebra` is walked before `dup`."""
    vault = tmp_path / "vault"
    _page(vault, "a-dir/zebra.md", title="Zebra one")
    _page(vault, "b-dir/zebra.md", title="Zebra two")
    _page(vault, "concepts/dup.md", title="Dup one")
    _page(vault, "concepts-x/dup.md", title="Dup two")

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["duplicate_stems"] == [
        {"stem": "dup", "pages": ["concepts-x/dup.md", "concepts/dup.md"]},
        {"stem": "zebra", "pages": ["a-dir/zebra.md", "b-dir/zebra.md"]},
    ]


def test_duplicate_stems_slugs_the_filename(tmp_path: Path) -> None:
    """`Vector Search.md` and `vector-search.md` are the same node; a raw
    `Path.stem` would not see it."""
    vault = tmp_path / "vault"
    _page(vault, "concepts/Vector Search.md", title="Vector Search")
    _page(vault, "entities/vector-search.md", title="The Pinecone product")

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["duplicate_stems"] == [
        {
            "stem": "vector-search",
            "pages": ["concepts/Vector Search.md", "entities/vector-search.md"],
        }
    ]


def test_duplicate_stems_reports_a_collision_inside_one_folder(tmp_path: Path) -> None:
    """A hand-named page beside a tool-written one: same folder, same node."""
    vault = tmp_path / "vault"
    _page(vault, "concepts/Vector Search.md", title="Vector Search")
    _page(vault, "concepts/vector-search.md", title="Vector search notes")

    report = lint_vault(vault, require_trust_ledger=False)

    assert report["findings"]["duplicate_stems"] == [
        {
            "stem": "vector-search",
            "pages": ["concepts/Vector Search.md", "concepts/vector-search.md"],
        }
    ]
