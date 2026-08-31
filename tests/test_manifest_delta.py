from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import manifest  # noqa: E402


class ManifestRelativePathMatchingTest(unittest.TestCase):
    def test_windows_path_matches_posix_manifest_key(self) -> None:
        entry = {"ingested_at": "2026-08-31T00:00:00Z"}
        index = manifest._relative_key_index(
            {"projects/demo/session.jsonl": entry}
        )

        matched = manifest._match_relative(
            r"C:\Users\米格\projects\demo\session.jsonl", index
        )

        self.assertIs(matched, entry)

    def test_posix_path_matches_windows_manifest_key(self) -> None:
        entry = {"ingested_at": "2026-08-31T00:00:00Z"}
        index = manifest._relative_key_index(
            {r"projects\demo\session.jsonl": entry}
        )

        matched = manifest._match_relative(
            "/home/user/projects/demo/session.jsonl", index
        )

        self.assertIs(matched, entry)


class ManifestDeltaRelativeKeyTest(unittest.TestCase):
    """cmd_delta must recognize sources stored under relative keys.

    Real vaults key many sources relative to the ingest root (e.g.
    "-Users-x-github/abc.jsonl" under ~/.claude/projects/). canonical()
    resolves those against the CWD, so before the fix every already-ingested
    file with a relative key was misreported as NEW.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.vault = root / "vault"
        self.vault.mkdir()
        # A scanned source living under an ingest root, tracked relatively.
        self.projects = root / "projects"
        self.source = self.projects / "-Users-yician-github" / "abc123.jsonl"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("{}\n")
        self.scan = str(self.projects / "**" / "*.jsonl")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_manifest(self, sources: dict) -> None:
        m = {"version": 1, "sources": sources, "projects": {}, "stats": {}}
        (self.vault / ".manifest.json").write_text(json.dumps(m, indent=2))

    def _delta(self) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = manifest.main(["delta", str(self.vault), "--scan", self.scan])
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def test_relative_key_older_ingest_is_modified_not_new(self) -> None:
        # File mtime = now, ingested long ago -> modified via suffix match.
        self._write_manifest(
            {"-Users-yician-github/abc123.jsonl": {"ingested_at": "2020-01-01T00:00:00Z"}}
        )
        out = self._delta()
        self.assertIn("# 0 new, 1 modified, 1 known", out)
        self.assertNotIn("NEW\t", out)
        self.assertIn("MOD\t", out)

    def test_relative_key_recent_ingest_is_unchanged(self) -> None:
        # File mtime older than the ingest timestamp -> neither new nor modified.
        old = 946684800  # 2000-01-01
        os.utime(self.source, (old, old))
        self._write_manifest(
            {"-Users-yician-github/abc123.jsonl": {"ingested_at": "2020-01-01T00:00:00Z"}}
        )
        out = self._delta()
        self.assertIn("# 0 new, 0 modified, 1 known", out)
        self.assertNotIn("NEW\t", out)
        self.assertNotIn("MOD\t", out)

    def test_absolute_key_still_matches(self) -> None:
        # Absolute keys must keep working exactly as before.
        old = 946684800
        os.utime(self.source, (old, old))
        self._write_manifest(
            {str(self.source): {"ingested_at": "2020-01-01T00:00:00Z"}}
        )
        out = self._delta()
        self.assertIn("# 0 new, 0 modified, 1 known", out)
        self.assertNotIn("NEW\t", out)

    def test_unknown_file_is_new(self) -> None:
        # A scanned file matched by neither an absolute nor a relative key.
        self._write_manifest(
            {"-Users-yician-github/other.jsonl": {"ingested_at": "2020-01-01T00:00:00Z"}}
        )
        out = self._delta()
        self.assertIn("# 1 new, 0 modified, 1 known", out)
        self.assertIn("NEW\t", out)


class ManifestNormalizeRelativeKeyTest(unittest.TestCase):
    """cmd_normalize must not corrupt relative source keys.

    canonical() resolves a relative key against the CWD, so canonicalizing one
    would rewrite it to a bogus absolute path and persist the damage. normalize
    only dedups/canonicalizes absolute keys; relative keys must survive as-is.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.vault.mkdir()
        self.manifest = self.vault / ".manifest.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_manifest(self, sources: dict) -> None:
        m = {"version": 1, "sources": sources, "projects": {}, "stats": {}}
        self.manifest.write_text(json.dumps(m, indent=2))

    def _keys_after_normalize(self, cwd: str) -> list:
        prev = os.getcwd()
        os.chdir(cwd)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = manifest.main(["normalize", str(self.vault)])
            self.assertEqual(rc, 0)
        finally:
            os.chdir(prev)
        return list(json.loads(self.manifest.read_text())["sources"].keys())

    def test_relative_key_preserved_regardless_of_cwd(self) -> None:
        relkey = "-Users-yician-github/abc.jsonl"
        self._write_manifest({relkey: {"ingested_at": "2020-01-01T00:00:00Z"}})
        # Run from an unrelated CWD; the relative key must not be abspath-rewritten.
        keys = self._keys_after_normalize(self.tmp.name)
        self.assertEqual(keys, [relkey])

    def test_absolute_keys_still_dedup_and_canonicalize(self) -> None:
        # Two spellings of the same absolute path must merge into one canonical key.
        abs_dir = str(Path(self.tmp.name) / "sessions")
        os.makedirs(abs_dir)
        canon = os.path.join(abs_dir, "x.jsonl")
        messy = os.path.join(abs_dir, "sub", "..", "x.jsonl")
        self._write_manifest(
            {
                canon: {"ingested_at": "2020-01-01T00:00:00Z"},
                messy: {"ingested_at": "2021-01-01T00:00:00Z"},
            }
        )
        keys = self._keys_after_normalize(self.tmp.name)
        self.assertEqual(keys, [canon])


if __name__ == "__main__":
    unittest.main()
