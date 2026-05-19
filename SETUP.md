# Setup

A skill-based framework for AI coding agents — Claude Code, Cursor, Windsurf, Pi, Gemini CLI, Google Antigravity, Codex, Hermes, OpenClaw, OpenCode, Aider, Factory Droid, Trae / Trae CN, Kiro, GitHub Copilot (CLI + VS Code Chat) — to build and maintain an Obsidian wiki using Karpathy's LLM Wiki pattern. No scripts, no API keys — the agent **is** the LLM.

> Running `bash setup.sh` wires up every supported agent: project-local skill symlinks (`.claude/skills/`, `.cursor/skills/`, `.windsurf/skills/`, `.agents/skills/`, `.kiro/skills/`), global symlinks (`~/.claude/skills/`, `~/.gemini/skills/`, `~/.codex/skills/`, `~/.hermes/skills/`, `~/.openclaw/skills/`, `~/.copilot/skills/`, `~/.trae/skills/`, `~/.trae-cn/skills/`, `~/.kiro/skills/`, `~/.agents/skills/`), and always-on rule files (`CLAUDE.md`, `GEMINI.md`, `AGENTS.md`, `.hermes.md`, `.cursor/rules/…`, `.windsurf/rules/…`, `.kiro/steering/…`, `.agent/rules/…`, `.agent/workflows/…`, `.github/copilot-instructions.md`). See the [Agent Compatibility table in README.md](README.md#agent-compatibility) for the full matrix.

## Quick Start

### 1. Set your vault path

```bash
cp .env.example .env
```

Open `.env` and set `OBSIDIAN_VAULT_PATH` to your Obsidian vault:

```
OBSIDIAN_VAULT_PATH=/path/to/your/vault
```

That's the only required config.

### 2. Point an agent at the skills

Open this project in your coding agent and tell it what you want:

| What you say | Skill triggered |
|---|---|
| "Set up my wiki" | `wiki-setup` |
| "Ingest my documents from ~/research" | `wiki-ingest` |
| "/wiki-history-ingest claude" or "/wiki-history-ingest codex" | `wiki-history-ingest` |
| "Import my Claude history" | `claude-history-ingest` |
| "Import my Codex history" | `codex-history-ingest` |
| "Import my Pi history" | `pi-history-ingest` |
| "Process this ChatGPT export" | `data-ingest` |
| "What's the status of my wiki?" | `wiki-status` |
| "What do I know about X?" | `wiki-query` |
| "Audit my wiki" | `wiki-lint` |
| "Rebuild from scratch" | `wiki-rebuild` |

The agent reads the skills from `.skills/`, reads `.env` for your vault path, and does the work.

### 3. Open in Obsidian

Open your vault directory in Obsidian (File → Open Vault). The wiki pages, wikilinks, and graph view all work natively.

## What Can It Ingest?

Anything text-based:

| Source | Skill | What it reads |
|---|---|---|
| Markdown, PDFs, text files | `wiki-ingest` | Any document directory |
| Claude Code history | `claude-history-ingest` | `~/.claude/` — conversations, memories, sessions |
| Codex CLI history | `codex-history-ingest` | `~/.codex/` — sessions, rollouts, history index |
| Pi agent sessions | `pi-history-ingest` | `~/.pi/agent/sessions/` — tree-structured JSONL |
| ChatGPT exports | `data-ingest` | `conversations.json` from ChatGPT export |
| Slack / Discord logs | `data-ingest` | Channel export JSON files |
| Meeting transcripts | `data-ingest` | Any text transcript |
| Raw text dumps | `data-ingest` | Anything — CSV, logs, journals, notes |

## Tracking & Delta

The framework tracks everything it ingests via `.manifest.json` in the vault root. This enables:

- **Status view** — "What's been ingested? What's new? What's changed?"
- **Delta ingestion** — Only process new/modified sources, skip what's already in the wiki
- **Provenance** — Which source produced which wiki page
- **Staleness detection** — Source changed but wiki page hasn't been updated

### Typical workflow

```
"What's the status?"     → wiki-status computes the delta
"Ingest the new stuff"   → wiki-ingest processes only the delta (append mode)
"What's the status now?" → wiki-status confirms everything is up to date
```

### When things drift too far

```
"Archive and rebuild"    → wiki-rebuild archives current wiki to _archives/, clears, ready for fresh ingest
"Restore the old one"    → wiki-rebuild restores from a previous archive
```

Archives live at `$VAULT/_archives/` with full snapshots. Nothing is ever lost.

## Vault Structure

```
$OBSIDIAN_VAULT_PATH/
├── concepts/           # Global knowledge — ideas, theories, mental models
├── entities/           # People, orgs, tools
├── skills/             # How-to knowledge, procedures
├── references/         # Source summaries
├── synthesis/          # Cross-cutting analysis
├── journal/            # Timestamped logs
├── projects/           # Per-project knowledge
│   ├── my-project/
│   │   ├── _project.md
│   │   ├── concepts/
│   │   └── skills/
│   └── another-project/
│       └── ...
├── _archives/          # Wiki snapshots for rebuild/restore
├── index.md            # Auto-maintained catalog
├── log.md              # Chronological operation log
└── .manifest.json      # Ingest tracking ledger
```

Knowledge that's project-specific goes under `projects/<name>/`. Knowledge that's general goes in the global category directories. Both are cross-referenced with `[[wikilinks]]`.

## Optional Config

| Variable | What it does | Default |
|---|---|---|
| `OBSIDIAN_SOURCES_DIR` | Directories with docs to ingest (comma-separated) | *(empty — point agent at specific files)* |
| `OBSIDIAN_CATEGORIES` | Wiki page categories | `concepts,entities,skills,references,synthesis,journal` |
| `OBSIDIAN_MAX_PAGES_PER_INGEST` | Max pages updated per ingest | `15` |
| `CLAUDE_HISTORY_PATH` | Where to find Claude data | *auto-discovers from `~/.claude`* |
| `CODEX_HISTORY_PATH` | Where to find Codex data | *defaults to `~/.codex`* |
| `PI_HISTORY_PATH` | Where to find Pi sessions | *defaults to `~/.pi/agent/sessions`* |
| `LINT_SCHEDULE` | Wiki health check frequency | `weekly` |

## Skills Reference

| Skill | Purpose |
|---|---|
| `llm-wiki` | Core pattern — 3-layer architecture, page templates, project org |
| `wiki-setup` | Initialize vault structure, create index/log, configure Obsidian |
| `wiki-ingest` | Distill source documents into wiki pages (append or full mode) |
| `wiki-history-ingest` | Unified history ingest router (`claude`, `codex`, `pi`) |
| `data-ingest` | Ingest any raw text — chat exports, logs, transcripts, anything |
| `claude-history-ingest` | Mine `~/.claude` conversations and memories into wiki pages |
| `codex-history-ingest` | Mine `~/.codex` sessions and rollout logs into wiki pages |
| `pi-history-ingest` | Mine `~/.pi/agent/sessions` JSONL history into wiki pages |
| `wiki-status` | Audit: what's ingested, what's pending, delta, recommend action |
| `wiki-rebuild` | Archive current wiki, rebuild from scratch, or restore from archive |
| `wiki-query` | Answer questions from the compiled wiki with citations |
| `wiki-lint` | Find orphans, broken links, stale content, contradictions |
| `wiki-update` | Sync current project's knowledge into the vault (works from any project) |
| `skill-creator` | Create new skills to extend the framework |

## How It Works

No scripts, no dependencies. The skills are markdown files that tell an AI agent *how* to operate on your Obsidian vault:

1. Agent reads `.env` for vault path
2. Agent reads `.manifest.json` to know what's already been done
3. Agent reads the relevant skill for instructions
4. Agent uses its built-in tools (read, write, search) to do the work
5. Agent updates `.manifest.json` to track what it did
6. Output is standard Obsidian-compatible markdown with frontmatter and `[[wikilinks]]`

**The wiki is the artifact. The agent is the maintainer. Obsidian is the viewer.**

## Extending

Want a new workflow? Use the `skill-creator` skill:

> "Create a skill that generates weekly summaries from my journal entries"

It walks you through drafting, testing, and refining a new skill in `.skills/`.
