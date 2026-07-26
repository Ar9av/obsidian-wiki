"""Regression tests for issue #134.

cache-check / cache-update were written for a dict-keyed manifest with bare hex
hashes, but the wiki-ingest skill writes ``sources`` as a list of objects with
``sha256:``-prefixed hashes and vault-relative paths. That combination caused a
crash, then false "modified"/"new" once the crash was patched. These tests pin
all four failure modes the issue enumerated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from obsidian_wiki.cache import (
    check_sources,
    compute_hash,
    update_source,
    _load_raw,
    _manifest_path,
)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    return v


@pytest.fixture
def raw_file(vault):
    f = vault / "_raw" / "foo.md"
    f.parent.mkdir(parents=True)
    f.write_text("# Foo\nbody", encoding="utf-8")
    return f


def _write_list_manifest(vault: Path, entries: list[dict]) -> None:
    _manifest_path(vault).write_text(
        json.dumps({"version": 1, "sources": entries}, indent=2), encoding="utf-8"
    )


# 1. Crash on list-shaped sources ------------------------------------------

def test_list_shaped_manifest_does_not_crash(vault, raw_file):
    _write_list_manifest(vault, [{"path": "_raw/foo.md", "content_hash": "sha256:x"}])
    result = check_sources(vault, [raw_file])  # previously: AttributeError
    assert isinstance(result, dict)


# 2. Hash prefix mismatch ---------------------------------------------------

def test_sha256_prefixed_hash_reads_as_unchanged(vault, raw_file):
    # Skill records "sha256:<hex>"; compute_hash returns bare hex.
    _write_list_manifest(
        vault, [{"path": "_raw/foo.md", "content_hash": f"sha256:{compute_hash(raw_file)}"}]
    )
    result = check_sources(vault, [raw_file])
    assert str(raw_file) in result["unchanged"]
    assert result["modified"] == []
    assert result["new"] == []


def test_prefixed_hash_still_detects_real_change(vault, raw_file):
    _write_list_manifest(
        vault, [{"path": "_raw/foo.md", "content_hash": f"sha256:{compute_hash(raw_file)}"}]
    )
    raw_file.write_text("# Foo\nchanged", encoding="utf-8")
    result = check_sources(vault, [raw_file])
    assert str(raw_file) in result["modified"]


# 3. Vault-relative path stored, absolute path queried ----------------------

def test_relative_list_path_matches_absolute_query(vault, raw_file):
    _write_list_manifest(
        vault, [{"path": "_raw/foo.md", "content_hash": f"sha256:{compute_hash(raw_file)}"}]
    )
    result = check_sources(vault, [raw_file.resolve()])
    assert str(raw_file.resolve()) in result["unchanged"]


# 4. update_source preserves shape, duplicates, and extra fields ------------

def test_update_preserves_list_shape(vault, raw_file):
    _write_list_manifest(
        vault,
        [{"path": "_raw/foo.md", "content_hash": "sha256:old", "source_type": "document",
          "pages_produced": ["concepts/foo.md"]}],
    )
    update_source(vault, raw_file, pages_produced=["concepts/foo.md", "concepts/bar.md"])
    sources = _load_raw(vault)["sources"]
    assert isinstance(sources, list), "must stay a list, not collapse to a dict"
    assert len(sources) == 1
    entry = sources[0]
    assert entry["source_type"] == "document"  # skill field preserved
    assert entry["content_hash"] == f"sha256:{compute_hash(raw_file)}"  # prefix kept
    assert entry["pages_produced"] == ["concepts/foo.md", "concepts/bar.md"]


def test_update_preserves_duplicate_path_entries(vault, raw_file):
    # Same path ingested on two occasions — a dict round-trip would collapse these.
    _write_list_manifest(
        vault,
        [
            {"path": "_raw/foo.md", "content_hash": "sha256:v1", "ingested_at": "2026-01-01"},
            {"path": "_raw/foo.md", "content_hash": "sha256:v2", "ingested_at": "2026-02-01"},
        ],
    )
    update_source(vault, raw_file)
    sources = _load_raw(vault)["sources"]
    assert len(sources) == 2, "duplicate-path entries must survive"
    # First match updated; the second occasion is left intact.
    assert sources[0]["content_hash"] == f"sha256:{compute_hash(raw_file)}"
    assert sources[1]["content_hash"] == "sha256:v2"


def test_update_appends_new_list_entry(vault, raw_file):
    _write_list_manifest(vault, [{"path": "_raw/other.md", "content_hash": "sha256:z"}])
    update_source(vault, raw_file)
    sources = _load_raw(vault)["sources"]
    assert isinstance(sources, list)
    assert {e["path"] for e in sources} == {"_raw/other.md", str(raw_file)}


def test_top_level_keys_preserved(vault, raw_file):
    _manifest_path(vault).write_text(
        json.dumps({"version": 1, "stats": {"total_sources_ingested": 5}, "sources": []}),
        encoding="utf-8",
    )
    update_source(vault, raw_file)
    manifest = _load_raw(vault)
    assert manifest["version"] == 1
    assert manifest["stats"]["total_sources_ingested"] == 5


# Non-file keys (URLs / pseudo-paths) must not be flagged missing -----------

def test_url_source_key_not_flagged_missing(vault):
    _write_list_manifest(
        vault,
        [{"path": "https://example.com/x", "content_hash": "sha256:x", "source_type": "repository"}],
    )
    result = check_sources(vault, [])
    assert result["missing"] == []
