"""Behavioral tests for the Stop hook's trigger logic.

Runs ``wiki-stop-capture.sh`` against synthetic transcripts and asserts on the
exit code contract (0 = silent, 2 = nudge on stderr). Covers the read-only
session exemption: a session with zero file edits whose shell commands are all
provably read-only must not nudge, while any file edit — or shell activity the
classifier can't prove read-only — keeps the pre-exemption behavior.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
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


def _tool_entry(name, tool_input=None):
    return {
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": tool_input or {}}],
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

    def _sentinel(self, session_id):
        return self.tmp / f"wiki-stop-capture-{session_id}.done"

    def _age_sentinel(self, session_id, seconds):
        old = time.time() - seconds
        os.utime(self._sentinel(session_id), (old, old))

    def _run(self, entries, session_id=None, stop_hook_active=False, extra_env=None):
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
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", "TMPDIR": str(self.tmp), **(extra_env or {})},
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

    def test_task_subagent_disables_exemption(self):
        entries = _READONLY_BASH + [
            _tool_entry("Task", {"subagent_type": "general-purpose", "prompt": "fix the bug"})
        ]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_readonly_agent_types_keep_exemption(self):
        entries = _READONLY_BASH + [
            _tool_entry("Task", {"subagent_type": "Explore", "prompt": "find the config"}),
            _tool_entry("Task", {"subagent_type": "Plan", "prompt": "plan the change"}),
        ]
        self.assertEqual(self._run(entries).returncode, 0)

    def test_enter_worktree_disables_exemption(self):
        entries = _READONLY_BASH + [_tool_entry("EnterWorktree")]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_explain_analyze_dml_disables_exemption(self):
        entries = _READONLY_BASH + [
            _tool_entry(
                "mcp__neon__explain_sql_statement",
                {"analyze": True, "sql": "DELETE FROM users"},
            )
        ]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_explain_plain_select_keeps_exemption(self):
        entries = _READONLY_BASH + [
            _tool_entry("mcp__neon__explain_sql_statement", {"sql": "SELECT count(*) FROM users"})
        ]
        self.assertEqual(self._run(entries).returncode, 0)

    def test_prepare_named_tool_disables_exemption(self):
        entries = _READONLY_BASH + [_tool_entry("mcp__neon__prepare_query_tuning")]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_resolve_named_tool_disables_exemption(self):
        entries = _READONLY_BASH + [
            _tool_entry("mcp__codex_apps__github_resolve_review_thread")
        ]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_double_quote_backslash_parity(self):
        # "a\\" — the two backslashes escape each other, the quote CLOSES,
        # and the rm after the semicolon runs unquoted.
        entries = [_bash_entry('echo "a\\\\" ; rm -rf ./victim')] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_curl_config_and_quote_count_as_mutating(self):
        entries = [
            _bash_entry("printf 'request = \"DELETE\"\\n' | curl --config - http://h/items/42"),
            _bash_entry("curl -Q 'DELE important.txt' ftp://server/"),
            _bash_entry("curl -sK curlrc http://h/"),
            _bash_entry("curl --quote 'DELE x' ftp://server/"),
        ]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_python_sqlite_execute_counts_as_mutating(self):
        entries = [
            _bash_entry(
                "python3 -c \"import sqlite3; sqlite3.connect('app.db', isolation_level=None)"
                ".execute('delete from users')\""
            )
        ] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_python_os_alias_counts_as_mutating(self):
        entries = [_bash_entry("python3 -c \"import os as x; x.remove('/tmp/victim')\"")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_python_path_open_write_counts_as_mutating(self):
        entries = [
            _bash_entry(
                "python3 -c \"from pathlib import Path; Path('/tmp/out').open('w').close()\""
            )
        ] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_sudo_date_positional_counts_as_mutating(self):
        entries = [_bash_entry("sudo date 010100002025")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_date_readonly_forms_stay_readonly(self):
        entries = [
            _bash_entry("date +%Y-%m-%d"),
            _bash_entry("date -u"),
            _bash_entry("date -j -f '%Y' '2026' +%s"),
            _bash_entry("date"),
        ]
        self.assertEqual(self._run(entries).returncode, 0)

    def test_git_upload_pack_counts_as_mutating(self):
        entries = [
            _bash_entry("git ls-remote --upload-pack='touch /tmp/pwn' ssh://host/repo")
        ] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_awk_variable_targets_count_as_mutating(self):
        entries = [
            _bash_entry("awk 'BEGIN { c=\"rm -rf /tmp/victim\"; print | c; close(c) }'"),
            _bash_entry("awk 'BEGIN { f=\"/tmp/out\"; print \"x\" > f; close(f) }'"),
            _bash_entry("awk 'BEGIN { c=\"rm x\"; print | c }'"),
            _bash_entry("awk '{ print > outfile }' outfile=/tmp/o data.txt"),
        ]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_awk_numeric_comparison_stays_readonly(self):
        entries = [_bash_entry("awk '$3 > 100 { print $1 }' data.txt")] * 4
        self.assertEqual(self._run(entries).returncode, 0)

    def test_sed_alternate_delimiter_write_counts_as_mutating(self):
        entries = [_bash_entry("sed 's#a#b#w /tmp/out' input.txt")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_xxd_uniq_stdin_output_counts_as_mutating(self):
        entries = [
            _bash_entry("printf 41 | xxd -r -p - /tmp/out.bin"),
            _bash_entry("printf 'x\\nx\\n' | uniq - /tmp/out.txt"),
            _bash_entry("printf 42 | xxd -r -p - /tmp/out2.bin"),
            _bash_entry("printf 'y\\ny\\n' | uniq - /tmp/out2.txt"),
        ]
        self.assertEqual(self._run(entries).returncode, 2)

    def test_less_log_file_counts_as_mutating(self):
        entries = [_bash_entry("printf x | less -F -o /tmp/log")] * 4
        self.assertEqual(self._run(entries).returncode, 2)

    def test_rearm_after_age_and_new_edits(self):
        first = self._run([_edit_entry()] * 5, session_id="long")
        self.assertEqual(first.returncode, 2)
        self._age_sentinel("long", 7 * 3600)
        second = self._run([_edit_entry()] * 20, session_id="long")
        self.assertEqual(second.returncode, 2)
        self.assertIn("20 file edit(s)", second.stderr)

    def test_no_rearm_while_sentinel_is_young(self):
        first = self._run([_edit_entry()] * 5, session_id="young")
        self.assertEqual(first.returncode, 2)
        # Plenty of new edits, but the nudge was moments ago.
        second = self._run([_edit_entry()] * 40, session_id="young")
        self.assertEqual(second.returncode, 0)

    def test_no_rearm_without_enough_new_edits(self):
        first = self._run([_edit_entry()] * 5, session_id="idle")
        self.assertEqual(first.returncode, 2)
        self._age_sentinel("idle", 7 * 3600)
        # Only 3 edits since the nudge that recorded 5.
        second = self._run([_edit_entry()] * 8, session_id="idle")
        self.assertEqual(second.returncode, 0)
        # The sentinel must survive, still holding the original count.
        self.assertEqual((self._sentinel("idle") / "edits").read_text(), "5")

    def test_rearm_updates_stored_count_and_rests_again(self):
        first = self._run([_edit_entry()] * 5, session_id="cycle")
        self.assertEqual(first.returncode, 2)
        self._age_sentinel("cycle", 7 * 3600)
        second = self._run([_edit_entry()] * 20, session_id="cycle")
        self.assertEqual(second.returncode, 2)
        self.assertEqual((self._sentinel("cycle") / "edits").read_text(), "20")
        # Fresh sentinel again: more edits right away stay silent.
        third = self._run([_edit_entry()] * 40, session_id="cycle")
        self.assertEqual(third.returncode, 0)

    def test_pre_feature_sentinel_rearms_from_zero(self):
        # A sentinel claimed before the re-arm feature has no edits file:
        # the whole current count is the delta.
        self._sentinel("legacy").mkdir()
        self._age_sentinel("legacy", 7 * 3600)
        result = self._run([_edit_entry()] * 12, session_id="legacy")
        self.assertEqual(result.returncode, 2)

    def test_concurrent_rearm_produces_exactly_one_nudge(self):
        # Duplicate hook registration fires two invocations per stop. With an
        # expired sentinel both pass the age check; the mv claim plus the
        # young-retire guard must let exactly one of them re-nudge — the
        # loser either loses the mv or grabs the winner's FRESH sentinel,
        # sees it is young, restores it, and stands down.
        #
        # TRUE concurrency matters: the hook's first statement is
        # INPUT=$(cat), so feeding stdin through sequential communicate()
        # calls would hold the second process at that read until the first
        # had fully exited — serializing the bodies and never exercising
        # the race. Both processes therefore get stdin from a pre-written
        # file and run the whole body simultaneously; the transcript is
        # large so the parse phase gives a wide overlap window between the
        # age check and the claim.
        transcript = self.tmp / "transcript.jsonl"
        transcript.write_text(
            "".join(json.dumps(_edit_entry()) + "\n" for _ in range(200))
        )
        raced_rounds = 0
        for round_no in range(10):
            sid = f"race{round_no}"
            sentinel = self._sentinel(sid)
            sentinel.mkdir()
            (sentinel / "edits").write_text("0")
            self._age_sentinel(sid, 7 * 3600)
            payload_file = self.tmp / f"payload{round_no}.json"
            payload_file.write_text(
                json.dumps({"session_id": sid, "transcript_path": str(transcript)})
            )
            env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "TMPDIR": str(self.tmp)}
            # bash -x: the xtrace on stderr is evidence of WHICH path each
            # process took, asserted on below — outcome checks alone cannot
            # distinguish a genuine race from accidental serialization.
            procs = []
            for _ in range(2):
                with payload_file.open() as stdin_file:
                    procs.append(
                        subprocess.Popen(
                            ["bash", "-x", str(HOOK)],
                            stdin=stdin_file,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            env=env,
                        )
                    )
            codes = []
            traces = []
            for p in procs:
                _, stderr = p.communicate()
                codes.append(p.returncode)
                traces.append(stderr)
            self.assertEqual(
                sorted(codes), [0, 2], f"round {round_no}: exactly one nudge, got {codes}"
            )
            self.assertTrue(sentinel.exists(), f"round {round_no}: sentinel must survive")
            # State invariant: whichever invocation ends up owning the
            # sentinel, the edit count must be present — the winner writes
            # it, and a restorer repairs it if it grabbed the sentinel in
            # the winner's mkdir-to-write gap. Without it, the next re-arm
            # would compute its delta from zero and fire early.
            self.assertEqual(
                (sentinel / "edits").read_text(),
                "200",
                f"round {round_no}: sentinel lost its edit-count state",
            )
            # A process that reached the claim phase shows an mv or mkdir on
            # the sentinel path in its xtrace; a serialized loser instead
            # exits at the top age check and never touches the sentinel.
            marker = f"wiki-stop-capture-{sid}.done"
            if all(
                any(
                    marker in line and ("+ mv " in line or "+ mkdir " in line)
                    for line in trace.splitlines()
                )
                for trace in traces
            ):
                raced_rounds += 1
        # The race path must demonstrably execute: in a genuinely concurrent
        # round BOTH processes pass the age check and reach the claim.
        # Requiring 3 of 10 rounds tolerates a loaded machine occasionally
        # serializing a round (unloaded runs hit 10/10) while still failing
        # loudly if the harness ever degrades back to sequential execution.
        self.assertGreaterEqual(
            raced_rounds,
            3,
            f"only {raced_rounds}/10 rounds raced — the test is not exercising "
            "the concurrent claim path",
        )

    def test_rearm_env_knobs_override_defaults(self):
        first = self._run([_edit_entry()] * 5, session_id="knobs")
        self.assertEqual(first.returncode, 2)
        # Zero cool-down and a 1-edit delta: the very next stop re-fires.
        second = self._run(
            [_edit_entry()] * 6,
            session_id="knobs",
            extra_env={"WIKI_STOP_REARM_SECONDS": "0", "WIKI_STOP_REARM_EDITS": "1"},
        )
        self.assertEqual(second.returncode, 2)


if __name__ == "__main__":
    unittest.main()
