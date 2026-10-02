"""The repo doubles as a Claude Code plugin marketplace (.claude-plugin/).

`/plugin marketplace add Ar9av/obsidian-wiki` reads marketplace.json, follows the
plugin's `source` to plugin.json, and loads skills from the path it names. Each
hop is a string nothing else checks, so a rename or a moved directory would
break the install silently.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / ".claude-plugin"


def _load(name: str) -> dict:
    return json.loads((PLUGIN_DIR / name).read_text(encoding="utf-8"))


class ClaudePluginTest(unittest.TestCase):
    def setUp(self) -> None:
        self.marketplace = _load("marketplace.json")
        self.plugin = _load("plugin.json")

    def test_marketplace_lists_this_repo_as_the_plugin(self) -> None:
        entries = self.marketplace["plugins"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["name"], self.plugin["name"])
        source = (ROOT / entry["source"]).resolve()
        self.assertEqual(source, ROOT)
        self.assertTrue((source / ".claude-plugin" / "plugin.json").is_file())

    def test_install_id_matches_the_docs(self) -> None:
        install_id = f"{self.plugin['name']}@{self.marketplace['name']}"
        self.assertEqual(install_id, "obsidian-wiki@obsidian-wiki")
        for doc in ("README.md", "README_TW.md", "docs/installation.md"):
            with self.subTest(doc=doc):
                self.assertIn(f"/plugin install {install_id}", (ROOT / doc).read_text(encoding="utf-8"))

    def test_skills_path_loads_every_skill(self) -> None:
        skills_dir = (ROOT / self.plugin["skills"]).resolve()
        self.assertEqual(skills_dir, ROOT / ".skills")
        found = {p.parent.name for p in skills_dir.glob("*/SKILL.md")}
        self.assertIn("wiki-setup", found)
        self.assertIn("wiki-query", found)

    def test_no_pinned_version(self) -> None:
        # Without a version Claude Code keys the install on the git commit, so
        # `marketplace update` delivers every change on main. A pinned version
        # would freeze users until someone remembers to bump it.
        self.assertNotIn("version", self.plugin)
        self.assertNotIn("version", self.marketplace["plugins"][0])


if __name__ == "__main__":
    unittest.main()
