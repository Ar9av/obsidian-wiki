"""Regression guard for issue #153.

setup.sh (source/curl installs) used to hand-roll its own git-sync logic while
`obsidian-wiki setup` (the pip/uv CLI) had none at all — the two entrypoints
had diverged, and the one most users actually run (pip/uv) silently skipped
GitHub sync. Both now delegate to obsidian_wiki/sync.py. These tests pin that
setup.sh calls into the CLI instead of re-implementing git plumbing, and that
the CLI exposes the subcommands setup.sh (and agents, via wiki-setup) depend on.
"""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SetupShDelegatesToCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.setup_sh = (ROOT / "setup.sh").read_text()

    def test_calls_sync_setup_subcommand(self) -> None:
        self.assertIn("sync-setup", self.setup_sh)

    def test_creates_global_writing_profile_from_canonical_template(self) -> None:
        self.assertIn("WRITING.md", self.setup_sh)
        self.assertIn("llm-wiki/references/WRITING.md", self.setup_sh)

    def test_reports_resolved_writing_profile_path(self) -> None:
        self.assertIn('Writing profile:  $WRITING_PROFILE', self.setup_sh)

    def test_calls_cli_module_not_a_standalone_git_flow(self) -> None:
        self.assertIn("obsidian_wiki.cli", self.setup_sh)

    def test_does_not_hand_roll_git_init(self) -> None:
        # The old setup.sh ran `git -C "$VAULT_PATH" init` directly; that logic
        # must now live only in obsidian_wiki/sync.py.
        self.assertNotIn('git -C "$VAULT_PATH" init', self.setup_sh)

    def test_does_not_generate_a_standalone_sync_script(self) -> None:
        # The old setup.sh wrote a hand-rolled ~/.obsidian-wiki/sync.sh with its
        # own git add/commit/push logic — that's now `obsidian-wiki sync`.
        self.assertNotIn("Wrote ~/.obsidian-wiki/sync.sh", self.setup_sh)


class EnvExampleDoesNotOverclaimTest(unittest.TestCase):
    def test_no_dangling_vault_github_remote_var(self) -> None:
        env_example = (ROOT / ".env.example").read_text()
        self.assertNotIn("VAULT_GITHUB_REMOTE", env_example)


class CliExposesSyncSubcommandsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = (ROOT / "obsidian_wiki" / "cli.py").read_text()

    def test_sync_setup_subcommand_registered(self) -> None:
        self.assertIn('sub.add_parser(\n        "sync-setup"', self.cli)

    def test_sync_subcommand_registered(self) -> None:
        self.assertIn('sub.add_parser("sync"', self.cli)

    def test_setup_command_offers_sync(self) -> None:
        self.assertIn("_maybe_configure_sync", self.cli)


if __name__ == "__main__":
    unittest.main()
