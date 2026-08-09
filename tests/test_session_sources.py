from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from obsidian_wiki import session_sources as ss


def _line(**kwargs) -> str:
    return json.dumps(kwargs)


def _turn(role: str, text, **extra) -> str:
    """A user or assistant envelope line."""
    content = text if role == "user" else [{"type": "text", "text": text}]
    rec = {
        "type": role,
        "message": {"role": role, "content": content},
        "timestamp": extra.pop("timestamp", "2026-07-01T10:00:00.000Z"),
        "cwd": extra.pop("cwd", "/Users/x/projects/app"),
        "gitBranch": extra.pop("gitBranch", "main"),
        "sessionId": extra.pop("sessionId", "sess1"),
    }
    rec.update(extra)
    return json.dumps(rec)


class ReadTranscriptTest(unittest.TestCase):
    """The reader must keep what the human said and drop machine boilerplate.

    Every exclusion here is a real line type seen in a live cache. Tool results
    arrive as user-role lines with list content; subagent traffic is marked
    isSidechain; injected context is isMeta; slash commands and caveats arrive
    as user-role strings wrapped in tags. Counting any of them as a prompt
    poisons both the topic vector and the n_user_prompts stat.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project_dir = self.root / "projects" / "-Users-x-projects-app"
        self.project_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, name: str, lines: list[str]) -> Path:
        path = self.project_dir / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_keeps_real_prompts_and_drops_boilerplate(self) -> None:
        path = self._write("sess1.jsonl", [
            _turn("user", "add telemetry batching to the warden runtime"),
            _turn("assistant", "I will edit telemetry.py"),
            # tool result: user role, list content
            _line(type="user", message={"role": "user", "content": [
                {"type": "tool_result", "content": "ok"}]},
                timestamp="2026-07-01T10:01:00.000Z"),
            # subagent traffic
            _turn("user", "explore the repo", isSidechain=True),
            # injected context
            _turn("user", "<system-reminder>ignore me</system-reminder>", isMeta=True),
            # slash command wrapper
            _turn("user", "<command-name>/clear</command-name>"),
            _turn("user", "now add the retry path", timestamp="2026-07-01T10:05:00.000Z"),
        ])
        doc = ss.read_transcript(path)
        assert doc is not None

        self.assertEqual(doc.n_user_prompts, 2)
        self.assertEqual(doc.fields["first_prompt"],
                         ["add telemetry batching to the warden runtime"])
        self.assertEqual(doc.fields["prompt"], ["now add the retry path"])
        self.assertEqual(doc.fields["assistant"], ["I will edit telemetry.py"])
        # Envelope metadata comes off the first user/assistant line.
        self.assertEqual(doc.cwd, "/Users/x/projects/app")
        self.assertEqual(doc.project, "app")
        self.assertEqual(doc.tier, "full")
        self.assertEqual(doc.start_ts, "2026-07-01T10:00:00.000Z")
        self.assertEqual(doc.end_ts, "2026-07-01T10:05:00.000Z")

    def test_last_ai_title_wins(self) -> None:
        path = self._write("sess1.jsonl", [
            _line(type="ai-title", aiTitle="Early guess", sessionId="sess1"),
            _turn("user", "do the thing"),
            _line(type="ai-title", aiTitle="Warden telemetry batching", sessionId="sess1"),
        ])
        doc = ss.read_transcript(path)
        assert doc is not None
        self.assertEqual(doc.title, "Warden telemetry batching")
        self.assertEqual(doc.title_source, "ai-title")

    def test_title_falls_back_to_last_prompt_then_first_prompt(self) -> None:
        path = self._write("sess2.jsonl", [
            _turn("user", "fix the sprite sheet slicing"),
            _line(type="last-prompt", lastPrompt="fix the sprite sheet", sessionId="sess2"),
        ])
        doc = ss.read_transcript(path)
        assert doc is not None
        self.assertEqual(doc.title_source, "last-prompt")

        # No ai-title and no last-prompt at all -> first prompt.
        path3 = self._write("sess3.jsonl", [_turn("user", "fix the sprite sheet slicing")])
        doc3 = ss.read_transcript(path3)
        assert doc3 is not None
        self.assertEqual(doc3.title_source, "first-prompt")
        self.assertEqual(doc3.title, "fix the sprite sheet slicing")

    def test_pr_links_and_subagents_are_captured(self) -> None:
        path = self._write("sess4.jsonl", [
            _turn("user", "open the PR"),
            _line(type="pr-link", prUrl="https://github.com/acme/widget/pull/12",
                  prRepository="https://github.com/acme/widget.git"),
        ])
        meta_dir = self.project_dir / "sess4" / "subagents"
        meta_dir.mkdir(parents=True)
        (meta_dir / "agent-1.meta.json").write_text(
            json.dumps({"agentType": "Explore", "description": "find the policy signer"}),
            encoding="utf-8")

        doc = ss.read_transcript(path)
        assert doc is not None
        self.assertEqual(doc.pr_links, ["https://github.com/acme/widget/pull/12"])
        self.assertEqual(doc.repos, ["acme/widget"])
        self.assertEqual(len(doc.subagents), 1)
        self.assertIn("find the policy signer", doc.fields["subagent"][0])

    def test_transcript_with_no_turns_is_dropped(self) -> None:
        path = self._write("empty.jsonl", [_line(type="ai-title", aiTitle="nothing")])
        self.assertIsNone(ss.read_transcript(path))

    def test_assistant_blocks_are_capped_and_truncated(self) -> None:
        lines = [_turn("user", "go")]
        lines += [_turn("assistant", "x" * 900) for _ in range(ss.MAX_ASSISTANT_BLOCKS + 10)]
        path = self._write("big.jsonl", lines)
        doc = ss.read_transcript(path)
        assert doc is not None
        self.assertEqual(len(doc.fields["assistant"]), ss.MAX_ASSISTANT_BLOCKS)
        self.assertTrue(all(len(b) <= ss.MAX_ASSISTANT_CHARS for b in doc.fields["assistant"]))


class CollectTest(unittest.TestCase):
    """collect() must cover both tiers and re-read only what changed."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.claude = Path(self.tmp.name) / ".claude"
        proj = self.claude / "projects" / "-Users-x-projects-app"
        proj.mkdir(parents=True)
        (proj / "aaa.jsonl").write_text(
            _turn("user", "add telemetry batching", sessionId="aaa") + "\n", encoding="utf-8")

        # history.jsonl knows about a session whose transcript is gone.
        (self.claude / "history.jsonl").write_text("\n".join([
            json.dumps({"display": "add telemetry batching", "timestamp": 1785000000000,
                        "project": "/Users/x/projects/app", "sessionId": "aaa"}),
            json.dumps({"display": "port the sprite slicer to webgl", "timestamp": 1784000000000,
                        "project": "/Users/x/projects/game", "sessionId": "ghost"}),
            json.dumps({"display": "/clear", "timestamp": 1784000001000,
                        "project": "/Users/x/projects/game", "sessionId": "ghost"}),
        ]) + "\n", encoding="utf-8")

        self.bookmarks = Path(self.tmp.name) / "bookmarks.json"
        self.bookmarks.write_text(json.dumps([
            {"id": "bm1", "tool": "claude-code", "sessionId": "aaa",
             "title": "Telemetry batching", "tags": ["observability"], "note": "the good one",
             "createdAt": "2026-07-01T00:00:00-0700"},
        ]), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_collects_full_and_thin_tiers(self) -> None:
        docs, info = ss.collect(self.claude, bookmarks_path=self.bookmarks)
        by_id = {d.session_id: d for d in docs}

        self.assertEqual(by_id["aaa"].tier, "full")
        self.assertEqual(by_id["ghost"].tier, "thin")
        self.assertIsNone(by_id["ghost"].transcript)
        # The thin node keeps its prompt but drops the slash command.
        self.assertEqual(by_id["ghost"].fields["first_prompt"],
                         ["port the sprite slicer to webgl"])
        self.assertNotIn("prompt", by_id["ghost"].fields)
        self.assertEqual(by_id["ghost"].project, "game")
        self.assertEqual(info["thin"], 1)

    def test_bookmark_is_attached_as_a_weighted_field(self) -> None:
        docs, _ = ss.collect(self.claude, bookmarks_path=self.bookmarks)
        doc = next(d for d in docs if d.session_id == "aaa")
        assert doc.bookmark is not None
        self.assertEqual(doc.bookmark["tags"], ["observability"])
        self.assertIn("observability", doc.fields["bookmark"][0])

    def test_second_run_re_reads_nothing(self) -> None:
        docs1, info1 = ss.collect(self.claude, bookmarks_path=self.bookmarks)
        self.assertEqual(len(docs1), 2)

        docs2, info2 = ss.collect(self.claude, bookmarks_path=self.bookmarks,
                                  state=info1["state"])
        self.assertEqual(docs2, [])
        self.assertEqual(sorted(info2["unchanged"]), ["aaa", "ghost"])

    def test_touching_one_transcript_re_reads_exactly_that_one(self) -> None:
        _, info1 = ss.collect(self.claude, bookmarks_path=self.bookmarks)
        path = self.claude / "projects" / "-Users-x-projects-app" / "aaa.jsonl"
        path.write_text(
            _turn("user", "add telemetry batching and retries", sessionId="aaa") + "\n",
            encoding="utf-8")

        docs2, info2 = ss.collect(self.claude, bookmarks_path=self.bookmarks,
                                  state=info1["state"])
        self.assertEqual([d.session_id for d in docs2], ["aaa"])
        self.assertEqual(info2["unchanged"], ["ghost"])

    def test_missing_claude_dir_yields_nothing_rather_than_raising(self) -> None:
        docs, info = ss.collect(Path(self.tmp.name) / "nope")
        self.assertEqual(docs, [])
        self.assertEqual(info["full_on_disk"], 0)


if __name__ == "__main__":
    unittest.main()
