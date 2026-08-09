from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WikiNarrateDocsTest(unittest.TestCase):
    def read(self, relpath: str) -> str:
        return (ROOT / relpath).read_text()

    def test_skill_declares_the_canonical_command_and_voices(self) -> None:
        skill = self.read(".skills/wiki-narrate/SKILL.md")

        self.assertIn("/wiki-narrate <topic> [--voice briefing|plain-language|lecturer] [--save]", skill)
        self.assertIn("default voice is `briefing`", skill)
        self.assertIn("case-sensitive", skill)
        self.assertIn("Unsupported values", skill)

    def test_skill_requires_closed_set_citations(self) -> None:
        skill = self.read(".skills/wiki-narrate/SKILL.md")

        self.assertIn("every factual sentence", skill)
        self.assertIn("^[inferred]", skill)
        self.assertIn("^[ambiguous]", skill)
        self.assertIn("web knowledge", skill)
        self.assertIn("model memory", skill)

    def test_skill_keeps_readouts_out_of_the_knowledge_graph(self) -> None:
        skill = self.read(".skills/wiki-narrate/SKILL.md")

        self.assertIn("`_readouts/<slug>.md`", skill)
        self.assertIn("must not update `index.md` or `.manifest.json`", skill)
        self.assertIn("exclude `_readouts/`", skill)

    def test_voice_reference_has_exactly_the_three_first_release_voices(self) -> None:
        voices = self.read(".skills/wiki-narrate/references/voices.md")

        headings = set(re.findall(r"^## `([^`]+)`$", voices, flags=re.MULTILINE))
        self.assertEqual(headings, {"briefing", "plain-language", "lecturer"})

    def test_routing_and_skills_reference_expose_wiki_narrate(self) -> None:
        agents = self.read("AGENTS.md")
        skills = self.read("docs/skills.md")

        self.assertIn("`wiki-narrate`", agents)
        self.assertIn("`wiki-narrate`", skills)
        self.assertIn("`/wiki-narrate <topic>`", skills)


if __name__ == "__main__":
    unittest.main()
