from __future__ import annotations

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
