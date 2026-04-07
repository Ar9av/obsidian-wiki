# Obsidian Wiki — Agent Context

This project is a **skill-based framework** for building and maintaining an Obsidian knowledge base. There are no scripts or dependencies — everything is markdown instructions that you (the agent) execute directly.

## Quick Orientation

1. Read `.env` for `OBSIDIAN_VAULT_PATH` — this is where the wiki lives.
2. Read `.manifest.json` at the vault root to see what's already been ingested.
3. Skills are in `.skills/` (symlinked to `.claude/skills/`, `~/.gemini/antigravity/skills/`, and `~/.codex/skills/` for global access). Each subfolder has a `SKILL.md`.

## When to Use Skills

| User says something like… | Read this skill |
|---|---|
| "set up my wiki" / "initialize" | `.skills/wiki-setup/SKILL.md` |
| "ingest" / "add this to the wiki" / "process these docs" | `.skills/wiki-ingest/SKILL.md` |
| "import my Claude history" / "mine my conversations" | `.skills/claude-history-ingest/SKILL.md` |
| "process this export" / "ingest this data" / logs, transcripts | `.skills/data-ingest/SKILL.md` |
| "what's the status" / "what's been ingested" / "show the delta" | `.skills/wiki-status/SKILL.md` |
| "wiki insights" / "what's central" / "show me the hubs" / "wiki structure" | `.skills/wiki-status/SKILL.md` (insights mode) |
| "what do I know about X" / "find info on Y" / any question | `.skills/wiki-query/SKILL.md` |
| "audit" / "lint" / "find broken links" / "wiki health" | `.skills/wiki-lint/SKILL.md` |
| "rebuild" / "start over" / "archive" / "restore" | `.skills/wiki-rebuild/SKILL.md` |
| "link my pages" / "cross-reference" / "connect my wiki" | `.skills/cross-linker/SKILL.md` |
| "fix my tags" / "normalize tags" / "tag audit" | `.skills/tag-taxonomy/SKILL.md` |
| "update wiki" / "sync to wiki" / "save this to my wiki" | `.skills/wiki-update/SKILL.md` |
| "create a new skill" | `.skills/skill-creator/SKILL.md` |

## Key Rules

- **Compile, don't retrieve.** The wiki is pre-compiled knowledge. Update existing pages, don't just append.
- **Always update `.manifest.json`** after ingesting — it tracks what's been processed.
- **Always update `index.md` and `log.md`** after any operation.
- **Use `[[wikilinks]]`** to connect related pages. This is an Obsidian vault.
- **Frontmatter is required** on every wiki page: title, category, tags, sources, created, updated.

## Architecture Reference

For the full pattern (three-layer architecture, page templates, project org), read `.skills/llm-wiki/SKILL.md`.
