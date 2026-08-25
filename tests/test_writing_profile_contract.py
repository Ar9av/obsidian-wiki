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


def test_llm_wiki_defines_exact_precedence_and_inheritance() -> None:
    body = (ROOT / ".skills" / "llm-wiki" / "SKILL.md").read_text()
    assert (
        "framework invariants > current task/skill requirements > current project "
        "`AGENTS.md` > vault `AGENTS.md` > global `WRITING.md`"
    ) in body
    assert "Unspecified project and vault rules are inherited" in body
    assert "more specific same-topic rules win" in body


def test_llm_wiki_scopes_frontmatter_and_structured_content() -> None:
    body = (ROOT / ".skills" / "llm-wiki" / "SKILL.md").read_text()
    assert "natural-language title and summary values in YAML frontmatter" in body
    assert (
        "cannot alter YAML syntax, required keys, structure, types, or machine-generated fields"
    ) in body
    assert "JSON, structured logs, and pass-through content remain unchanged" in body


def test_wiki_setup_resolves_global_path_and_template_without_repo_config() -> None:
    body = (ROOT / ".skills" / "wiki-setup" / "SKILL.md").read_text()
    assert 'GLOBAL_CONFIG_DIR="$(obsidian_wiki_config_dir)"' in body
    assert 'SKILL_FILE="<absolute path of this loaded wiki-setup/SKILL.md>"' in body
    assert 'if [ -n "${OBSIDIAN_WIKI_REPO:-}" ]; then' in body
    assert "${SKILL_DIR%/skills/wiki-setup}" in body
    assert "${SKILL_DIR%/.skills/wiki-setup}" in body
    assert "/skills/llm-wiki/references/WRITING.md" in body
    assert "/.skills/llm-wiki/references/WRITING.md" in body


def test_wiki_capture_applies_profile_before_every_mode() -> None:
    body = (ROOT / ".skills" / "wiki-capture" / "SKILL.md").read_text()
    hook = body.index("**Writing profile:**")
    for heading in (
        "## Quick Mode (`--quick`)",
        "## Correction Mode (`--correction`)",
        "## Full Mode",
    ):
        assert hook < body.index(heading), heading


def test_every_current_prose_writer_references_the_contract() -> None:
    for skill in REQUIRED_SKILLS:
        body = (ROOT / ".skills" / skill / "SKILL.md").read_text()
        assert CONTRACT in body, skill
        assert "WRITING.md" in body, skill
