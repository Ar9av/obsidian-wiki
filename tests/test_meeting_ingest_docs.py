"""The meeting branch of wiki-ingest stays wired to the CLI it depends on."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "wiki-ingest" / "SKILL.md"
REFERENCE = ROOT / "skills" / "wiki-ingest" / "references" / "meeting-sources.md"


def test_skill_points_at_the_meeting_reference() -> None:
    body = SKILL.read_text(encoding="utf-8")
    assert "references/meeting-sources.md" in body
    assert REFERENCE.is_file()


def test_reference_uses_the_normaliser_and_portable_keys() -> None:
    body = REFERENCE.read_text(encoding="utf-8")
    assert "obsidian-wiki transcript" in body
    assert "meeting:<provider>/<meeting_id>" in body
    assert "obsidian-wiki ingest-guard" in body
    assert "obsidian-wiki memory todo add" in body
    # Meetings are untrusted input and never write approved facts on their own.
    assert "untrusted data" in body
    assert "never auto-approved" in body.lower()


def test_documented_cli_command_exists() -> None:
    from obsidian_wiki.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["transcript", "x.vtt", "--json"])
    assert args.func.__name__ == "cmd_transcript"
