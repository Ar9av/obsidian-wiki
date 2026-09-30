from __future__ import annotations

from pathlib import Path

from obsidian_wiki.provenance import (
    archive_wikilink_relpath,
    expected_snapshots_for_page,
    invert_pages,
    parse_snapshots_field,
    prefer_archive_write_path,
    resolve_source_key,
    unwrap_snapshot_value,
)


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
    assert unwrap_snapshot_value(
        '"[a](_raw/_archived/a.md)"'
    ) == "_raw/_archived/a.md"
    assert unwrap_snapshot_value(
        "[clip](_raw/_archived/topic/clip.md)"
    ) == "_raw/_archived/topic/clip.md"
    assert unwrap_snapshot_value(
        "[[_raw/_archived/foo|foo]]"
    ) == "_raw/_archived/foo.md"
    assert unwrap_snapshot_value("_raw/_archived/foo|foo") == (
        "_raw/_archived/foo.md"
    )


def test_resolve_stale_raw_to_archived(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    archived = vault / "_raw" / "_archived" / "notes.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("# notes\n", encoding="utf-8")
    assert resolve_source_key(vault, "_raw/notes.md") == "_raw/_archived/notes.md"


def test_resolve_url_unique_clip(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    clip = vault / "_raw" / "_archived" / "clip.md"
    clip.parent.mkdir(parents=True)
    clip.write_text("---\nurl: https://example.com/x\n---\n", encoding="utf-8")
    assert resolve_source_key(vault, "url:https://example.com/x") == (
        "_raw/_archived/clip.md"
    )


def test_resolve_url_ambiguous_returns_none(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    arch = vault / "_raw" / "_archived"
    arch.mkdir(parents=True)
    (arch / "a.md").write_text("---\nurl: https://dup.example/\n---\n", encoding="utf-8")
    (arch / "b.md").write_text("---\nurl: https://dup.example/\n---\n", encoding="utf-8")
    assert resolve_source_key(vault, "url:https://dup.example/") is None


def test_resolve_agent_key_is_none(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    assert resolve_source_key(vault, "agent:claude/abc") is None


def test_expected_snapshots_skips_unresolvable_keys(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "_raw" / "_archived").mkdir(parents=True)
    (vault / "_raw" / "_archived" / "a.md").write_text("x\n", encoding="utf-8")
    sources = {
        "_raw/_archived/a.md": {"pages_produced": ["concepts/foo.md"]},
        "url:https://no-clip.example/": {"pages_produced": ["concepts/foo.md"]},
        "agent:claude/abc": {"pages_produced": ["concepts/foo.md"]},
    }
    assert expected_snapshots_for_page(vault, "concepts/foo.md", sources) == [
        "_raw/_archived/a.md"
    ]


def test_parse_snapshots_block_list() -> None:
    raw = (
        "\n  - [[_raw/_archived/a.md]]\n"
        "  - _raw/_archived/b.md\n"
        '  - "[c](_raw/_archived/c.md)"\n'
    )
    assert parse_snapshots_field(raw) == [
        "_raw/_archived/a.md",
        "_raw/_archived/b.md",
        "_raw/_archived/c.md",
    ]


def test_invert_ten_thousand_keys() -> None:
    sources = {
        f"_raw/_archived/doc-{i}.md": {
            "pages_produced": [f"concepts/p{i % 50}.md"]
        }
        for i in range(10_000)
    }
    idx = invert_pages(sources)
    assert len(idx) == 50
    assert len(idx["concepts/p0.md"]) == 200


def test_prefer_keeps_nested_archived_when_flat_namesake_exists(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    nested = vault / "_raw" / "_archived" / "topic" / "clip.md"
    flat = vault / "_raw" / "_archived" / "clip.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("nested\n", encoding="utf-8")
    flat.write_text("flat\n", encoding="utf-8")
    assert prefer_archive_write_path(vault, "_raw/_archived/topic/clip.md") == (
        "_raw/_archived/topic/clip.md"
    )


def test_prefer_stale_raw_uses_flat_archived_basename(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    archived = vault / "_raw" / "_archived" / "notes.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("x\n", encoding="utf-8")
    assert prefer_archive_write_path(vault, "_raw/notes.md") == "_raw/_archived/notes.md"


def test_prefer_live_draft_over_same_named_archive(tmp_path: Path) -> None:
    # A new _raw/notes.md next to an old archived notes.md is a new draft.
    vault = tmp_path / "vault"
    archived = vault / "_raw" / "_archived" / "notes.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("x\n", encoding="utf-8")
    (vault / "_raw" / "notes.md").write_text("staging\n", encoding="utf-8")
    assert prefer_archive_write_path(vault, "_raw/notes.md") == "_raw/notes.md"


def test_archive_basename_only_matches_raw_keys(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    archived = vault / "_raw" / "_archived" / "README.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("x\n", encoding="utf-8")
    (vault / "docs").mkdir()
    (vault / "docs" / "README.md").write_text("doc\n", encoding="utf-8")
    assert prefer_archive_write_path(vault, "docs/README.md") == "docs/README.md"
    assert resolve_source_key(vault, "docs/README.md") is None
    assert resolve_source_key(vault, "projects/x/README.md") is None


def test_prefer_missing_returns_none(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    assert prefer_archive_write_path(vault, "_raw/_archived/ghost.md") is None


def test_archive_wikilink_relpath_existing_and_missing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    clip = vault / "_raw" / "_archived" / "foo.md"
    clip.parent.mkdir(parents=True)
    clip.write_text("x\n", encoding="utf-8")
    assert archive_wikilink_relpath(vault, "_raw/_archived/foo") == (
        "_raw/_archived/foo.md"
    )
    assert archive_wikilink_relpath(vault, "_raw/_archived/foo.md") == (
        "_raw/_archived/foo.md"
    )
    assert archive_wikilink_relpath(vault, "concepts/foo") is None
    missing = archive_wikilink_relpath(vault, "_raw/_archived/missing")
    assert missing == "_raw/_archived/missing.md"


def test_prefer_live_staging_without_archive_returns_staging(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    staging = vault / "_raw" / "notes.md"
    staging.parent.mkdir(parents=True)
    staging.write_text("staging\n", encoding="utf-8")
    assert prefer_archive_write_path(vault, "_raw/notes.md") == "_raw/notes.md"


def test_prefer_archive_write_path_rejects_traversal_and_absolute(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n", encoding="utf-8")
    assert prefer_archive_write_path(vault, "../outside.md") is None
    assert prefer_archive_write_path(vault, outside.as_posix()) is None


def test_archive_wikilink_relpath_rejects_parent_traversal(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    assert archive_wikilink_relpath(vault, "_raw/_archived/../attention") is None
