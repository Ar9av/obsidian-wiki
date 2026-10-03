"""OKF v0.2 conformance for the wiki-export / wiki-import bridge.

tests/fixtures/okf_v02_bundle/ is a real bundle: an agent ran
.skills/wiki-export/SKILL.md Step 3.5 over a five-page vault that exercises
every mapping row (date-only and offset `updated`, URL and opaque sources,
draft/verified/archived lifecycles, a trust-ledger entry, a folder note, a
forward reference). Importing it back with wiki-import reproduced the source
pages exactly. These tests pin the shape of that output against the spec's
rules, and keep the two skills describing the same mapping.

Pure stdlib (CI has no PyYAML), so frontmatter is checked line by line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from obsidian_wiki.vault import split_frontmatter

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "tests" / "fixtures" / "okf_v02_bundle"
EXPORT = ROOT / ".skills" / "wiki-export" / "SKILL.md"
IMPORT = ROOT / ".skills" / "wiki-import" / "SKILL.md"
DATETIME_WITH_OFFSET = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)")


def _frontmatter(path: Path) -> str:
    fm, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    return fm


def _block(fm: str, key: str) -> list[str]:
    """Lines indented under a top-level `key:` (empty when key is inline or absent)."""
    lines = fm.splitlines()
    for i, line in enumerate(lines):
        if line == f"{key}:":
            out = []
            for nxt in lines[i + 1:]:
                if nxt and not nxt.startswith(" "):
                    break
                out.append(nxt)
            return out
    return []


def _top_value(fm: str, key: str) -> str | None:
    m = re.search(rf"^{key}:[ \t]*(.*)$", fm, re.M)
    return m.group(1).strip().strip('"') if m else None


def _concepts() -> list[Path]:
    return [p for p in sorted(BUNDLE.rglob("*.md")) if p.name not in ("index.md", "log.md")]


class OkfV02BundleTest(unittest.TestCase):
    def test_fixture_has_every_case(self) -> None:
        self.assertEqual(len(_concepts()), 5)

    def test_every_concept_has_a_type(self) -> None:  # §11 rules 1-2
        for path in _concepts():
            with self.subTest(page=path.relative_to(BUNDLE).as_posix()):
                self.assertTrue(_top_value(_frontmatter(path), "type"))

    def test_generated_replaces_timestamp(self) -> None:  # §5.2, §13.1
        for path in _concepts():
            fm = _frontmatter(path)
            with self.subTest(page=path.relative_to(BUNDLE).as_posix()):
                self.assertIsNone(_top_value(fm, "timestamp"))
                block = "\n".join(_block(fm, "generated"))
                self.assertRegex(block, r"by: obsidian-wiki(/\S+)?")
                at = re.search(r"at: (\S+)", block)
                self.assertIsNotNone(at)
                self.assertRegex(at.group(1), DATETIME_WITH_OFFSET)

    def test_sources_are_resource_objects(self) -> None:  # §5.1
        for path in _concepts():
            entries = [line for line in _block(_frontmatter(path), "sources") if line.lstrip().startswith("- ")]
            with self.subTest(page=path.relative_to(BUNDLE).as_posix()):
                self.assertTrue(entries)
                for entry in entries:
                    self.assertRegex(entry.strip(), r"^- resource: \S")

    def test_status_follows_lifecycle(self) -> None:  # §5.4
        expected = {"draft": "draft", "verified": "stable", "archived": "deprecated", None: None}
        for path in _concepts():
            fm = _frontmatter(path)
            with self.subTest(page=path.relative_to(BUNDLE).as_posix()):
                self.assertEqual(_top_value(fm, "status"), expected[_top_value(fm, "lifecycle")])

    def test_verified_only_from_the_trust_ledger(self) -> None:  # §5.2, §5.3, §7
        verified = {p.relative_to(BUNDLE).as_posix(): _block(_frontmatter(p), "verified") for p in _concepts()}
        self.assertEqual([k for k, v in verified.items() if v], ["concepts/rate-limiting.md"])
        block = "\n".join(verified["concepts/rate-limiting.md"])
        self.assertIn("human:vault-owner", block)
        self.assertRegex(re.search(r"at: (\S+)", block).group(1), DATETIME_WITH_OFFSET)

    def test_native_updated_rides_along(self) -> None:
        # generated.at must be a datetime; the native value keeps date-only precision.
        fm = _frontmatter(BUNDLE / "entities" / "redis.md")
        self.assertEqual(_top_value(fm, "updated"), "2026-03-02")

    def test_index_files(self) -> None:  # §8
        self.assertEqual(_top_value(_frontmatter(BUNDLE / "index.md"), "okf_version"), "0.2")
        for path in BUNDLE.rglob("index.md"):
            if path != BUNDLE / "index.md":
                with self.subTest(index=path.relative_to(BUNDLE).as_posix()):
                    self.assertEqual(_frontmatter(path), "")

    def test_log_is_date_grouped_newest_first(self) -> None:  # §9
        dates = re.findall(r"^## (.+)$", (BUNDLE / "log.md").read_text(encoding="utf-8"), re.M)
        self.assertTrue(dates)
        for d in dates:
            self.assertRegex(d, r"^\d{4}-\d\d-\d\d$")
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_links_are_file_relative(self) -> None:  # §6; folder-note case
        body = (BUNDLE / "projects" / "demo" / "concepts" / "note.md").read_text(encoding="utf-8")
        self.assertIn("](../../demo.md)", body)
        for path in _concepts():
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"\]\(/")


class OkfSkillsAgreeTest(unittest.TestCase):
    def test_export_targets_v02(self) -> None:
        text = EXPORT.read_text(encoding="utf-8")
        self.assertIn('okf_version: "0.2"', text)
        self.assertNotIn('okf_version: "0.1"', text)
        self.assertIn("generated: { by: obsidian-wiki/<version>, at: <datetime> }", text)

    def test_import_reads_both_versions(self) -> None:
        text = IMPORT.read_text(encoding="utf-8")
        self.assertIn("`generated.at`", text)
        self.assertIn("legacy v0.1 `timestamp`", text)
        self.assertIn("take its `resource`", text)
        # Undo what our own exporter derived, or the round-trip adds keys.
        self.assertIn("starts with `obsidian-wiki/`", text)
        self.assertIn("`human:vault-owner`", text)

    def test_docs_claim_v02(self) -> None:
        for doc in ("AGENTS.md", "docs/architecture.md"):
            with self.subTest(doc=doc):
                text = (ROOT / doc).read_text(encoding="utf-8")
                self.assertIn("v0.2", text)
                self.assertNotIn("OKF) v0.1", text)
                self.assertNotIn("OKF v0.1]", text)


if __name__ == "__main__":
    unittest.main()
