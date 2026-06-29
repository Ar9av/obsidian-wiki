# Obsidian Wiki — Copilot Context

This project is a **skill-based framework** for building and maintaining an Obsidian knowledge base using AI coding agents. There are no scripts or dependencies — everything is markdown instructions that the agent executes directly.

## Project Overview

- **Purpose:** Build and maintain an Obsidian wiki using the LLM Wiki pattern (Andrej Karpathy).
- **Tech Stack:** Markdown only. No code, no dependencies. The AI agent IS the runtime.
- **Key Config:** Resolve config via `AGENTS.md`: inline `@name` vault override first, then `.env`, then `~/.obsidian-wiki/config`. The resolved config supplies `OBSIDIAN_VAULT_PATH`.
- **Skills:** `.skills/` contains skill folders, each with a `SKILL.md` defining a workflow.

## Key Concepts

- The wiki is a **compiled artifact** — knowledge distilled from raw sources into interconnected pages.
- Every wiki page has YAML frontmatter: `title`, `category`, `tags`, `sources`, `created`, `updated`.
- Pages are connected with Obsidian `[[wikilinks]]`.
- A `.manifest.json` in the vault root tracks all ingested sources for delta-based updates.
- `index.md` and `log.md` must be updated after every operation.

## Skills Reference

| Skill | Folder | Purpose |
|---|---|---|
| Setup | `.skills/wiki-setup/` | Initialize vault structure |
| Ingest | `.skills/wiki-ingest/` | Distill documents into wiki pages, plus any text data — chat exports, logs, transcripts |
| History Router | `.skills/wiki-history-ingest/` | Route `/wiki-history-ingest <claude|codex>` to the right history skill |
| Claude History | `.skills/claude-history-ingest/` | Mine `~/.claude` conversations |
| Codex History | `.skills/codex-history-ingest/` | Mine `~/.codex` sessions and rollout logs |
| Status | `.skills/wiki-status/` | Audit ingestion state and delta |
| Query | `.skills/wiki-query/` | Answer questions from wiki |
| Lint | `.skills/wiki-lint/` | Find broken links, orphans |
| Rebuild | `.skills/wiki-rebuild/` | Archive and rebuild |
| Cross-Linker | `.skills/cross-linker/` | Auto-discover and insert missing wikilinks |
| Tag Taxonomy | `.skills/tag-taxonomy/` | Enforce consistent tag vocabulary |
| LLM Wiki | `.skills/llm-wiki/` | Core architecture pattern |
| Skill Creator | `.skills/skill-creator/` | Create new skills |

## Coding Conventions

- When creating wiki pages, always use YAML frontmatter.
- Use `[[wikilinks]]` syntax for cross-references — NOT markdown links.
- Project-specific knowledge goes in `projects/<name>/`. Global knowledge goes in top-level categories.
- Never modify the `.obsidian/` directory.
