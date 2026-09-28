from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from obsidian_wiki.provenance import parse_snapshots_field
from obsidian_wiki.snapshots import (
    format_snapshots_block,
    read_snapshots,
    rewrite_page_snapshots,
    union_snapshot_paths,
)
from obsidian_wiki.trust import build_trust_ledger, write_trust_ledger
from obsidian_wiki.vault import split_frontmatter


def test_format_snapshots_block_is_wikilink_list_without_md() -> None:
    block = format_snapshots_block(["_raw/_archived/foo.md", "_raw/_archived/bar.md"])
    assert block.splitlines()[0] == "snapshots:"
    assert "  - [[_raw/_archived/foo]]" in block
    assert ".md]]" not in block
    assert parse_snapshots_field("\n" + "\n".join(block.splitlines()[1:])) == [
        "_raw/_archived/foo.md",
        "_raw/_archived/bar.md",
    ]


def test_rewrite_inserts_and_preserves_sources(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "---\ntitle: T\nsources: [manual]\n---\n# T\nbody\n",
        encoding="utf-8",
    )
    rewrite_page_snapshots(page, ["_raw/_archived/a.md"])
    text = page.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    assert "sources: [manual]" in fm
    assert "snapshots:" in fm
    assert "  - [[_raw/_archived/a]]" in fm
    assert body.strip().startswith("# T")


def test_union_snapshot_paths_keeps_prior() -> None:
    assert union_snapshot_paths(
        ["_raw/_archived/old.md"],
        ["_raw/_archived/new.md"],
    ) == ["_raw/_archived/old.md", "_raw/_archived/new.md"]


def test_read_snapshots_round_trips_block_list(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "---\ntitle: T\nsources: [manual]\nsnapshots:\n"
        "  - [[_raw/_archived/a]]\n---\n# T\n",
        encoding="utf-8",
    )
    assert read_snapshots(page) == ["_raw/_archived/a.md"]


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    home.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True, check=False, text=True, env=env, cwd=home,
    )


def _home_vault(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir(parents=True)
    (config_dir / "config").write_text(f'OBSIDIAN_VAULT_PATH="{vault}"\n', encoding="utf-8")
    return home, vault


def test_snapshots_set_unions_and_rejects_missing(tmp_path: Path) -> None:
    home, vault = _home_vault(tmp_path)
    (vault / "_raw" / "_archived").mkdir(parents=True)
    (vault / "_raw" / "_archived" / "a.md").write_text("a\n", encoding="utf-8")
    (vault / "_raw" / "_archived" / "b.md").write_text("b\n", encoding="utf-8")
    page = vault / "concepts" / "alpha.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ntitle: alpha\nsources: [manual]\n---\n# alpha\n", encoding="utf-8")
    proc = _run(
        home, "snapshots", "set", "concepts/alpha.md", "--archive", "_raw/_archived/a.md",
    )
    assert proc.returncode == 0
    proc2 = _run(
        home, "snapshots", "set", "concepts/alpha.md", "--archive", "_raw/_archived/b.md",
    )
    assert proc2.returncode == 0
    text = page.read_text(encoding="utf-8")
    assert "[[_raw/_archived/a]]" in text
    assert "[[_raw/_archived/b]]" in text
    assert "sources: [manual]" in text
    bad = _run(
        home, "snapshots", "set", "concepts/alpha.md", "--archive", "_raw/_archived/nope.md",
    )
    assert bad.returncode != 0
    assert page.read_text(encoding="utf-8") == text


def test_snapshots_set_rejects_staging_path_without_archive(tmp_path: Path) -> None:
    home, vault = _home_vault(tmp_path)
    staging = vault / "_raw" / "notes.md"
    staging.parent.mkdir(parents=True)
    staging.write_text("staging\n", encoding="utf-8")
    page = vault / "concepts" / "alpha.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ntitle: alpha\nsources: [manual]\n---\n# alpha\n", encoding="utf-8")
    before = page.read_text(encoding="utf-8")
    proc = _run(
        home, "snapshots", "set", "concepts/alpha.md", "--archive", "_raw/notes.md",
    )
    assert proc.returncode != 0
    assert page.read_text(encoding="utf-8") == before
    assert "snapshots:" not in before


def test_snapshots_set_rejects_page_paths_that_escape_vault(tmp_path: Path) -> None:
    home, vault = _home_vault(tmp_path)
    (vault / "_raw" / "_archived").mkdir(parents=True)
    (vault / "_raw" / "_archived" / "a.md").write_text("a\n", encoding="utf-8")
    page = vault / "concepts" / "alpha.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ntitle: alpha\nsources: [manual]\n---\n# alpha\n", encoding="utf-8")
    before = page.read_text(encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("---\ntitle: outside\nsources: [manual]\n---\n# outside\n", encoding="utf-8")
    outside_before = outside.read_text(encoding="utf-8")
    via_dotdot = _run(
        home, "snapshots", "set", "../outside.md", "--archive", "_raw/_archived/a.md",
    )
    assert via_dotdot.returncode != 0
    assert page.read_text(encoding="utf-8") == before
    assert outside.read_text(encoding="utf-8") == outside_before
    via_abs = _run(
        home, "snapshots", "set", str(page), "--archive", "_raw/_archived/a.md",
    )
    assert via_abs.returncode != 0
    assert page.read_text(encoding="utf-8") == before


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
    snapshots: str | None = None,
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
        if snapshots is not None:
            lines.append(f"snapshots: {snapshots}")
        lines.append("---")
    lines.append(f"# {title or path.stem}")
    for link in links or []:
        lines.append(f"[[{link}]]")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _clean_pair(vault: Path, *, alpha_snapshots: str | None = None) -> None:
    """Write a two-page graph and trust ledger from the **final** page bytes.

    Never rewrite a page after `write_trust_ledger`: that marks reviewed
    pages stale (`confidence_review_stale`) and pollutes `status`.
    """
    _page(
        vault,
        "concepts/alpha.md",
        links=["beta"],
        snapshots=alpha_snapshots,
    )
    _page(vault, "concepts/beta.md", links=["alpha"])
    ledger = build_trust_ledger(vault, reviewed_at="2026-07-12T17:38:39+07:00")
    write_trust_ledger(vault / "_meta" / "trust-ledger.json", ledger, vault=vault)


def _write_archive_and_manifest(vault: Path, page: str = "concepts/alpha.md") -> None:
    archived = vault / "_raw" / "_archived" / "a.md"
    archived.parent.mkdir(parents=True, exist_ok=True)
    archived.write_text("# clip\n", encoding="utf-8")
    (vault / ".manifest.json").write_text(
        json.dumps(
            {
                "sources": {
                    "_raw/_archived/a.md": {"pages_produced": [page]},
                }
            }
        ),
        encoding="utf-8",
    )


def test_snapshots_apply_dry_run_then_apply_replaces(tmp_path: Path) -> None:
    home, vault = _home_vault(tmp_path)
    _clean_pair(vault, alpha_snapshots="[_raw/_archived/extra.md]")
    _write_archive_and_manifest(vault)
    json_path = tmp_path / "lint.json"
    proc = _run(home, "lint", "--json")
    assert proc.returncode == 0
    json_path.write_text(proc.stdout, encoding="utf-8")
    report = json.loads(proc.stdout)
    assert report["findings"]["snapshot_mismatch"]
    before = (vault / "concepts" / "alpha.md").read_text(encoding="utf-8")
    preview = _run(home, "snapshots", "apply", "--from-json", str(json_path))
    assert preview.returncode == 0
    assert "concepts/alpha.md" in preview.stdout
    assert "[[_raw/_archived/a]]" in preview.stdout
    assert (vault / "concepts" / "alpha.md").read_text(encoding="utf-8") == before
    written = _run(home, "snapshots", "apply", "--from-json", str(json_path), "--apply")
    assert written.returncode == 0
    text = (vault / "concepts" / "alpha.md").read_text(encoding="utf-8")
    assert "[[_raw/_archived/a]]" in text
    assert "[[_raw/_archived/extra]]" not in text
    assert "sources: [manual]" in text


def test_snapshots_apply_bad_json_writes_nothing(tmp_path: Path) -> None:
    home, vault = _home_vault(tmp_path)
    _clean_pair(vault)
    _write_archive_and_manifest(vault)
    before = (vault / "concepts" / "alpha.md").read_text(encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    proc = _run(home, "snapshots", "apply", "--from-json", str(bad))
    assert proc.returncode != 0
    assert (vault / "concepts" / "alpha.md").read_text(encoding="utf-8") == before


def test_snapshots_apply_missing_page_writes_nothing(tmp_path: Path) -> None:
    home, vault = _home_vault(tmp_path)
    _clean_pair(vault)
    _write_archive_and_manifest(vault)
    before = (vault / "concepts" / "alpha.md").read_text(encoding="utf-8")
    payload = {
        "findings": {
            "snapshot_mismatch": [
                {"page": "concepts/alpha.md", "expected": ["_raw/_archived/a.md"]},
                {"page": "concepts/missing.md", "expected": ["_raw/_archived/a.md"]},
            ]
        }
    }
    json_path = tmp_path / "lint.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    proc = _run(home, "snapshots", "apply", "--from-json", str(json_path), "--apply")
    assert proc.returncode != 0
    assert (vault / "concepts" / "alpha.md").read_text(encoding="utf-8") == before


def test_snapshots_apply_empty_expected_skips_row(tmp_path: Path) -> None:
    home, vault = _home_vault(tmp_path)
    _clean_pair(vault, alpha_snapshots="\n  - [[_raw/_archived/keep]]")
    archived = vault / "_raw" / "_archived" / "keep.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("k\n", encoding="utf-8")
    before = (vault / "concepts" / "alpha.md").read_text(encoding="utf-8")
    payload = {
        "findings": {
            "snapshot_mismatch": [
                {"page": "concepts/alpha.md", "expected": []},
            ]
        }
    }
    json_path = tmp_path / "lint.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    proc = _run(home, "snapshots", "apply", "--from-json", str(json_path), "--apply")
    assert proc.returncode == 0
    assert (vault / "concepts" / "alpha.md").read_text(encoding="utf-8") == before
    assert "[[_raw/_archived/keep]]" in before
