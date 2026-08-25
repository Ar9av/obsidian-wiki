from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "Writing Profile Resolution"
REQUIRED_SKILLS = (
    "wiki-capture",
    "wiki-ingest",
    "wiki-update",
    "wiki-research",
    "wiki-synthesize",
    "wiki-agent",
    "wiki-narrate",
    "wiki-digest",
    "wiki-dashboard",
    "wiki-status",
    "wiki-lint",
    "wiki-import",
    "wiki-dedup",
    "cross-linker",
    "claude-history-ingest",
    "codex-history-ingest",
    "copilot-history-ingest",
    "hermes-history-ingest",
    "openclaw-history-ingest",
    "pi-history-ingest",
)


def test_llm_wiki_defines_writing_profile_resolution() -> None:
    body = (ROOT / ".skills" / "llm-wiki" / "SKILL.md").read_text()
    assert CONTRACT in body
    assert "WRITING.md" in body
    assert "AGENTS.md" in body


def test_every_current_prose_writer_references_the_contract() -> None:
    for skill in REQUIRED_SKILLS:
        body = (ROOT / ".skills" / skill / "SKILL.md").read_text()
        assert CONTRACT in body, skill
        assert "WRITING.md" in body, skill
