"""Tests for _meta/voice.md: parsing the owner's voice file and the banned-words check."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from obsidian_wiki import voice as vc

ROOT = Path(__file__).resolve().parents[1]

VOICE = """---
title: Voice
category: _meta
---
# Voice

Intro text mentioning leverage is not a rule.

## Never use

<!-- One per bullet.
- commented-out
-->
- leverage -> use
- "delve"
- `game changer`
- —
- Leverage
- utilize => use

## Posts I love

- [[my-best-post]]
- "Ship it boring."

## Posts I hate

- [[that-viral-thread]]

## Notes on tone

Short sentences. No hashtags.
"""


def _vault(tmp_path: Path, text: str = VOICE) -> Path:
    (tmp_path / "_meta").mkdir(parents=True, exist_ok=True)
    (tmp_path / vc.VOICE_REL).write_text(text, encoding="utf-8")
    return tmp_path


def _cli(*argv: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, CI="true", PYTHONPATH=str(ROOT))
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "voice", *argv],
        input=stdin, capture_output=True, text=True, cwd=ROOT, env=env,
    )


def test_parse_sections_by_heading() -> None:
    voice = vc.parse_voice(VOICE)
    assert [(b.phrase, b.replacement) for b in voice.banned] == [
        ("leverage", "use"),
        ("delve", ""),
        ("game changer", ""),
        ("—", ""),
        ("utilize", "use"),
    ]
    assert voice.love == ["[[my-best-post]]", '"Ship it boring."']
    assert voice.hate == ["[[that-viral-thread]]"]
    assert "No hashtags." in voice.notes


def test_heading_synonyms() -> None:
    voice = vc.parse_voice(
        "## Words I never use\n- synergy\n## Best examples\n- a\n## Posts I dislike\n- b\n"
    )
    assert [b.phrase for b in voice.banned] == ["synergy"]
    assert voice.love == ["a"] and voice.hate == ["b"]


def test_template_parses_empty() -> None:
    voice = vc.parse_voice(vc.TEMPLATE.format(created="2026-11-15"))
    assert voice.banned == [] and voice.love == [] and voice.hate == []


def test_check_matches_whole_words_case_insensitively() -> None:
    voice = vc.parse_voice(VOICE)
    findings = vc.check_text("We leverage AI. Leveraged gains. LEVERAGE!", voice)
    assert [(f["column"], f["match"]) for f in findings] == [(4, "leverage"), (34, "LEVERAGE")]
    assert findings[0]["replacement"] == "use"


def test_check_phrases_span_any_whitespace_and_punctuation_is_literal() -> None:
    voice = vc.parse_voice(VOICE)
    findings = vc.check_text("A real game\tchanger—honestly.", voice)
    assert [f["phrase"] for f in findings] == ["game changer", "—"]


def test_check_skips_frontmatter_code_and_links() -> None:
    voice = vc.parse_voice(VOICE)
    draft = (
        "---\ntitle: How we leverage things\n---\n"
        "Use `leverage` in code. See [[leverage-page]] or [x](https://e.com/leverage).\n"
        "```\nleverage\n```\n"
        "Time to delve.\n"
    )
    findings = vc.check_text(draft, voice)
    assert [(f["line"], f["phrase"]) for f in findings] == [(8, "delve")]


def test_no_voice_file_means_no_rules(tmp_path: Path) -> None:
    result = vc.check_file(tmp_path, "We leverage AI.")
    assert result["banned"] == 0 and result["findings"] == []


def test_cli_check_exit_codes(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    draft = tmp_path / "post.md"
    draft.write_text("We leverage AI.\n", encoding="utf-8")

    flagged = _cli("check", str(draft), "--vault", str(vault))
    assert flagged.returncode == 2
    assert "line 1:4: 'leverage' is on the never-use list (try: use)" in flagged.stdout

    clean = _cli("check", "-", "--vault", str(vault), "--json", stdin="We use AI.\n")
    assert clean.returncode == 0
    assert json.loads(clean.stdout)["findings"] == []

    missing = _cli("check", str(tmp_path / "nope.md"), "--vault", str(vault))
    assert missing.returncode == 1


def test_cli_show_json(tmp_path: Path) -> None:
    result = _cli("show", "--json", "--vault", str(_vault(tmp_path)))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["banned"][0] == {"phrase": "leverage", "replacement": "use"}
    assert payload["love"] == ["[[my-best-post]]", '"Ship it boring."']


def test_setup_seeds_voice_once_and_never_overwrites(tmp_path: Path) -> None:
    from obsidian_wiki.cli import scaffold_vault

    scaffold_vault(tmp_path)
    seeded = (tmp_path / vc.VOICE_REL).read_text(encoding="utf-8")
    assert seeded.startswith("---\ntitle: Voice\n")
    assert "## Never use" in seeded

    (tmp_path / vc.VOICE_REL).write_text(VOICE, encoding="utf-8")
    scaffold_vault(tmp_path)
    assert (tmp_path / vc.VOICE_REL).read_text(encoding="utf-8") == VOICE
