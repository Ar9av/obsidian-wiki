from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InlineVaultTargetingDocsTest(unittest.TestCase):
    def read(self, relpath: str) -> str:
        return (ROOT / relpath).read_text()

    def test_central_protocol_documents_inline_override_before_fallbacks(self) -> None:
        llm_wiki = self.read(".skills/llm-wiki/SKILL.md")
        agents = self.read("AGENTS.md")

        self.assertIn("0. **Inline vault override (`@name`)", llm_wiki)
        self.assertIn("0. **Inline vault override (`@name`)", agents)
        self.assertIn("resolve `~/.obsidian-wiki/config.<name>` directly", llm_wiki)
        self.assertIn("do **not** silently fall back to the default", agents)

    def test_skill_resolution_summaries_include_inline_override(self) -> None:
        stale = []
        for skill_file in sorted((ROOT / ".skills").glob("*/SKILL.md")):
            text = skill_file.read_text()
            if "follow the Config Resolution Protocol" not in text:
                continue
            if "walk up CWD for `.env`" in text and "inline `@name` override" not in text:
                stale.append(skill_file.relative_to(ROOT).as_posix())

        self.assertEqual(stale, [])

    def test_agent_bootstrap_files_mention_named_vault_routing(self) -> None:
        for relpath in [
            "AGENTS.md",
            ".agent/rules/obsidian-wiki.md",
            ".cursor/rules/obsidian-wiki.mdc",
            ".github/copilot-instructions.md",
            ".kiro/steering/obsidian-wiki.md",
            ".windsurf/rules/obsidian-wiki.md",
            "README.md",
            "SETUP.md",
        ]:
            with self.subTest(relpath=relpath):
                self.assertIn("@name", self.read(relpath))

    def test_readme_says_all_supported_agents_inherit_named_vault_routing(self) -> None:
        readme = self.read("README.md")

        self.assertIn("All supported agents can use this syntax", readme)
        self.assertIn("Claude Code, Cursor, Windsurf, Codex, Gemini", readme)

    def test_core_skill_descriptions_include_named_vault_examples(self) -> None:
        examples = {
            ".skills/wiki-query/SKILL.md": "wiki-query @work",
            ".skills/wiki-update/SKILL.md": "@work update wiki",
            ".skills/wiki-capture/SKILL.md": "@research save this",
        }

        for relpath, expected in examples.items():
            with self.subTest(relpath=relpath):
                self.assertIn(expected, self.read(relpath))

    def test_wiki_query_does_not_prefer_default_over_inline_override(self) -> None:
        wiki_query = self.read(".skills/wiki-query/SKILL.md")

        self.assertIn("For cross-project queries without `@name`", wiki_query)
        self.assertNotIn("Prefer `~/.obsidian-wiki/config` for cross-project queries", wiki_query)


if __name__ == "__main__":
    unittest.main()
