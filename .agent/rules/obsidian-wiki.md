---
alwaysApply: true
description: Obsidian Wiki skill-based framework — routing, conventions, and core rules.
---

# Obsidian Wiki — Agent Context

This project is a **skill-based framework** for building and maintaining an Obsidian knowledge base.

## Quick Orientation

1. Read `~/.obsidian-wiki/config` (or `.env` in this repo) for `OBSIDIAN_VAULT_PATH` — this is where the wiki lives.
2. Read `.manifest.json` at the vault root to see what's already been ingested.
3. Skills are in `.skills/` (also at `.agents/skills/`). Each subfolder has a `SKILL.md`.

## When to Use Skills

| User says something like… | Read this skill |
|---|---|
| "set up my wiki" / "initialize" | `wiki-setup` |
| "ingest" / "add this to the wiki" | `wiki-ingest` |
| "import my Claude history" | `claude-history-ingest` |
| "import my Codex history" | `codex-history-ingest` |
| "import my Hermes history" | `hermes-history-ingest` |
| "import my OpenClaw history" | `openclaw-history-ingest` |
| "import my Pi history" | `pi-history-ingest` |
| "process this export" / "ingest this data" | `data-ingest` |
| "what's the status" / "show the delta" | `wiki-status` |
| "what do I know about X" | `wiki-query` |
| "audit" / "lint" / "find broken links" | `wiki-lint` |
| "rebuild" / "archive" / "restore" | `wiki-rebuild` |
| "link my pages" / "cross-reference" | `cross-linker` |
| "fix my tags" | `tag-taxonomy` |
| "update wiki" / "sync to wiki" | `wiki-update` |
| "export wiki" / "export graph" | `wiki-export` |

## Core Rules

- **Compile, don't retrieve** — update existing pages, don't append or duplicate.
- **Track everything** — update `.manifest.json`, `index.md`, and `log.md` after every operation.
- **Connect with `[[wikilinks]]`** — every page should link to related pages.
- **Frontmatter required** — every page needs `title`, `category`, `tags`, `sources`, `created`, `updated`.

For full context, read `AGENTS.md` at the repo root.
