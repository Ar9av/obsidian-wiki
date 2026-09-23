"""docs/configuration.md and the wiki-ingest skill must agree that promoted
_raw/ files are archived, not deleted (#235)."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RawPromotionDocsTest(unittest.TestCase):
    def test_docs_and_skill_both_archive_promoted_raw_files(self) -> None:
        skill = (ROOT / ".skills/wiki-ingest/SKILL.md").read_text(encoding="utf-8")
        docs = (ROOT / "docs/configuration.md").read_text(encoding="utf-8")
        self.assertIn("_raw/_archived/", skill)
        self.assertIn("_raw/_archived/", docs)
        self.assertNotIn("removes the originals", docs)


if __name__ == "__main__":
    unittest.main()
