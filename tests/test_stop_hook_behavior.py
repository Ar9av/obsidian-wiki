"""Behavioral tests for the Stop hook's trigger logic.

Runs ``wiki-stop-capture.sh`` against synthetic transcripts and asserts on the
exit code contract (0 = silent, 2 = nudge on stderr). Covers the read-only
session exemption: a session with zero file edits whose shell commands are all
provably read-only must not nudge, while any file edit — or shell activity the
classifier can't prove read-only — keeps the pre-exemption behavior.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude" / "hooks" / "wiki-stop-capture.sh"


def _bash_entry(command):
    return {
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": command}}],
        }
    }


def _edit_entry(tool="Edit"):
    return {
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": tool, "input": {"file_path": "/tmp/x"}}],
        }
    }


@unittest.skipIf(shutil.which("bash") is None, "requires bash")
class StopHookBehaviorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._session_seq = 0

    def _run(self, entries, session_id=None, stop_hook_active=False):
        transcript = self.tmp / "transcript.jsonl"
        transcript.write_text("".join(json.dumps(e) + "\n" for e in entries))
        if session_id is None:
            self._session_seq += 1
            session_id = f"s{self._session_seq}"
        payload = {
            "session_id": session_id,
            "transcript_path": str(transcript),
            "stop_hook_active": stop_hook_active,
        }
        # Isolated TMPDIR so sentinel state never leaks between tests.
        return subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", "TMPDIR": str(self.tmp)},
        )

    def test_file_edit_triggers_nudge(self):
        result = self._run([_edit_entry()])
        self.assertEqual(result.returncode, 2)
        self.assertIn("/wiki-capture --quick", result.stderr)

    def test_readonly_session_is_exempt(self):
        entries = [
            _bash_entry("gh pr list --state open"),
            _bash_entry("git log --oneline -20"),
            _bash_entry("grep -rn 'pattern' src/ | head -50"),
            _bash_entry("cat README.md"),
            _bash_entry("python3 -c \"import json,sys; print(json.load(sys.stdin))\""),
            _bash_entry("curl -s https://api.example.com/status"),
        ]
        result = self._run(entries)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_one_mutating_command_restores_trigger(self):
        entries = [
            _bash_entry("git status"),
            _bash_entry("ls -la"),
            _bash_entry("grep foo bar.txt"),
            _bash_entry("npm install left-pad"),
        ]
        result = self._run(entries)
        self.assertEqual(result.returncode, 2)

    def test_redirect_counts_as_mutating(self):
        entries = [_bash_entry("echo hi > out.txt")] * 4
        result = self._run(entries)
        self.assertEqual(result.returncode, 2)

    def test_devnull_redirect_stays_readonly(self):
        entries = [_bash_entry("grep -c foo bar.txt 2>/dev/null")] * 4
        result = self._run(entries)
        self.assertEqual(result.returncode, 0)

    def test_mutating_git_and_sed_classified(self):
        entries = [
            _bash_entry("git checkout -b feature"),
            _bash_entry("sed -i '' 's/a/b/' file.txt"),
            _bash_entry("git push origin main"),
            _bash_entry("mkdir -p build"),
        ]
        result = self._run(entries)
        self.assertEqual(result.returncode, 2)

    def test_below_threshold_is_silent(self):
        entries = [_bash_entry("npm install"), _bash_entry("rm -rf build")]
        result = self._run(entries)
        self.assertEqual(result.returncode, 0)

    def test_sentinel_prevents_second_nudge(self):
        first = self._run([_edit_entry()], session_id="same")
        self.assertEqual(first.returncode, 2)
        second = self._run([_edit_entry()], session_id="same")
        self.assertEqual(second.returncode, 0)
        self.assertEqual(second.stderr, "")

    def test_stop_hook_active_suppresses(self):
        result = self._run([_edit_entry()], stop_hook_active=True)
        self.assertEqual(result.returncode, 0)

    def test_below_threshold_does_not_burn_sentinel(self):
        quiet = self._run([_bash_entry("ls")], session_id="keep")
        self.assertEqual(quiet.returncode, 0)
        busy = self._run([_edit_entry()], session_id="keep")
        self.assertEqual(busy.returncode, 2)


if __name__ == "__main__":
    unittest.main()
