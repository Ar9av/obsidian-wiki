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


def _tool_entry(name):
    return {
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": {}}],
        }
    }


_READONLY_BASH = [
    _bash_entry("git status"),
    _bash_entry("ls -la"),
    _bash_entry("grep foo bar.txt"),
    _bash_entry("cat notes.md"),
]


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

    def test_command_substitution_counts_as_mutating(self):
        # $(…) runs an arbitrary inner command — even inside double quotes.
        entries = [_bash_entry('echo "$(rm -rf /tmp/x)"')] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_single_quoted_substitution_stays_literal(self):
        entries = [_bash_entry("grep -F '$(not executed)' file.txt")] * 4
        self.assertEqual(self._run(entries).returncode, 0)

    def test_find_delete_counts_as_mutating(self):
        entries = [_bash_entry("find . -name '*.tmp' -delete")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_find_exec_counts_as_mutating(self):
        entries = [_bash_entry("find . -name '*.log' -exec rm {} +")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_plain_find_stays_readonly(self):
        entries = [_bash_entry("find . -name '*.md' -type f")] * 4
        self.assertEqual(self._run(entries).returncode, 0)

    def test_curl_glued_method_counts_as_mutating(self):
        entries = [
            _bash_entry("curl -XPOST https://api.example.com/things"),
            _bash_entry("curl --request DELETE https://api.example.com/things/1"),
            _bash_entry("curl --json '{}' https://api.example.com/things"),
            _bash_entry("curl -XPUT https://api.example.com/things/2"),
        ]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_sort_output_flag_counts_as_mutating(self):
        entries = [_bash_entry("sort -o sorted.txt input.txt")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_env_unwraps_to_real_command(self):
        entries = [_bash_entry("env FOO=1 python3 build.py")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_bare_env_stays_readonly(self):
        entries = [_bash_entry("env | grep PATH")] * 4
        self.assertEqual(self._run(entries).returncode, 0)

    def test_python_inline_write_counts_as_mutating(self):
        entries = [_bash_entry("python3 -c \"import os; os.remove('x')\"")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_python_inline_parse_stays_readonly(self):
        entries = [_bash_entry("python3 -c \"import json,sys; print(json.load(sys.stdin)['a'])\"")] * 4
        self.assertEqual(self._run(entries).returncode, 0)

    def test_awk_internal_redirect_counts_as_mutating(self):
        entries = [_bash_entry("awk '{print > \"split.txt\"}' data.txt")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_cd_chain_stays_readonly(self):
        entries = [_bash_entry("cd /repo && git log --oneline -5")] * 4
        self.assertEqual(self._run(entries).returncode, 0)

    def test_python_exec_counts_as_mutating(self):
        entries = [_bash_entry("python3 -c \"exec(open('payload.py').read())\"")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_python_open_mode_kwarg_counts_as_mutating(self):
        entries = [_bash_entry("python3 -c \"open('f', mode='w')\"")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_sed_write_command_counts_as_mutating(self):
        entries = [
            _bash_entry("sed -n 'w /tmp/out.txt' input.txt"),
            _bash_entry("sed 's/a/b/w changed.txt' input.txt"),
            _bash_entry("sed -n 'w /tmp/out2.txt' input.txt"),
            _bash_entry("sed 's/x/y/w other.txt' input.txt"),
        ]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_plain_sed_stays_readonly(self):
        entries = [_bash_entry("sed -n '5,10p' input.txt")] * 4
        self.assertEqual(self._run(entries).returncode, 0)

    def test_git_output_flag_counts_as_mutating(self):
        entries = [_bash_entry("git diff --output=changes.patch main")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_curl_short_flag_clusters_count_as_mutating(self):
        entries = [
            _bash_entry("curl -sd '{\"a\":1}' https://api.example.com/x"),
            _bash_entry("curl -sLo out.json https://api.example.com/x"),
            _bash_entry("curl -sT upload.bin https://api.example.com/x"),
            _bash_entry("curl -sD headers.txt https://api.example.com/x"),
        ]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_curl_plain_get_flags_stay_readonly(self):
        entries = [_bash_entry("curl -fsSL https://api.example.com/status")] * 4
        self.assertEqual(self._run(entries).returncode, 0)

    def test_mcp_write_tool_disables_exemption(self):
        # A real system mutation hides behind an MCP call: read-only bash
        # alone must not exempt the session.
        entries = _READONLY_BASH + [_tool_entry("mcp__notion__notion-update-page")]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_mcp_read_tools_keep_exemption(self):
        entries = _READONLY_BASH + [
            _tool_entry("mcp__postgres__list_schemas"),
            _tool_entry("mcp__notion__notion-search"),
            _tool_entry("Read"),
            _tool_entry("Grep"),
        ]
        self.assertEqual(self._run(entries).returncode, 0)

    def test_mcp_write_alone_matches_upstream_threshold(self):
        # Upstream never triggered on MCP-only sessions (no edits, < 4 bash);
        # suspicious tools only disable the exemption, they don't nudge alone.
        entries = [_tool_entry("mcp__notion__notion-update-page")] * 3
        self.assertEqual(self._run(entries).returncode, 0)

    def test_mcp_get_or_create_counts_as_write(self):
        entries = _READONLY_BASH + [_tool_entry("mcp__x__get-or-create-session")]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_unknown_harness_tool_disables_exemption(self):
        entries = _READONLY_BASH + [_tool_entry("Artifact")]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_hostname_with_argument_counts_as_mutating(self):
        entries = [_bash_entry("hostname build-box-7")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_bare_hostname_stays_readonly(self):
        entries = [_bash_entry("hostname"), _bash_entry("hostname -f")] * 2
        self.assertEqual(self._run(entries).returncode, 0)

    def test_fd_exec_counts_as_mutating(self):
        entries = [_bash_entry("fd -e tmp -x rm {}")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_tree_output_flag_counts_as_mutating(self):
        entries = [_bash_entry("tree -o listing.txt src/")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_single_quote_always_closes(self):
        # In shell, backslash does not escape inside '…': the quote after
        # the backslash CLOSES the string and the rm runs unquoted.
        entries = [_bash_entry("echo 'a\\' ; rm -rf /tmp/probe'")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_git_reflog_expire_counts_as_mutating(self):
        entries = [
            _bash_entry("git reflog expire --expire=now --all"),
            _bash_entry("git reflog delete HEAD@{2}"),
            _bash_entry("git reflog expire --expire=now --all"),
            _bash_entry("git reflog delete HEAD@{1}"),
        ]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_git_reflog_show_stays_readonly(self):
        entries = [_bash_entry("git reflog"), _bash_entry("git reflog show HEAD")] * 2
        self.assertEqual(self._run(entries).returncode, 0)

    def test_curl_cookie_jar_counts_as_mutating(self):
        entries = [
            _bash_entry("curl -sc cookies.txt https://example.com/login"),
            _bash_entry("curl --cookie-jar cj.txt https://example.com"),
            _bash_entry("curl --dump-header h.txt https://example.com"),
            _bash_entry("curl --trace-ascii t.log https://example.com"),
        ]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_awk_pipe_to_command_counts_as_mutating(self):
        entries = [_bash_entry("awk '{print | \"sh\"}' cmds.txt")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_sed_glued_write_script_counts_as_mutating(self):
        entries = [_bash_entry("sed -e's/a/b/w out.txt' input.txt")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_history_clear_counts_as_mutating(self):
        entries = [_bash_entry("history -c")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_python_smtplib_counts_as_mutating(self):
        entries = [_bash_entry("python3 -c \"import smtplib; ...\"")] * 4
        self.assertEqual(self._run(entries).returncode, 2)


if __name__ == "__main__":
    unittest.main()
