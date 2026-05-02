---
name: hermes-history-ingest
description: >
  Ingest Hermes agent history into the Obsidian wiki. Use this skill when the user wants to mine
  their past Hermes sessions for knowledge, import their ~/.hermes folder, extract insights from
  previous Hermes conversations, or says things like "process my Hermes history", "add my Hermes
  memories to the wiki", "ingest ~/.hermes", or "what have I worked on in Hermes". Also triggers
  when the user mentions Hermes memories, Hermes sessions, ~/.hermes/memories, or Hermes skill logs.
---

# Hermes History Ingest — Conversation & Memory Mining

You are extracting knowledge from the user's Hermes agent history and distilling it into the Obsidian wiki. Hermes stores both free-form memories and structured session transcripts — focus on durable knowledge, not operational telemetry.

This skill can be invoked directly or via the `wiki-history-ingest` router (`/wiki-history-ingest hermes`).

## Before You Start

1. Read `.env` to get `OBSIDIAN_VAULT_PATH` and `HERMES_HISTORY_PATH` (default to `~/.hermes` if unset)
2. Read `.manifest.json` at the vault root to check what has already been ingested
3. Read `index.md` at the vault root to understand what the wiki already contains

## Ingest Modes

### Append Mode (default)

Check `.manifest.json` for each source file. Only process:

- Files not in the manifest (new memory files, new session logs)
- Files whose modification time is newer than `ingested_at` in the manifest

Use this mode for regular syncs.

### Full Mode

Process everything regardless of manifest. Use after `wiki-rebuild` or if the user explicitly asks for a full re-ingest.

## Hermes Data Layout

Hermes stores all local artifacts under `~/.hermes/` (or `$HERMES_HOME` for non-default profiles).

```
~/.hermes/
├── memories/                          # Persistent agent memories (markdown or JSON)
│   └── *.md / *.json
├── skills/                            # Installed skills (read-only for ingest purposes)
│   └── <skill-name>/SKILL.md
├── sessions/                          # Session transcripts (if session logging is enabled)
│   └── YYYY-MM-DD/
│       └── <session-id>.jsonl
├── config.yaml                        # User config (model, theme, paths)
└── .hub/                              # Skills Hub state (lock.json, audit.log, quarantine/)
```

### Key data sources ranked by value

1. `memories/*.md` / `memories/*.json` — highest signal; curated persistent knowledge the agent accumulated
2. `sessions/**/*.jsonl` — structured turn-by-turn transcripts; rich but noisy
3. `config.yaml` — metadata only (model preferences, paths); rarely worth ingesting

Skip `.hub/` internals (audit/quarantine state) and the `skills/` directory (source material, not user knowledge).

## Step 1: Survey and Compute Delta

Scan `HERMES_HISTORY_PATH` and compare against `.manifest.json`:

- `~/.hermes/memories/`
- `~/.hermes/sessions/**/` (if present)

Classify each file:

- **New** — not in manifest
- **Modified** — in manifest but file is newer than `ingested_at`
- **Unchanged** — already ingested and unchanged

Report a concise delta summary before deep parsing.

## Step 2: Parse Memories First

Memories are the highest-value source. Hermes writes them as either:

- **Markdown** — structured prose with optional frontmatter; ingest directly
- **JSON** — `{"content": "...", "created_at": "...", "tags": [...]}` records

For each memory:

- Extract the core knowledge claim
- Note any tags Hermes attached (they often map to wiki categories)
- Merge into the appropriate wiki page rather than creating one memory = one page

## Step 3: Parse Session JSONL Safely

Each session JSONL line is an event envelope. Common shapes:

```json
{"role": "user", "content": "..."}
{"role": "assistant", "content": "..."}
{"type": "tool_use", "name": "...", "input": {...}}
{"type": "tool_result", "content": "..."}
```

### Extraction rules

- Prioritize assistant responses that state conclusions, patterns, or decisions
- Extract user intent from high-signal turns; skip low-information follow-ups
- Treat `tool_use` / `tool_result` pairs as context, not primary content
- Skip token accounting, internal plumbing, and repeated plan echoes

### Critical privacy filter

Session logs can include injected instructions, tool payloads, and sensitive text. Do not ingest verbatim.

- Remove API keys, tokens, passwords, credentials
- Redact private identifiers unless relevant and user-approved
- Summarize; do not quote raw transcripts verbatim

## Step 4: Cluster by Topic

Do not create one wiki page per memory or session.

- Group memories by stable topic (concept, tool, project, technique)
- Split mixed sessions into separate themes
- Merge recurring patterns across dates and projects
- Use file paths or session `cwd` metadata to infer project scope when available

## Step 5: Distill into Wiki Pages

Route extracted knowledge using existing wiki conventions:

- Project-specific architecture/process → `projects/<name>/...`
- General concepts → `concepts/`
- Recurring techniques/debug playbooks → `skills/`
- Tools/services/frameworks → `entities/`
- Cross-session patterns → `synthesis/`

For each impacted project, create/update `projects/<name>/<name>.md`.

### Writing rules

- Distill knowledge, not chronology
- Avoid "on date X we discussed..." unless date context is essential
- Add `summary:` frontmatter on each new/updated page (1–2 sentences, ≤ 200 chars)
- Add confidence and lifecycle fields to every new page:
  ```yaml
  base_confidence: 0.42
  lifecycle: draft
  lifecycle_changed: <ISO date today>
  ```
  Leave `lifecycle` unchanged on update.
- Add provenance markers:
  - `^[extracted]` when directly grounded in explicit memory/session content
  - `^[inferred]` when synthesizing patterns across multiple memories
  - `^[ambiguous]` when memories conflict
- Add/update `provenance:` frontmatter mix for each changed page

## Step 6: Update Manifest, Log, and Index

### Update `.manifest.json`

For each processed source file:

- `ingested_at`, `size_bytes`, `modified_at`
- `source_type`: `hermes_memory` | `hermes_session`
- `project`: inferred project name (when applicable)
- `pages_created`, `pages_updated`

Add/update a top-level summary block:

```json
{
  "hermes": {
    "source_path": "~/.hermes/",
    "last_ingested": "TIMESTAMP",
    "memories_ingested": 42,
    "sessions_ingested": 7,
    "pages_created": 5,
    "pages_updated": 12
  }
}
```

### Update special files

Update `index.md` and `log.md`:

```
- [TIMESTAMP] HERMES_HISTORY_INGEST memories=N sessions=M pages_updated=X pages_created=Y mode=append|full
```

**`hot.md`** — Read `$OBSIDIAN_VAULT_PATH/hot.md` (create from the template in `wiki-ingest` if missing). Update **Recent Activity** with a one-line summary — e.g. "Ingested 42 Hermes memories and 7 sessions; dominant themes: reasoning strategies, tool use patterns." Keep the last 3 operations. Update `updated` timestamp.

## Privacy and Compliance

- Distill and synthesize; avoid raw memory or transcript dumps
- Default to redaction for anything that looks sensitive
- Ask the user before storing personal or sensitive details
- Keep references to other people minimal and purpose-bound

## Reference

See `references/hermes-data-format.md` for field-level notes and extraction guidance.
