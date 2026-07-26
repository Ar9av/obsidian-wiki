"""Tests for the content-hash cache module."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from obsidian_wiki.cache import (
    check_sources,
    compute_hash,
    hash_file,
    sha256_file,
    sha256_dir,
    update_source,
    _load_manifest,
    _manifest_path,
)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    return v


@pytest.fixture
def src_file(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Hello\nSome content.", encoding="utf-8")
    return f


@pytest.fixture
def src_dir(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    (d / "a.py").write_text("x = 1")
    (d / "b.py").write_text("y = 2")
    return d


# ---------------------------------------------------------------------------
# Hash functions
# ---------------------------------------------------------------------------

class TestHashing:
    def test_sha256_file_deterministic(self, src_file):
        assert sha256_file(src_file) == sha256_file(src_file)

    def test_sha256_file_changes_on_edit(self, src_file):
        h1 = sha256_file(src_file)
        src_file.write_text("# Different content")
        h2 = sha256_file(src_file)
        assert h1 != h2

    def test_sha256_dir_deterministic(self, src_dir):
        assert sha256_dir(src_dir) == sha256_dir(src_dir)

    def test_sha256_dir_changes_on_edit(self, src_dir):
        h1 = sha256_dir(src_dir)
        (src_dir / "a.py").write_text("x = 999")
        h2 = sha256_dir(src_dir)
        assert h1 != h2

    def test_compute_hash_dispatches(self, src_file, src_dir):
        assert len(compute_hash(src_file)) == 64  # hex SHA-256
        assert len(compute_hash(src_dir)) == 64

    def test_hash_file_alias(self, src_file):
        assert hash_file(src_file) == sha256_file(src_file)


# ---------------------------------------------------------------------------
# check_sources
# ---------------------------------------------------------------------------

class TestCheckSources:
    def test_new_source(self, vault, src_file):
        result = check_sources(vault, [src_file])
        assert str(src_file) in result["new"]
        assert result["modified"] == []
        assert result["unchanged"] == []

    def test_unchanged_after_update(self, vault, src_file):
        update_source(vault, src_file)
        result = check_sources(vault, [src_file])
        assert str(src_file) in result["unchanged"]
        assert result["new"] == []
        assert result["modified"] == []

    def test_modified_after_content_change(self, vault, src_file):
        update_source(vault, src_file)
        src_file.write_text("# Changed content")
        result = check_sources(vault, [src_file])
        assert str(src_file) in result["modified"]

    def test_missing_path(self, vault, tmp_path):
        ghost = tmp_path / "ghost.md"
        result = check_sources(vault, [ghost])
        assert str(ghost) in result["missing"]

    def test_empty_source_list(self, vault):
        result = check_sources(vault, [])
        assert result == {"new": [], "modified": [], "unchanged": [], "missing": []}

    def test_multiple_sources(self, vault, src_file, src_dir):
        update_source(vault, src_file)
        result = check_sources(vault, [src_file, src_dir])
        assert str(src_file) in result["unchanged"]
        assert str(src_dir) in result["new"]

    def test_timestamp_irrelevant(self, vault, src_file):
        # Touch the file (change mtime) without changing content — still unchanged
        update_source(vault, src_file)
        src_file.touch()
        result = check_sources(vault, [src_file])
        assert str(src_file) in result["unchanged"]

    def _write_relative_manifest(self, vault, rel_key, content_hash):
        """Write a manifest whose source key is stored vault-relative."""
        _manifest_path(vault).write_text(
            json.dumps(
                {"sources": {rel_key: {"content_hash": content_hash, "last_ingested": "2026-07-14"}}}
            ),
            encoding="utf-8",
        )

    def test_relative_manifest_key_unchanged_for_abs_path(self, vault):
        # Manifest stores a vault-relative key; caller passes the absolute path.
        src = vault / "_raw" / "articles" / "foo.md"
        src.parent.mkdir(parents=True)
        src.write_text("body", encoding="utf-8")
        self._write_relative_manifest(vault, "_raw/articles/foo.md", sha256_file(src))
        result = check_sources(vault, [src])
        assert str(src) in result["unchanged"]
        assert result["new"] == []
        assert result["missing"] == []

    def test_relative_manifest_key_not_falsely_missing(self, vault):
        # A relative key whose file exists under the vault must not be flagged missing,
        # even when CWD != vault root.
        src = vault / "_raw" / "articles" / "foo.md"
        src.parent.mkdir(parents=True)
        src.write_text("body", encoding="utf-8")
        self._write_relative_manifest(vault, "_raw/articles/foo.md", sha256_file(src))
        result = check_sources(vault, [])
        assert "_raw/articles/foo.md" not in result["missing"]

    def test_relative_manifest_key_modified(self, vault):
        src = vault / "_raw" / "articles" / "foo.md"
        src.parent.mkdir(parents=True)
        src.write_text("body", encoding="utf-8")
        self._write_relative_manifest(vault, "_raw/articles/foo.md", "stale-hash")
        result = check_sources(vault, [src])
        assert str(src) in result["modified"]

    def test_relative_manifest_key_genuinely_missing(self, vault):
        # A relative key with no file on disk is still reported missing.
        self._write_relative_manifest(vault, "_raw/articles/gone.md", "abc")
        result = check_sources(vault, [])
        assert "_raw/articles/gone.md" in result["missing"]


# ---------------------------------------------------------------------------
# update_source / manifest
# ---------------------------------------------------------------------------

class TestUpdateSource:
    def test_writes_manifest(self, vault, src_file):
        update_source(vault, src_file)
        assert _manifest_path(vault).exists()

    def test_records_correct_hash(self, vault, src_file):
        h = update_source(vault, src_file)
        assert h == sha256_file(src_file)
        sources = _load_manifest(vault)
        assert sources[str(src_file)]["content_hash"] == h

    def test_records_pages_produced(self, vault, src_file):
        update_source(vault, src_file, pages_produced=["concepts/foo.md", "entities/bar.md"])
        sources = _load_manifest(vault)
        assert sources[str(src_file)]["pages_produced"] == ["concepts/foo.md", "entities/bar.md"]

    def test_records_last_ingested_timestamp(self, vault, src_file):
        update_source(vault, src_file)
        sources = _load_manifest(vault)
        assert "last_ingested" in sources[str(src_file)]

    def test_update_overwrites_old_hash(self, vault, src_file):
        update_source(vault, src_file)
        src_file.write_text("new content")
        h2 = update_source(vault, src_file)
        sources = _load_manifest(vault)
        assert sources[str(src_file)]["content_hash"] == h2

    def test_preserves_other_manifest_entries(self, vault, src_file, src_dir):
        update_source(vault, src_file)
        update_source(vault, src_dir)
        sources = _load_manifest(vault)
        assert str(src_file) in sources
        assert str(src_dir) in sources


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCacheCLI:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", *args],
            capture_output=True, text=True,
        )

    def test_cache_hash_file(self, src_file):
        proc = self._run("cache-hash", str(src_file))
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data["sha256"] == sha256_file(src_file)

    def test_cache_hash_missing_exits_nonzero(self, tmp_path):
        proc = self._run("cache-hash", str(tmp_path / "nope.md"))
        assert proc.returncode != 0

    def test_cache_check_new(self, vault, src_file):
        proc = self._run("cache-check", str(vault), str(src_file))
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert str(src_file) in data["new"]

    def test_cache_check_pretty(self, vault, src_file):
        proc = self._run("cache-check", "--pretty", str(vault), str(src_file))
        assert proc.returncode == 0
        assert "\n  " in proc.stdout

    def test_cache_update_then_check_unchanged(self, vault, src_file):
        self._run("cache-update", str(vault), str(src_file))
        proc = self._run("cache-check", str(vault), str(src_file))
        data = json.loads(proc.stdout)
        assert str(src_file) in data["unchanged"]

    def test_cache_update_with_pages(self, vault, src_file):
        proc = self._run("cache-update", str(vault), str(src_file),
                         "--pages", "concepts/foo.md", "entities/bar.md")
        assert proc.returncode == 0
        sources = _load_manifest(vault)
        assert sources[str(src_file)]["pages_produced"] == ["concepts/foo.md", "entities/bar.md"]
