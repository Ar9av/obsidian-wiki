from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "check_readme_sync.py"


class ReadmeDriftTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def commit(self, message: str, *files: str) -> None:
        for name in files:
            path = self.repo / name
            path.write_text(path.read_text() + message + "\n" if path.exists() else message + "\n")
        self.git("add", *files)
        self.git("commit", "-q", "-m", message)

    def run_checker(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER)],
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_in_sync_passes(self) -> None:
        self.commit("initial docs", "README.md", "README_TW.md")

        result = self.run_checker()

        self.assertEqual(result.returncode, 0)
        self.assertIn("up to date", result.stdout)

    def test_english_only_commits_are_reported_with_diff(self) -> None:
        self.commit("initial docs", "README.md", "README_TW.md")
        self.commit("add install section", "README.md")

        result = self.run_checker()

        self.assertEqual(result.returncode, 1)
        self.assertIn("add install section", result.stdout)
        self.assertIn("+add install section", result.stdout)
        self.assertIn("backfill", result.stdout)

    def test_later_translation_commit_clears_drift(self) -> None:
        self.commit("initial docs", "README.md", "README_TW.md")
        self.commit("add install section", "README.md")
        self.commit("translate install section", "README_TW.md")

        result = self.run_checker()

        self.assertEqual(result.returncode, 0)

    def test_unrelated_commits_do_not_trigger_drift(self) -> None:
        self.commit("initial docs", "README.md", "README_TW.md")
        self.commit("tweak cli", "cli.py")

        result = self.run_checker()

        self.assertEqual(result.returncode, 0)

    def test_sync_workflow_is_documented(self) -> None:
        for path in (ROOT / "AGENTS.md", ROOT / "README.md", ROOT / "README_TW.md"):
            with self.subTest(path=path.name):
                contents = path.read_text(encoding="utf-8")
                self.assertIn("check_readme_sync.py", contents)


if __name__ == "__main__":
    unittest.main()
