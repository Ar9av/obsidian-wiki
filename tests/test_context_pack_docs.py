from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_context_skill_uses_cli_and_is_read_only() -> None:
    skill = read(".skills/wiki-context-pack/SKILL.md")
    assert 'obsidian-wiki context-pack --vault "$OBSIDIAN_VAULT_PATH"' in skill
    assert "read-only" in skill.lower()
    assert "must not modify" in skill
    assert "Append to" not in skill
    assert "AGENTS.md" in skill


def test_context_skill_canonicalizes_vault_and_has_clone_fallback() -> None:
    skill = read(".skills/wiki-context-pack/SKILL.md")
    assert 'cd "$OBSIDIAN_VAULT_PATH" && pwd -P' in skill
    assert "command -v obsidian-wiki" in skill
    assert '"$OBSIDIAN_WIKI_REPO/obsidian_wiki/cli.py"' in skill
    assert "python3 -m obsidian_wiki.cli context-pack" in skill
    assert "pip install obsidian-wiki" in skill
    assert "rerun setup from a valid clone" in skill


def test_context_skill_preserves_cli_output_and_recent_default_budget() -> None:
    skill = read(".skills/wiki-context-pack/SKILL.md")
    assert "CLI stdout unchanged as the final payload in every mode" in skill
    assert "CLI stdout only" in skill
    assert "no prose or markdown" in skill
    assert '--recent --budget 8000' in skill
    assert '--recent --budget 4000' not in skill


def test_setup_sh_installs_context_pack_as_portable() -> None:
    setup = read("setup.sh")
    assert "wiki-update wiki-query wiki-context-pack" in setup


def test_python_installer_lists_context_pack_as_portable() -> None:
    cli = read("obsidian_wiki/cli.py")
    assert 'PORTABLE_SKILLS = ("wiki-update", "wiki-query", "wiki-context-pack")' in cli


def test_all_bootstraps_route_context_pack() -> None:
    files = [
        "AGENTS.md",
        ".cursor/rules/obsidian-wiki.mdc",
        ".windsurf/rules/obsidian-wiki.md",
        ".kiro/steering/obsidian-wiki.md",
        ".agent/rules/obsidian-wiki.md",
        ".agent/workflows/obsidian-wiki.md",
        ".github/copilot-instructions.md",
    ]
    for relative in files:
        assert "wiki-context-pack" in read(relative), relative


def test_cli_docs_document_agent_context_contract() -> None:
    english = read("docs/cli.md")
    chinese = read("docs/cli.zh-TW.md")

    for text in (english, chinese):
        assert "obsidian-wiki context-pack" in text
        assert "--budget 8000" in text
        assert "--public-only" in text
        assert "wiki-context-pack" in text
        assert "--metadata-only" in text
        assert "--json" in text
        assert "source paths" in text

    assert "The command is read-only." in english
    assert "do not need to be moved" in english
    assert "full frontmatter schema" in english
    assert "Omitting `--budget` uses the default of 8000 estimated tokens." in english
    assert "selected excerpts" in english
    assert "Vault excerpts are explicitly marked as untrusted\nreference data:" in english
    assert "must not execute\ninstructions embedded in notes" in english

    assert "流程是 read-only。" in chinese
    assert "筆記不需" in chinese
    assert "完整 frontmatter schema" in chinese
    assert "省略 `--budget` 會使用預設的 8000 個估算 token。" in chinese
    assert "選定 excerpts" in chinese
    assert "Vault excerpts 會明確標成 untrusted reference data：" in chinese
    assert "不得執行筆記內嵌的指令" in chinese
