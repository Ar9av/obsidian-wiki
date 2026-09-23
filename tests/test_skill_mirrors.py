"""The committed agent-skill mirrors must track every skill in .skills/ (#233).

setup.sh regenerates them, but a fresh clone opened without running setup
only gets what is committed, so check the git index, not the working tree.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIRRORS = (".agents", ".claude", ".cursor", ".kiro", ".pi", ".windsurf")


def _tracked(path: str) -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", "-s", path], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    # mode 120000 = symlink; the name is the last path component
    return {line.split("\t")[1].rsplit("/", 1)[-1] for line in out.splitlines() if line.startswith("120000")}


@unittest.skipUnless((ROOT / ".git").exists(), "needs a git checkout")
class SkillMirrorsTest(unittest.TestCase):
    def test_every_mirror_links_every_skill(self) -> None:
        skills = {p.parent.name for p in (ROOT / ".skills").glob("*/SKILL.md")}
        for mirror in MIRRORS:
            with self.subTest(mirror=mirror):
                tracked = _tracked(f"{mirror}/skills/")
                self.assertEqual(
                    skills - tracked, set(),
                    f"{mirror}/skills/ is missing committed symlinks; run `bash setup.sh` and commit them",
                )
                self.assertEqual(tracked - skills, set(), f"{mirror}/skills/ links to removed skills")

    def test_mirror_links_are_relative_and_resolve(self) -> None:
        for mirror in MIRRORS:
            for link in (ROOT / mirror / "skills").iterdir():
                if link.is_symlink():
                    self.assertEqual(os.readlink(link), f"../../.skills/{link.name}", str(link))


if __name__ == "__main__":
    unittest.main()
