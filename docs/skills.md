# Skills Reference

Everything lives in [`.skills/`](../.skills/). Each skill is a markdown file the agent reads when your request matches its description — there's no runtime, no plugin system, no registration step.

Slash commands (`/skill-name`) work in Claude Code, Cursor, Windsurf, and most CLI agents. Everywhere else, just describe what you want.

## Setup & vaults

| Skill | What it does | Slash command |
|---|---|---|
| `wiki-setup` | Initialize the vault structure, index, log, and Obsidian config | `/wiki-setup` |
| `wiki-switch` | Manage multiple named vault profiles; switch the active one | `/wiki-switch <name>` |
| `daily-update` | Daily maintenance cycle — source freshness, index rebuild, hot cache | `/daily-update` |

## Feeding the brain

| Skill | What it does | Slash command |
|---|---|---|
| `wiki-ingest` | The catch-all. Distills documents, PDFs, chat exports, logs, transcripts, images, and URLs into wiki pages | `/wiki-ingest` |
| `wiki-capture` | Save the current conversation as a wiki note; `--quick` stages findings to `_raw/` in under 60 seconds | `/wiki-capture` |
| `wiki-update` | Sync the current project's knowledge into the vault — works from any repo | `/wiki-update` |
| `wiki-research` | Autonomous multi-round web research, filed straight into the vault | `/wiki-research [topic]` |
| `wiki-history-ingest` | Unified router for agent history ingest | `/wiki-history-ingest <agent>` |
| `claude-history-ingest` | Mine `~/.claude` conversations and memories (Claude Code + desktop) | `/claude-history-ingest` |
| `codex-history-ingest` | Mine `~/.codex` sessions and rollout logs | `/codex-history-ingest` |
| `hermes-history-ingest` | Mine `~/.hermes` memories and sessions | `/hermes-history-ingest` |
| `openclaw-history-ingest` | Mine `~/.openclaw` `MEMORY.md` and sessions | `/openclaw-history-ingest` |
| `copilot-history-ingest` | Mine `~/.copilot` CLI session history | `/copilot-history-ingest` |
| `pi-history-ingest` | Mine `~/.pi/agent/sessions` JSONL history | `/pi-history-ingest` |
| `wiki-agent` | Topic-first ingest from one agent's raw history | `/wiki-claude`, `/wiki-codex`, `/wiki-hermes`, `/wiki-openclaw`, `/wiki-copilot`, `/wiki-pi` |

## Asking the brain

| Skill | What it does | Slash command |
|---|---|---|
| `wiki-query` | Answer questions from the vault with citations. Tiered — reads summaries before page bodies | `/wiki-query` |
| `wiki-narrate` | Render a cited briefing, plain-language explanation, or progressive lecture from a topic | `/wiki-narrate <topic>` |
| `wiki-digest` | Newsletter-style summary of what you learned over a day, week, or month | `/wiki-digest [period]` |
| `wiki-context-pack` | Produce a token-bounded context slice for a downstream agent or skill | `/wiki-context-pack` |
| `memory-bridge` | Browse and diff knowledge by which AI tool wrote it | `/memory-bridge` |

## Finding past sessions

These two build a retrieval index over your raw agent sessions. They write a sidecar at `~/.claude/session-brain/` and **never touch the vault**. See [Session Brain](session-brain.md).

| Skill | What it does | Slash command |
|---|---|---|
| `session-brain` | Build and maintain a topic graph over your agent session history | `/session-brain` |
| `session-search` | Find a past session by topic and load its context into the current conversation | `/wiki-sessions <topic>` |

> **Ingest vs. retrieve.** If you want knowledge preserved as permanent vault pages, use `wiki-history-ingest`. If you want to find the session where something happened, use these.

## Maintaining the brain

| Skill | What it does | Slash command |
|---|---|---|
| `wiki-status` | What's ingested, what's pending, the delta — plus vault-shape insights (hubs, bridges, clusters) and an equilibrium check across the maintenance skills | `/wiki-status` |
| `wiki-lint` | Find broken links, orphans, stale content, contradictions, missing frontmatter | `/wiki-lint` |
| `wiki-dedup` | Identity resolution — merge pages covering the same concept under different names | `/wiki-dedup` |
| `cross-linker` | Auto-discover unlinked mentions and weave them into the graph with `[[wikilinks]]` | `/cross-linker` |
| `tag-taxonomy` | Enforce a consistent tag vocabulary across every page | `/tag-taxonomy` |
| `wiki-synthesize` | Discover and fill synthesis gaps across concepts | `/wiki-synthesize` |
| `wiki-stage-commit` | Review and promote staged pages when `WIKI_STAGED_WRITES=true` | `/wiki-stage-commit` |
| `wiki-rebuild` | Archive the vault, rebuild from scratch, or restore a previous archive | `/wiki-rebuild` |

## Seeing & moving the brain

| Skill | What it does | Slash command |
|---|---|---|
| `graph-colorize` | Color-code the Obsidian graph view by tag, category, or visibility | `/graph-colorize` |
| `wiki-dashboard` | Create dynamic Obsidian Bases dashboard views | `/wiki-dashboard` |
| `wiki-export` | Export the graph to JSON, GraphML, Neo4j Cypher, Postgres SQL, interactive HTML, or an OKF bundle | `/wiki-export` |
| `wiki-import` | Import a `graph.json` export or an OKF markdown bundle into the current vault | `/wiki-import` |
| `obsidian-layout-adjustment` | Restyle Obsidian via CSS snippets — tabs, sidebars, graph panes, note surfaces | — |

## Extending the framework

| Skill | What it does | Slash command |
|---|---|---|
| `llm-wiki` | The core pattern and architecture reference every other skill defers to | `/llm-wiki` |
| `skill-creator` | Create, edit, and eval new skills | `/skill-creator` |
| `vault-skill-factory` | Turn a cluster of mature vault pages into a portable "digital expert" skill | `/vault-skill-factory` |
| `impl-validator` | Validate an implementation against its stated goal | `/impl-validator` |

## Recommended companion: Obsidian Skills by Kepano

This framework handles the knowledge-management workflow — ingest, query, lint, rebuild. For Obsidian format mastery, install [**kepano/obsidian-skills**](https://github.com/kepano/obsidian-skills) alongside it. Optional, but it improves output quality:

| Skill | What it adds |
|---|---|
| `obsidian-markdown` | Correct Obsidian-flavored syntax — wikilinks, callouts, embeds, properties |
| `obsidian-bases` | Create and edit `.base` files (database-like views of notes) |
| `json-canvas` | Create and edit `.canvas` files (visual mind maps, flowcharts) |
| `obsidian-cli` | Interact with a running Obsidian instance via CLI |
| `defuddle` | Extract clean markdown from web pages — less noise, fewer tokens during ingest |

```bash
npx skills add kepano/obsidian-skills
```

Both projects follow the same [Agent Skills spec](https://agentskills.io/specification), so they coexist in the same `.skills/` directory with no conflicts.

## Writing your own

See [Contributing → Adding a new skill](contributing.md#adding-a-new-skill), or just ask:

> "Create a skill that generates weekly summaries from my journal entries"

`skill-creator` walks you through drafting, testing, and refining it in `.skills/`.
