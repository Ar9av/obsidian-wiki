from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMMAND = 'obsidian-wiki index "$OBSIDIAN_VAULT_PATH" --link-format "$OBSIDIAN_LINK_FORMAT"'
FALLBACK = (
    "If the `obsidian-wiki` executable is unavailable, manually reconcile "
    "`index.md` using the format in `llm-wiki/SKILL.md`."
)
INDEX_WRITING_SKILLS = (
    "claude-history-ingest",
    "codex-history-ingest",
    "copilot-history-ingest",
    "cross-linker",
    "daily-update",
    "hermes-history-ingest",
    "openclaw-history-ingest",
    "pi-history-ingest",
    "tag-taxonomy",
    "wiki-agent",
    "wiki-capture",
    "wiki-dedup",
    "wiki-digest",
    "wiki-import",
    "wiki-ingest",
    "wiki-research",
    "wiki-stage-commit",
    "wiki-synthesize",
    "wiki-update",
)


@pytest.mark.parametrize("skill", INDEX_WRITING_SKILLS)
def test_index_writing_skills_use_deterministic_cli_with_fallback(skill: str) -> None:
    text = (ROOT / ".skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert COMMAND in text, skill
    assert FALLBACK in text, skill
    assert "OBSIDIAN_LINK_FORMAT" in text, skill


def test_llm_wiki_defines_the_deterministic_index_contract() -> None:
    text = (ROOT / ".skills/llm-wiki/SKILL.md").read_text(encoding="utf-8")
    assert "### Deterministic Index Refresh" in text
    assert COMMAND in text
    assert FALLBACK in text
