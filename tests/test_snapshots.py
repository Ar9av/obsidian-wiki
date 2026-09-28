from __future__ import annotations

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
