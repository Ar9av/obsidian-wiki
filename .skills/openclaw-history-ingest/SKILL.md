---
name: openclaw-history-ingest
description: >
  Ingest OpenClaw agent history into the Obsidian wiki. Use this skill when the user wants to mine
  their past OpenClaw sessions for knowledge, import their ~/.openclaw folder, extract insights from
  previous OpenClaw conversations, or says things like "process my OpenClaw history", "add my OpenClaw
  sessions to the wiki", "ingest ~/.openclaw", or "what have I worked on in OpenClaw". Also triggers
  when the user mentions OpenClaw session logs, MEMORY.md, daily notes, or ~/.openclaw/workspace.
---

# OpenClaw History Ingest — Session & Memory Mining

You are extracting knowledge from the user's OpenClaw agent history and distilling it into the Obsidian wiki. OpenClaw stores both a structured long-term MEMORY.md and per-session JSONL transcripts — focus on durable knowledge, not operational telemetry.

This skill can be invoked directly or via the `wiki-history-ingest` router (`/wiki-history-ingest openclaw`).

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH` and `OPENCLAW_HISTORY_PATH` (defaults to `~/.openclaw`)
2. Read `.manifest.json` at the vault root to check what has already been ingested
3. Read `index.md` at the vault root to understand what the wiki already contains

## Ingest Modes

### Append Mode (default)

Check `.manifest.json` for each source file. Only process:

- Files not in the manifest (new session logs, updated MEMORY.md or daily notes)
- Files whose modification time is newer than `ingested_at` in the manifest

Use this mode for regular syncs.

### Full Mode

Process everything regardless of manifest. Use after `wiki-rebuild` or if the user explicitly asks for a full re-ingest.

## OpenClaw Data Layout

OpenClaw stores all local artifacts under `~/.openclaw/`.

```
~/.openclaw/
├── openclaw.json                          # Global config
├── credentials/                           # Auth tokens (skip entirely)
├── workspace/                             # Agent workspace
│   ├── MEMORY.md                          # Long-term memory (loaded every session)
│   ├── DREAMS.md                          # Optional dream diary / summaries
│   └── memory/
│       ├── YYYY-MM-DD.md                  # Daily notes (today + yesterday auto-loaded)
│       └── ...
└── agents/
    └── <agentId>/
        ├── agent/
        │   └── models.json                # Agent config (skip)
        └── sessions/
            ├── sessions.json              # Session index
            └── <sessionId>.jsonl          # Session transcript (JSONL, append-only)
```

### Key data sources ranked by value

1. `workspace/MEMORY.md` — highest signal; long-term durable facts the agent accumulated
2. `workspace/memory/YYYY-MM-DD.md` — daily notes; recent entries often contain active project context
3. `agents/*/sessions/<id>.jsonl` — session transcripts; rich but noisy
4. `agents/*/sessions/sessions.json` — session index for inventory and timestamps
5. `workspace/DREAMS.md` — optional summaries; ingest if present

Skip `credentials/` entirely. Skip `agents/*/agent/models.json` (runtime config, not user knowledge).

## Step 1: Survey and Compute Delta

Scan `OPENCLAW_HISTORY_PATH` and compare against `.manifest.json`:

- `~/.openclaw/workspace/MEMORY.md`
- `~/.openclaw/workspace/DREAMS.md` (if present)
- `~/.openclaw/workspace/memory/*.md`
- `~/.openclaw/agents/*/sessions/sessions.json`
- `~/.openclaw/agents/*/sessions/*.jsonl`

Classify each file:

- **New** — not in manifest
- **Modified** — in manifest but file is newer than `ingested_at`
- **Unchanged** — already ingested and unchanged

Report a concise delta summary before deep parsing.

## Step 2: Parse MEMORY.md First

`MEMORY.md` is the highest-value source. It is plain markdown, human-readable and human-editable. It typically contains:

- Durable facts about the user's preferences, environment, and recurring patterns
- Decisions and context the agent was told to remember
- Project-specific notes the agent accumulated over many sessions

Read it in full and extract concept-level knowledge. Do not create one wiki page per MEMORY.md entry — cluster by topic.

## Step 3: Parse Daily Notes

`workspace/memory/YYYY-MM-DD.md` files contain time-stamped notes from that day's sessions. Prioritize recent files (last 30–90 days). Extract:

- Active project context and decisions made
- Patterns or techniques discovered
- Recurring blockers or solved problems

Older daily notes have diminishing signal — summarize in bulk rather than extracting line-by-line.

## Step 4: Parse Session JSONL Safely

Each session file is JSONL (append-only, one JSON object per line):

```json
{"role": "user",      "content": "...", "timestamp": "..."}
{"role": "assistant", "content": "...", "timestamp": "..."}
{"role": "tool",      "name": "...",   "content": "...", "timestamp": "..."}
```

### Extraction rules

- Prioritize assistant turns that state conclusions, decisions, or patterns
- Extract user intent from high-signal turns; skip low-information follow-ups
- Tool calls are context, not primary knowledge — only extract if the result contains a reusable insight
- Cross-reference `sessions.json` index to get session names/labels before opening individual transcripts

### Critical privacy filter

Session transcripts can include injected instructions, tool payloads, and sensitive text. Do not ingest verbatim.

- Remove API keys, tokens, passwords, credentials
- Redact private identifiers unless relevant and user-approved
- Summarize; do not quote raw transcripts verbatim

## Step 5: Cluster by Topic

Do not create one wiki page per session or per MEMORY.md entry.

- Group by stable topic (concept, tool, project, technique)
- Split mixed sessions into separate themes
- Merge recurring patterns across dates and agents
- Use session `cwd` or workspace path to infer project scope when available

## Step 6: Distill into Wiki Pages

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
  - `^[extracted]` when directly grounded in explicit session/memory content
  - `^[inferred]` when synthesizing patterns across multiple sessions
  - `^[ambiguous]` when sessions conflict
- Add/update `provenance:` frontmatter mix for each changed page

## Step 7: Update Manifest, Log, and Index

### Update `.manifest.json`

For each processed source file:

- `ingested_at`, `size_bytes`, `modified_at`
- `source_type`: `openclaw_memory` | `openclaw_daily_note` | `openclaw_session` | `openclaw_dreams`
- `agent_id`: agent directory name (when applicable)
- `pages_created`, `pages_updated`

Add/update a top-level summary block:

```json
{
  "openclaw": {
    "source_path": "~/.openclaw/",
    "last_ingested": "TIMESTAMP",
    "memory_updated_at": "TIMESTAMP",
    "daily_notes_ingested": 14,
    "sessions_ingested": 23,
    "pages_created": 6,
    "pages_updated": 18
  }
}
```

### Update special files

Update `index.md` and `log.md`:

```
- [TIMESTAMP] OPENCLAW_HISTORY_INGEST memory=updated daily_notes=N sessions=M pages_updated=X pages_created=Y mode=append|full
```

**`hot.md`** — Read `$OBSIDIAN_VAULT_PATH/hot.md` (create from the template in `wiki-ingest` if missing). Update **Recent Activity** with a one-line summary — e.g. "Ingested OpenClaw MEMORY.md and 14 daily notes; surfaced automation patterns and multi-agent coordination knowledge." Keep the last 3 operations. Update `updated` timestamp.

## Privacy and Compliance

- Distill and synthesize; avoid raw memory or transcript dumps
- Default to redaction for anything that looks sensitive
- Ask the user before storing personal or sensitive details
- Keep references to other people minimal and purpose-bound

## Reference

See `references/openclaw-data-format.md` for field-level notes and parsing guidance.
