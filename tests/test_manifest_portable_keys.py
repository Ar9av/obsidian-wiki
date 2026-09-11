"""Tests for the manifest helper's portable key handling and `migrate` command.

`scripts/manifest.py` is a standalone stdlib helper, so it is imported by path
rather than as a package (same pattern as ``test_manifest_delta.py``).
"""
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
from obsidian_wiki.cache import resolve_key as cache_resolve_key  # noqa: E402
from obsidian_wiki.cache import stored_key as cache_stored_key  # noqa: E402


class ResolveAndStoreKeyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.tmp.cleanup()

    def test_resolve_vault_relative(self) -> None:
        self.assertEqual(
            manifest.resolve_key("Raw/x.pdf", str(self.vault)),
            str(self.vault / "Raw" / "x.pdf"),
        )

    def test_resolve_home_relative(self) -> None:
        self.assertEqual(
            manifest.resolve_key("~/.claude/x.jsonl", str(self.vault)),
            str(self.home / ".claude" / "x.jsonl"),
        )

    def test_resolve_absolute_unchanged(self) -> None:
        abs_path = str(self.root / "elsewhere" / "a.md")
        self.assertEqual(manifest.resolve_key(abs_path, str(self.vault)), abs_path)

    def test_resolve_pseudo_key_is_none(self) -> None:
        for key in ("repo:github.com/o/n", "url:https://x/y", "agent:claude/1", "src:abcd1234"):
            self.assertIsNone(manifest.resolve_key(key, str(self.vault)))

    def test_stored_in_vault_relative(self) -> None:
        self.assertEqual(
            manifest.stored_key(str(self.vault / "Clippings" / "a.md"), str(self.vault)),
            "Clippings/a.md",
        )

    def test_stored_under_home_relative(self) -> None:
        self.assertEqual(
            manifest.stored_key(str(self.home / ".claude" / "x.jsonl"), str(self.vault)),
            "~/.claude/x.jsonl",
        )

    def test_stored_outside_both_is_none(self) -> None:
        self.assertIsNone(manifest.stored_key(str(self.root / "other" / "a.md"), str(self.vault)))


class MigrateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        self.manifest = self.vault / ".manifest.json"

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.tmp.cleanup()

    def _write(self, sources: dict) -> None:
        self.manifest.write_text(
            json.dumps({"version": 1, "sources": sources, "projects": {}}), encoding="utf-8"
        )

    def _run(self, *argv: str) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = manifest.main(["migrate", str(self.vault), *argv])
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def _keys(self) -> list[str]:
        return list(json.loads(self.manifest.read_text())["sources"].keys())

    def test_in_vault_absolute_becomes_relative(self) -> None:
        (self.vault / "Raw").mkdir()
        src = self.vault / "Raw" / "x.pdf"
        self._write({str(src): {"ingested_at": "2026-01-01"}})
        self._run()
        self.assertEqual(self._keys(), ["Raw/x.pdf"])

    def test_home_absolute_becomes_tilde_relative(self) -> None:
        src = self.home / ".claude" / "abc.jsonl"
        self._write({str(src): {"ingested_at": "2026-01-01"}})
        self._run()
        self.assertEqual(self._keys(), ["~/.claude/abc.jsonl"])

    def test_non_portable_absolute_is_preserved(self) -> None:
        src = self.root / "mnt" / "data" / "a.md"
        self._write({str(src): {"ingested_at": "2026-01-01"}})
        out = self._run()
        self.assertEqual(self._keys(), [str(src)])
        self.assertIn("no portable form", out)

    def test_legacy_relative_key_preserved(self) -> None:
        key = "-Users-yician-github/abc.jsonl"
        self._write({key: {"ingested_at": "2026-01-01"}})
        self._run()
        self.assertEqual(self._keys(), [key])

    def test_pseudo_key_preserved(self) -> None:
        self._write({"repo:github.com/o/n": {"ingested_at": "2026-01-01"}})
        self._run()
        self.assertEqual(self._keys(), ["repo:github.com/o/n"])

    def test_collision_merges_keeping_newest(self) -> None:
        (self.vault / "Raw").mkdir()
        src = self.vault / "Raw" / "x.pdf"
        messy = str(self.vault / "Raw" / "sub" / ".." / "x.pdf")
        self._write(
            {
                str(src): {"ingested_at": "2026-01-01", "pages_produced": ["a.md"]},
                messy: {"ingested_at": "2026-02-01", "pages_produced": ["b.md"]},
            }
        )
        self._run()
        self.assertEqual(self._keys(), ["Raw/x.pdf"])
        entry = json.loads(self.manifest.read_text())["sources"]["Raw/x.pdf"]
        self.assertEqual(entry["ingested_at"], "2026-02-01")
        self.assertEqual(sorted(entry["pages_produced"]), ["a.md", "b.md"])

    def test_non_portable_unnormalized_key_is_rewritten(self) -> None:
        # A non-portable absolute key with ".." is still normalized in spelling;
        # the write gate must not skip it while claiming "already portable".
        messy = str(self.root / "mnt" / "sub" / ".." / "a.md")
        canon = str(self.root / "mnt" / "a.md")
        self._write({messy: {"ingested_at": "2020-01-01"}})
        out = self._run()
        self.assertNotIn("already portable", out)
        self.assertIn("no portable form", out)
        self.assertEqual(self._keys(), [canon])

    def test_cross_machine_keys_are_kept_and_message_is_honest(self) -> None:
        # A vault moved machines: keys are rooted at the OLD vault path, which
        # matches neither the new vault nor $HOME. Nothing can be stripped, so
        # every key stays absolute — and the summary must not claim otherwise.
        old_root = self.root / "old-machine" / "oh-my-wiki"
        (self.vault / "Clippings").mkdir()
        (self.vault / "Raw").mkdir()
        keys = [str(old_root / "Clippings" / "a.md"), str(old_root / "Raw" / "b.pdf")]
        self._write({k: {"ingested_at": "2020-01-01"} for k in keys})
        out = self._run()
        self.assertEqual(sorted(self._keys()), sorted(keys))
        self.assertNotIn("already portable", out)
        self.assertIn("2 kept non-portable", out)
        self.assertIn("nothing portable to write", out)
        # The fix is stated, not guessed: the user supplies the old root.
        self.assertIn("--from-root <old-vault-root>", out)

    def test_from_root_strips_the_old_vault_root(self) -> None:
        old_root = self.root / "old-machine" / "oh-my-wiki"
        keys = [str(old_root / "Clippings" / "a.md"), str(old_root / "Raw" / "b.pdf")]
        self._write({k: {"ingested_at": "2020-01-01"} for k in keys})
        out = self._run("--from-root", str(old_root))
        self.assertEqual(sorted(self._keys()), ["Clippings/a.md", "Raw/b.pdf"])
        self.assertIn("2 re-keyed", out)
        self.assertIn("wrote", out)
        self.assertIn("0 kept non-portable", out)

    def test_from_root_dry_run_writes_nothing(self) -> None:
        old_root = self.root / "old-machine" / "oh-my-wiki"
        key = str(old_root / "Clippings" / "a.md")
        self._write({key: {"ingested_at": "2020-01-01"}})
        self._run("--from-root", str(old_root), "--dry-run")
        self.assertEqual(self._keys(), [key])

    def test_from_root_is_repeatable(self) -> None:
        r1 = self.root / "machine-a" / "vault"
        r2 = self.root / "machine-b" / "vault"
        self._write(
            {
                str(r1 / "Raw" / "a.md"): {"ingested_at": "2020-01-01"},
                str(r2 / "Raw" / "b.md"): {"ingested_at": "2020-01-01"},
            }
        )
        self._run("--from-root", str(r1), "--from-root", str(r2))
        self.assertEqual(sorted(self._keys()), ["Raw/a.md", "Raw/b.md"])

    def test_from_root_leaves_foreign_absolute_keys(self) -> None:
        old_root = self.root / "old-machine" / "oh-my-wiki"
        foreign = self.root / "elsewhere" / "c.md"
        self._write(
            {
                str(old_root / "Raw" / "a.md"): {"ingested_at": "2020-01-01"},
                str(foreign): {"ingested_at": "2020-01-01"},
            }
        )
        out = self._run("--from-root", str(old_root))
        self.assertIn("Raw/a.md", self._keys())
        self.assertIn(str(foreign), self._keys())
        self.assertIn("1 kept non-portable", out)

    def test_normalize_alias_accepts_from_root(self) -> None:
        old_root = self.root / "old-machine" / "oh-my-wiki"
        key = str(old_root / "Raw" / "a.md")
        self._write({key: {"ingested_at": "2020-01-01"}})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = manifest.main(["normalize", str(self.vault), "--from-root", str(old_root)])
        self.assertEqual(rc, 0)
        self.assertEqual(self._keys(), ["Raw/a.md"])

    def test_dry_run_writes_nothing(self) -> None:
        (self.vault / "Raw").mkdir()
        src = self.vault / "Raw" / "x.pdf"
        self._write({str(src): {"ingested_at": "2026-01-01"}})
        self._run("--dry-run")
        self.assertEqual(self._keys(), [str(src)])

    def test_idempotent_second_run(self) -> None:
        (self.vault / "Raw").mkdir()
        src = self.vault / "Raw" / "x.pdf"
        self._write({str(src): {"ingested_at": "2026-01-01"}})
        self._run()
        out = self._run()
        self.assertIn("already portable", out)
        self.assertEqual(self._keys(), ["Raw/x.pdf"])

    def test_normalize_is_an_alias(self) -> None:
        (self.vault / "Raw").mkdir()
        src = self.vault / "Raw" / "x.pdf"
        self._write({str(src): {"ingested_at": "2026-01-01"}})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = manifest.main(["normalize", str(self.vault)])
        self.assertEqual(rc, 0)
        self.assertEqual(self._keys(), ["Raw/x.pdf"])


class DeltaResolvesPortableKeysTest(unittest.TestCase):
    """cmd_delta must match a scanned absolute path against a relative stored key."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.vault.mkdir()
        self.src = self.vault / "Raw" / "doc.md"
        self.src.parent.mkdir()
        self.src.write_text("body", encoding="utf-8")
        old = 946684800  # 2000-01-01, older than the ingest timestamp
        os.utime(self.src, (old, old))
        (self.vault / ".manifest.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "sources": {
                        "Raw/doc.md": {"ingested_at": "2020-01-01T00:00:00Z"}
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_vault_relative_key_matches_scanned_absolute(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = manifest.main(
                ["delta", str(self.vault), "--scan", str(self.vault / "**" / "*.md")]
            )
        self.assertEqual(rc, 0)
        self.assertIn("# 0 new, 0 modified, 1 known", buf.getvalue())


class ResolveStoreParityTest(unittest.TestCase):
    """cache.py and manifest.py each implement the key helpers; keep them equal.

    They cannot share code — manifest.py is a standalone stdlib script that ships
    without the package — so this test is the guard that a change to one side
    cannot silently diverge from the other.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        os.environ["WIKI_PARITY_ROOT"] = str(self.root)

    def tearDown(self) -> None:
        os.environ.pop("WIKI_PARITY_ROOT", None)
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.tmp.cleanup()

    def test_resolve_key_agrees(self) -> None:
        cases = [
            "Raw/x.pdf",
            "~/.claude/x.jsonl",
            "$WIKI_PARITY_ROOT/abs/x.md",
            str(self.root / "outside" / "y.md"),
            "repo:github.com/o/n",
            "url:https://example.com/x",
            "agent:claude/1",
            "src:abcdef01",
        ]
        for key in cases:
            got_cache = cache_resolve_key(key, self.vault)
            got_manifest = manifest.resolve_key(key, str(self.vault))
            expected = str(got_cache) if got_cache is not None else None
            self.assertEqual(expected, got_manifest, f"resolve_key disagrees on {key!r}")

    def test_stored_key_agrees(self) -> None:
        paths = [
            self.vault / "Raw" / "x.pdf",
            self.home / ".claude" / "x.jsonl",
            self.root / "outside" / "y.md",
        ]
        for path in paths:
            self.assertEqual(
                cache_stored_key(path, self.vault),
                manifest.stored_key(str(path), str(self.vault)),
                f"stored_key disagrees on {path}",
            )


if __name__ == "__main__":
    unittest.main()
