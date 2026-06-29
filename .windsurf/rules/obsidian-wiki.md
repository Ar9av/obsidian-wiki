---
name: "Obsidian Wiki"
activation: "always-on"
---

# Obsidian Wiki — Agent Context

This project is a **skill-based framework** for building and maintaining an Obsidian knowledge base.

## Quick Orientation

1. Resolve config via `AGENTS.md`: honor an inline `@name` vault override first, then `.env`, then `~/.obsidian-wiki/config`. This gives `OBSIDIAN_VAULT_PATH` — where the wiki lives.
2. Read `.manifest.json` at the vault root to see what's already been ingested.
3. Skills are in `.skills/` (also at `.windsurf/skills/`). Each subfolder has a `SKILL.md`.

## When to Use Skills

| User says something like… | Read this skill |
|---|---|
| "set up my wiki" / "initialize" | `.skills/wiki-setup/SKILL.md` |
| "ingest" / "add this to the wiki" / "process this export" / "ingest this data" | `.skills/wiki-ingest/SKILL.md` |
| "/wiki-history-ingest claude" / "/wiki-history-ingest codex" / "/wiki-history-ingest pi" | `.skills/wiki-history-ingest/SKILL.md` |
| "import my Claude history" | `.skills/claude-history-ingest/SKILL.md` |
| "import my Codex history" | `.skills/codex-history-ingest/SKILL.md` |
| "import my Pi history" | `.skills/pi-history-ingest/SKILL.md` |
| "what's the status" / "show the delta" | `.skills/wiki-status/SKILL.md` |
| "what do I know about X" / any question | `.skills/wiki-query/SKILL.md` |
| "audit" / "lint" / "find broken links" | `.skills/wiki-lint/SKILL.md` |
| "rebuild" / "start over" / "archive" | `.skills/wiki-rebuild/SKILL.md` |
| "link my pages" / "cross-reference" | `.skills/cross-linker/SKILL.md` |
| "fix my tags" / "normalize tags" | `.skills/tag-taxonomy/SKILL.md` |
| "create a new skill" | `.skills/skill-creator/SKILL.md` |

## Key Rules

- **Compile, don't retrieve.** Update existing pages, don't just append.
- **Always update `.manifest.json`** after ingesting.
- **Always update `index.md` and `log.md`** after any operation.
- **Use `[[wikilinks]]`** to connect related pages.
- **Frontmatter is required** on every wiki page.
