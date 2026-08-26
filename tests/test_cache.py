"""Tests for the content-hash cache module."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from obsidian_wiki.cache import (
    ManifestLockTimeout,
    check_sources,
    compute_hash,
    hash_file,
    manifest_lock,
    sha256_file,
    sha256_dir,
    update_source,
    _load_manifest,
    _lock_path,
    _manifest_path,
    _write_manifest,
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

    def test_sha256_dir_independent_of_path_separator(self, src_dir):
        """Hash must match hashlib computed with POSIX separators regardless of platform (#178)."""
        import hashlib

        (src_dir / "sub").mkdir()
        (src_dir / "sub" / "c.py").write_text("z = 3")

        h = hashlib.sha256()
        for fp in sorted(src_dir.rglob("*"), key=lambda p: p.relative_to(src_dir).as_posix()):
            if fp.is_file():
                h.update(fp.relative_to(src_dir).as_posix().encode())
                h.update(sha256_file(fp).encode())
        assert sha256_dir(src_dir) == h.hexdigest()

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


class TestManifestLock:
    """Concurrent writers must serialize instead of clobbering the manifest."""

    def test_lock_is_released_after_use(self, vault):
        with manifest_lock(vault):
            assert _lock_path(vault).exists()
        assert not _lock_path(vault).exists()

    def test_second_holder_times_out(self, vault):
        with manifest_lock(vault):
            with pytest.raises(ManifestLockTimeout):
                with manifest_lock(vault, timeout=0.3):
                    pass

    def test_stale_lock_is_stolen(self, vault):
        lock = _lock_path(vault)
        lock.write_text("999999")
        old = time.time() - 120
        os.utime(lock, (old, old))
        with manifest_lock(vault, timeout=0.5, stale_after=60.0):
            pass
        assert not lock.exists()

    def test_lock_released_when_body_raises(self, vault):
        with pytest.raises(ValueError):
            with manifest_lock(vault):
                raise ValueError("boom")
        assert not _lock_path(vault).exists()

    def test_update_source_leaves_no_lock_behind(self, vault, src_file):
        update_source(vault, src_file)
        assert not _lock_path(vault).exists()

    def test_concurrent_updates_both_survive(self, vault, tmp_path):
        """The race the lock exists for: two processes, neither entry lost."""
        a = tmp_path / "a.md"
        a.write_text("alpha", encoding="utf-8")
        b = tmp_path / "b.md"
        b.write_text("beta", encoding="utf-8")
        code = (
            "import sys;from pathlib import Path;"
            "from obsidian_wiki.cache import update_source;"
            "update_source(Path(sys.argv[1]), Path(sys.argv[2]))"
        )
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
        procs = [
            subprocess.Popen([sys.executable, "-c", code, str(vault), str(src)], env=env)
            for src in (a, b)
        ]
        for p in procs:
            assert p.wait(timeout=30) == 0
        sources = _load_manifest(vault)
        assert str(a) in sources and str(b) in sources


class TestAtomicWrite:
    def test_failed_write_leaves_original_intact(self, vault, monkeypatch):
        _write_manifest(vault, {"sources": {"kept": {"content_hash": "abc"}}})

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("obsidian_wiki.cache.os.replace", boom)
        with pytest.raises(OSError):
            _write_manifest(vault, {"sources": {"lost": {}}})

        assert _load_manifest(vault) == {"kept": {"content_hash": "abc"}}
        leftovers = list(vault.glob(".manifest.json.*.tmp"))
        assert leftovers == []

    def test_manifest_is_never_partially_written(self, vault, src_file):
        update_source(vault, src_file)
        # A complete, parseable JSON document — never a truncated prefix.
        json.loads(_manifest_path(vault).read_text(encoding="utf-8"))
