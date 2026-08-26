"""Regression guard for issue #152.

The daily-update skill's Setup Mode references helper scripts under
``scripts/`` (daily-update.sh, the launchd plist, wiki-notify.sh) that are
committed to the repo but were never force-included into the published wheel
— the same packaging-gap class as #143 (the Stop hook), which that fix did
not cover. These tests pin the packaging config that force-includes
``scripts/`` and the skill instructions that resolve it via
``$OBSIDIAN_WIKI_REPO``.
"""

from __future__ import annotations

from pathlib import Path
import unittest

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
PACKAGED_SCRIPTS_DEST = "obsidian_wiki/_data/scripts"
WRITING_PROFILE_TEMPLATE = ROOT / ".skills" / "llm-wiki" / "references" / "WRITING.md"

REFERENCED_SCRIPTS = (
    "daily-update.sh",
    "com.obsidian-wiki.daily-update.plist",
    "wiki-notify.sh",
)


@unittest.skipIf(tomllib is None, "tomllib requires Python 3.11+")
class ScriptsPackagingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    def test_referenced_scripts_exist(self) -> None:
        for name in REFERENCED_SCRIPTS:
            with self.subTest(script=name):
                self.assertTrue((SCRIPTS_DIR / name).is_file(), f"{name} must exist to be bundled")

    def test_wheel_force_includes_scripts_dir(self) -> None:
        mapping = self.pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
        self.assertEqual(
            mapping.get("scripts"),
            PACKAGED_SCRIPTS_DEST,
            "wheel must force-include scripts/ under _data/scripts/",
        )

    def test_writing_profile_template_exists(self) -> None:
        self.assertTrue(WRITING_PROFILE_TEMPLATE.is_file())
        body = WRITING_PROFILE_TEMPLATE.read_text()
        self.assertIn("# Wiki Writing Profile", body)
        self.assertIn("## Language", body)
        self.assertIn("## Conditional Rules", body)

    def test_wheel_force_includes_skills_tree(self) -> None:
        mapping = self.pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
        self.assertEqual(mapping.get(".skills"), "obsidian_wiki/_data/skills")

    def test_scripts_dir_not_excluded_from_sdist(self) -> None:
        # Unlike /.claude, scripts/ isn't pruned, so the default VCS-tracked
        # sdist already carries it — the wheel (built from the sdist) can
        # force-include it from there. If this ever gets added to the sdist
        # exclude list, it would also need a matching force-include re-add.
        sdist_exclude = self.pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"]
        self.assertNotIn("/scripts", sdist_exclude)

    def test_wheel_excludes_pycache_from_force_included_dirs(self) -> None:
        # force-include copies straight from the working tree (not a
        # VCS-filtered view), so a local scripts/__pycache__ can otherwise
        # leak stray .pyc files into the published wheel.
        wheel_exclude = self.pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["exclude"]
        self.assertIn("**/__pycache__", wheel_exclude)


class DailyUpdateSkillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = (ROOT / ".skills" / "daily-update" / "SKILL.md").read_text()

    def test_skill_resolves_scripts_via_repo_var(self) -> None:
        for name in REFERENCED_SCRIPTS:
            with self.subTest(script=name):
                self.assertIn(f"$OBSIDIAN_WIKI_REPO/scripts/{name}", self.skill)


if __name__ == "__main__":
    unittest.main()
