"""examples/demo-vault/ is the first vault many people open, so it has to be
one the framework itself considers healthy: lint-clean, fully linked, and
already adopted by the memory writer so a user's first write updates
index.md and hot.md instead of skipping them.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from obsidian_wiki.lint import lint_vault
from obsidian_wiki.vault import iter_md, split_frontmatter

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "examples" / "demo-vault"
CATEGORIES = ("concepts", "entities", "skills", "references", "synthesis", "journal")
REQUIRED = ("title", "category", "tags", "sources", "created", "updated", "summary", "base_confidence", "lifecycle")
LINK = re.compile(r"\[\[([^\]|\\#]+)")


def _pages() -> list[Path]:
    return [p for p in iter_md(VAULT) if p.relative_to(VAULT).parts[0] in CATEGORIES]


class DemoVaultTest(unittest.TestCase):
    def test_lint_has_no_failures(self) -> None:
        # The only accepted warning is the missing trust ledger: recording one
        # needs `trust-record --approved`, a human sign-off sample content lacks.
        report = lint_vault(VAULT)
        problems = {k: v for k, v in report["findings"].items() if v}
        self.assertEqual(set(problems), {"confidence_ledger_errors"}, problems)
        self.assertEqual([e["issue"] for e in problems["confidence_ledger_errors"]], ["ledger_missing"])

    def test_every_category_is_populated(self) -> None:
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertGreaterEqual(len(list((VAULT / category).glob("*.md"))), 2)

    def test_required_frontmatter(self) -> None:
        for page in _pages():
            fm, _ = split_frontmatter(page.read_text(encoding="utf-8"))
            for key in REQUIRED:
                with self.subTest(page=page.relative_to(VAULT).as_posix(), key=key):
                    self.assertRegex(fm, rf"(?m)^{key}:")

    def test_links_resolve_and_every_page_is_linked_to(self) -> None:
        ids = {p.relative_to(VAULT).with_suffix("").as_posix() for p in _pages()}
        inbound = dict.fromkeys(ids, 0)
        for page in _pages():
            own = page.relative_to(VAULT).with_suffix("").as_posix()
            for target in set(LINK.findall(page.read_text(encoding="utf-8"))):
                with self.subTest(page=own, link=target):
                    self.assertIn(target, ids)
                if target != own:
                    inbound[target] += 1
        self.assertEqual([k for k, v in inbound.items() if v == 0], [])

    def test_adopted_by_the_memory_writer(self) -> None:
        self.assertTrue((VAULT / "_meta" / ".memory-adopted").is_file())
        for name, writer in (("index.md", "memory index"), ("hot.md", "memory hot")):
            with self.subTest(file=name):
                fm, _ = split_frontmatter((VAULT / name).read_text(encoding="utf-8"))
                self.assertIn(f"generated_by: obsidian-wiki {writer}", fm)
        self.assertFalse((VAULT / "_archives").exists(), "drop the migration backup before committing")

    def test_graph_is_colored_by_folder(self) -> None:
        graph = json.loads((VAULT / ".obsidian" / "graph.json").read_text(encoding="utf-8"))
        queries = {group["query"] for group in graph["colorGroups"]}
        self.assertEqual(queries, {f"path:{c}" for c in CATEGORIES})


if __name__ == "__main__":
    unittest.main()
