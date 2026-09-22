"""Pins the memory-surface documentation contract.

The code is only half the change: the reason the surface drifted in the first
place was that every skill carried its own prose copy of the procedure. These
tests guard the seams — that the skills point at the CLI rather than restating
it, that the documented variables are the ones the code reads, and that the
figures a reader is promised actually ship.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
IMAGES = DOCS / "images"
SKILLS = ROOT / ".skills"


class MemoryDocsTest(unittest.TestCase):
    def test_the_concept_page_exists_and_is_linked(self) -> None:
        page = DOCS / "memory.md"
        self.assertTrue(page.is_file(), "docs/memory.md is missing")
        for name in ("README.md", "README_TW.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("docs/memory.md", text, f"{name} does not link the memory page")

    def test_every_referenced_image_exists(self) -> None:
        broken = []
        for markdown in DOCS.glob("*.md"):
            body = markdown.read_text(encoding="utf-8")
            for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", body):
                src = match.group(1)
                if src.startswith("http"):
                    continue
                if not (markdown.parent / src).exists():
                    broken.append(f"{markdown.name} -> {src}")
        self.assertEqual(broken, [], f"broken relative image references: {broken}")

    def test_the_figures_ship(self) -> None:
        expected = {
            "memory-architecture.png",
            "memory-session-lifecycle.png",
            "memory-cli-session.png",
            "memory-check-gate.png",
            "memory-hot-cache.png",
        }
        present = {path.name for path in IMAGES.glob("*.png")}
        self.assertTrue(expected <= present, f"missing figures: {sorted(expected - present)}")

    def test_documented_env_vars_are_the_ones_the_code_reads(self) -> None:
        """A documented knob nothing reads is the defect this release fixed."""
        recap_hook = (ROOT / ".claude" / "hooks" / "wiki-session-recap.sh").read_text(encoding="utf-8")
        stop_hook = (ROOT / ".claude" / "hooks" / "wiki-stop-capture.sh").read_text(encoding="utf-8")
        memory = (ROOT / "obsidian_wiki" / "memory.py").read_text(encoding="utf-8")

        for variable in (
            "WIKI_SESSION_RECAP",
            "WIKI_RECAP_MAX_WORDS",
            "WIKI_RECAP_MIN_CONFIDENCE",
            "WIKI_RECAP_TIMEOUT",
            "WIKI_RECAP_PROJECT",
            "WIKI_RECAP_DEBUG",   # read only once /tmp/blocked-edits.py has been applied
        ):
            self.assertIn(variable, recap_hook, f"{variable} documented but unread")

        for variable in ("WIKI_STOP_CAPTURE", "HIVEMIND_CAPTURE"):
            self.assertIn(variable, stop_hook, f"{variable} documented but unread")

        self.assertIn("OBSIDIAN_HOT_MAX_WORDS", memory)

        configuration = (DOCS / "configuration.md").read_text(encoding="utf-8")
        for variable in ("WIKI_SESSION_RECAP", "WIKI_STOP_CAPTURE", "OBSIDIAN_HOT_MAX_WORDS"):
            self.assertIn(variable, configuration, f"{variable} read but undocumented")

    WRITE_SKILLS = (
        "wiki-ingest", "wiki-update", "wiki-capture", "wiki-research", "wiki-synthesize",
        "wiki-dedup", "wiki-import", "wiki-agent", "wiki-stage-commit", "cross-linker",
        "tag-taxonomy", "daily-update",
        "claude-history-ingest", "codex-history-ingest", "copilot-history-ingest",
        "hermes-history-ingest", "openclaw-history-ingest", "pi-history-ingest",
    )

    def test_every_write_skill_calls_the_shared_writer(self) -> None:
        """A skill that still rewrites hot.md by hand drops the per-file
        marker and, before the adoption record existed, re-armed the guard."""
        for name in self.WRITE_SKILLS:
            text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertRegex(
                text, r"obsidian-wiki memory (sync|hot|index)",
                f"{name} does not call the shared writer",
            )

    def test_no_skill_tells_the_model_to_create_hot_md_from_a_template(self) -> None:
        """That instruction produced a hot.md with no marker and no lock."""
        offenders = [
            path.parent.name for path in SKILLS.glob("*/SKILL.md")
            if "create from the template in `wiki-ingest`" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_read_only_skills_log_through_the_writer(self) -> None:
        for name in ("wiki-query", "wiki-narrate"):
            text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("obsidian-wiki memory log", text, f"{name} appends to log.md by hand")

    def test_the_shared_reference_states_the_non_obvious_rules(self) -> None:
        reference = (SKILLS / "llm-wiki" / "references" / "MEMORY.md").read_text(encoding="utf-8")
        for rule in (
            "Key Takeaways",       # the one slot that stays the model's
            "Staleness is reported",  # todos are never auto-closed
            "--check",             # the CI gate
        ):
            self.assertIn(rule, reference, f"MEMORY.md omits: {rule}")

    def test_architecture_no_longer_claims_the_prose_files_are_unlocked(self) -> None:
        """The old text told readers those files were deliberately unprotected."""
        architecture = (DOCS / "architecture.md").read_text(encoding="utf-8")
        self.assertNotIn("The prose files take no lock", architecture)
        self.assertIn(".memory.lock", architecture)



class HooksDocsTest(unittest.TestCase):
    def test_the_installer_is_documented_where_people_will_look(self) -> None:
        """A normal install got no session-start injection because the only
        install procedure was prose and covered one hook. The command must be
        findable from the CLI reference and the install guide."""
        for page in ("cli.md", "installation.md", "memory.md"):
            text = (DOCS / page).read_text(encoding="utf-8")
            self.assertIn("hooks install", text, f"{page} does not mention `hooks install`")

    def test_the_debug_switch_is_documented(self) -> None:
        configuration = (DOCS / "configuration.md").read_text(encoding="utf-8")
        self.assertIn("WIKI_RECAP_DEBUG", configuration)

    def test_the_adoption_record_is_documented(self) -> None:
        memory = (DOCS / "memory.md").read_text(encoding="utf-8")
        self.assertIn(".memory-adopted", memory)

if __name__ == "__main__":
    unittest.main()


class ShortFormDocsTest(unittest.TestCase):
    """The flag form is still supported, but nothing should *teach* it."""

    def test_no_skill_teaches_the_verbose_flag_form(self) -> None:
        offenders = [
            path.parent.name for path in SKILLS.glob("*/SKILL.md")
            if "--field " in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [], f"still using --field: {offenders}")

    def test_no_doc_teaches_the_verbose_flag_form(self) -> None:
        offenders = [
            page.name for page in DOCS.glob("*.md")
            if "--field " in page.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_the_quickstart_does_not_need_a_separate_hook_step(self) -> None:
        """`setup` registers them, so the README must not add a third line."""
        for name in ("README.md", "README_TW.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            quickstart = text.split("```bash", 1)[1].split("```", 1)[0]
            self.assertNotIn("hooks install", quickstart, f"{name} quickstart has an extra step")
