"""Tests for vault linting."""

from __future__ import annotations

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
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
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
