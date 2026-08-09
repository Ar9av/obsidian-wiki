"""Pins the session-brain skill contract.

The Python layer is useless without the two markdown skills that route to it,
and the skills are useless if they claim capabilities the CLI does not have.
These tests guard the seams between them, plus the zero-dependency promise that
the whole TF-IDF implementation exists to keep.
"""

from __future__ import annotations

import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".skills"
AGENTS_MD = ROOT / "AGENTS.md"


class SkillFilesTest(unittest.TestCase):
    def test_both_skills_exist_with_frontmatter(self) -> None:
        for name in ("session-brain", "session-search"):
            path = SKILLS / name / "SKILL.md"
            self.assertTrue(path.is_file(), f"missing {path}")
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), f"{name}: no frontmatter block")
            head = text.split("---", 2)[1]
            self.assertIn(f"name: {name}", head)
            self.assertIn("description:", head)

    def test_routing_rows_are_registered(self) -> None:
        text = AGENTS_MD.read_text(encoding="utf-8")
        self.assertIn("`session-brain`", text)
        self.assertIn("`session-search`", text)
        self.assertIn("/wiki-sessions", text)

    def test_ingest_versus_retrieve_is_disambiguated(self) -> None:
        """Three skills read the same caches for different reasons; without an
        explicit note the router picks between them by coin flip."""
        text = AGENTS_MD.read_text(encoding="utf-8")
        self.assertIn("Session history: ingest vs. retrieve", text)

    def test_search_skill_degrades_without_the_external_loader(self) -> None:
        """claude-session-load lives in the user's personal skills dir, not this
        repo, so the skill must hand off to it without depending on it."""
        text = (SKILLS / "session-search" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("claude-session-load", text)
        self.assertIn("~/.claude/skills/", text)
        self.assertIn("may not exist", text)

    def test_skills_only_reference_real_cli_subcommands(self) -> None:
        from obsidian_wiki.cli import build_parser

        known = set()
        for action in build_parser()._actions:
            if hasattr(action, "choices") and action.choices:
                known.update(action.choices)

        text = "\n".join(
            (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
            for name in ("session-brain", "session-search")
        )
        referenced = {
            token.strip("`.,")
            for token in text.split()
            if token.strip("`.,").startswith("sessions-")
        }
        self.assertTrue(referenced, "skills should invoke the CLI")
        for name in referenced:
            self.assertIn(name, known, f"skill references unknown subcommand {name!r}")

    def test_brain_skill_does_not_promise_vault_writes(self) -> None:
        """The sidecar boundary is the core design decision; a skill that writes
        pages would put 1000+ noisy nodes into a curated graph."""
        text = (SKILLS / "session-brain" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("never touched", text)


class ZeroDependencyTest(unittest.TestCase):
    def test_runtime_dependencies_remain_empty(self) -> None:
        """The hand-rolled TF-IDF exists precisely so this stays true."""
        if tomllib is None:
            self.skipTest("tomllib unavailable")
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["project"]["dependencies"], [])

    def test_session_modules_import_no_third_party_packages(self) -> None:
        import ast

        allowed_stdlib_prefixes = (
            "json", "math", "re", "collections", "dataclasses", "datetime",
            "pathlib", "typing", "os", "sys", "itertools", "functools", "urllib",
        )
        for name in ("session_sources", "session_index", "session_graph",
                     "session_viz", "session_query"):
            source = (ROOT / "obsidian_wiki" / f"{name}.py").read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                module = None
                if isinstance(node, ast.Import):
                    module = node.names[0].name
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                if not module:
                    continue
                root = module.split(".")[0]
                self.assertTrue(
                    root == "obsidian_wiki" or root in allowed_stdlib_prefixes
                    or module.startswith("__future__"),
                    f"{name}.py imports non-stdlib module {module!r}",
                )


if __name__ == "__main__":
    unittest.main()
