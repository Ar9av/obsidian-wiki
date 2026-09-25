from __future__ import annotations

from pathlib import Path

from obsidian_wiki.provenance import invert_pages, unwrap_snapshot_value


def test_invert_unions_pages_produced_and_pages_created() -> None:
    sources = {
        "_raw/_archived/a.md": {
            "pages_produced": ["concepts/foo.md"],
            "pages_created": ["concepts/bar.md"],
        },
        "_raw/_archived/b.md": {"pages_produced": ["concepts/foo.md"]},
    }
    idx = invert_pages(sources)
    assert set(idx["concepts/foo.md"]) == {
        "_raw/_archived/a.md",
        "_raw/_archived/b.md",
    }
    assert idx["concepts/bar.md"] == ["_raw/_archived/a.md"]


def test_invert_list_shaped_manifest() -> None:
    sources = [
        {
            "path": "_raw/_archived/a.md",
            "pages_produced": ["concepts/foo.md"],
        }
    ]
    idx = invert_pages(sources)
    assert idx["concepts/foo.md"] == ["_raw/_archived/a.md"]


def test_unwrap_wikilink_and_quotes() -> None:
    assert unwrap_snapshot_value("[[_raw/_archived/Old English]]") == (
        "_raw/_archived/Old English.md"
    )
    assert unwrap_snapshot_value('"_raw/_archived/a.md"') == "_raw/_archived/a.md"
