"""Regression guard for issue #143.

The wiki-setup skill wires a Claude Code Stop hook that runs
``wiki-stop-capture.sh``. That script lives under ``.claude/hooks/`` in the repo,
which the sdist prunes — so it was silently missing from the published wheel and
the installed hook pointed at a nonexistent path. These tests pin the packaging
config that force-includes the script and the skill instructions that resolve it.
"""

from __future__ import annotations

from pathlib import Path
import unittest

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]
HOOK_SRC = ROOT / ".claude" / "hooks" / "wiki-stop-capture.sh"
PACKAGED_HOOK_DEST = "obsidian_wiki/_data/hooks/wiki-stop-capture.sh"


@unittest.skipIf(tomllib is None, "tomllib requires Python 3.11+")
class StopHookPackagingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    def test_hook_source_exists(self) -> None:
        self.assertTrue(HOOK_SRC.is_file(), f"{HOOK_SRC} must exist to be bundled")

    def test_wheel_force_includes_hook(self) -> None:
        mapping = self.pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
        self.assertEqual(
            mapping.get(".claude/hooks/wiki-stop-capture.sh"),
            PACKAGED_HOOK_DEST,
            "wheel must force-include the Stop hook under _data/hooks/",
        )

    def test_sdist_reincludes_hook_despite_claude_exclusion(self) -> None:
        # The wheel is built from the sdist, and the sdist prunes /.claude — so
        # the one hook script must be force-included back or the wheel copy fails.
        sdist = self.pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]
        self.assertIn("/.claude", sdist["exclude"])
        self.assertEqual(
            sdist["force-include"].get(".claude/hooks/wiki-stop-capture.sh"),
            ".claude/hooks/wiki-stop-capture.sh",
        )


class WikiSetupSkillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = (ROOT / ".skills" / "wiki-setup" / "SKILL.md").read_text()

    def test_skill_points_at_packaged_hook_path(self) -> None:
        # Must reference the packaged layout, not only the source-checkout path.
        self.assertIn("<REPO_PATH>/hooks/wiki-stop-capture.sh", self.skill)

    def test_skill_offers_github_fallback(self) -> None:
        self.assertIn(
            "raw.githubusercontent.com/Ar9av/obsidian-wiki/main/.claude/hooks/wiki-stop-capture.sh",
            self.skill,
        )

    def test_setup_creates_manifest(self) -> None:
        # Secondary fix: doctor requires .manifest.json among core vault files.
        self.assertIn(".manifest.json", self.skill)


if __name__ == "__main__":
    unittest.main()
