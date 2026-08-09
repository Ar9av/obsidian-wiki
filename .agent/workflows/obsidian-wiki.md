---
name: obsidian-wiki
description: Obsidian wiki workflows — query, update, ingest, lint, status.
commands:
  - name: wiki-context-pack
    description: Compile a bounded vault context slice for a downstream agent.
    skill: .skills/wiki-context-pack/SKILL.md
  - name: wiki-query
    description: Answer questions from the compiled Obsidian wiki with [[wikilink]] citations.
    skill: .skills/wiki-query/SKILL.md
  - name: wiki-update
    description: Sync the current project's knowledge into the Obsidian wiki.
    skill: .skills/wiki-update/SKILL.md
  - name: wiki-ingest
    description: Ingest documents into the Obsidian wiki.
    skill: .skills/wiki-ingest/SKILL.md
  - name: wiki-status
    description: Show what's been ingested, what's pending, and the delta.
    skill: .skills/wiki-status/SKILL.md
  - name: wiki-lint
    description: Audit the wiki for orphans, broken links, stale content.
    skill: .skills/wiki-lint/SKILL.md
---

# Obsidian Wiki — Workflow Registry

Each command above maps to a `SKILL.md` in `.skills/`. When a user invokes one
of these commands, read the mapped skill file and follow its instructions
exactly. The skills handle vault path resolution, manifest tracking, and
`[[wikilink]]` connectivity on their own.

For the full routing table (all 15+ skills), see `AGENTS.md` at the repo root.
