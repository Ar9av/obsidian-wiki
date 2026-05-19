---
name: wiki-history-ingest
description: >
  Unified wiki-history-ingest entrypoint for conversation/session/learnings sources. Use this when the
  user says "/wiki-history-ingest claude", "/wiki-history-ingest copilot", "/wiki-history-ingest codex",
  "/wiki-history-ingest gstack", etc., or asks to ingest agent history without naming the underlying
  skill. This router dispatches to the specialized history skill.
---

# Unified History Ingest Router

This is a thin router for **history sources only**. It does not replace `wiki-ingest` for documents.

## Subcommands

If the user invokes `/wiki-history-ingest <target>` (or equivalent text command), dispatch directly:

| Subcommand | Route To |
|---|---|
| `claude` | `claude-history-ingest` |
| `copilot` | `copilot-history-ingest` |
| `codex` | `codex-history-ingest` |
| `hermes` | `hermes-history-ingest` |
| `openclaw` | `openclaw-history-ingest` |
| `gstack` | `gstack-history-ingest` |
| `auto` | infer from context using rules below |

## Routing Rules

1. If the user explicitly says `claude`, `copilot`, `codex`, `hermes`, `openclaw`, or `gstack`, route directly.
2. If the user provides a path/source:
   - `~/.claude` or Claude memory/session JSONL artifacts -> `claude-history-ingest`
   - `~/.copilot`, `session-store.db`, VS Code copilot-chat transcripts -> `copilot-history-ingest`
   - `~/.codex` or rollout/session index artifacts -> `codex-history-ingest`
   - `~/.hermes` or Hermes memories/session artifacts -> `hermes-history-ingest`
   - `~/.openclaw` or OpenClaw MEMORY.md/session JSONL artifacts -> `openclaw-history-ingest`
   - `~/.gstack/projects/*/learnings.jsonl` artifacts -> `gstack-history-ingest`
3. If ambiguous, ask one short clarification:
   - "Should I ingest `claude`, `copilot`, `codex`, `hermes`, `openclaw`, or `gstack` history?"

## Execution Contract

- After routing, execute the destination skill's workflow exactly.
- Do not duplicate destination logic in this file.
- Leave manifest/index/log update semantics to the destination skill.

## UX Convention

- Use `wiki-ingest` for **documents/content sources**
- Use `wiki-history-ingest` for **agent history sources**

Examples:

- `/wiki-history-ingest claude`
- `/wiki-history-ingest copilot`
- `/wiki-history-ingest codex`
- `/wiki-history-ingest hermes`
- `/wiki-history-ingest openclaw`
- `/wiki-history-ingest gstack`
- `$wiki-history-ingest claude` (agents that use `$skill` invocation)
- `$wiki-history-ingest copilot`
