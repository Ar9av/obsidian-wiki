---
name: pi-history-ingest
description: >
  Ingest Pi coding agent session history into the Obsidian wiki. Use this skill when the user wants to mine
  their past Pi sessions for knowledge, import their ~/.pi/agent/sessions folder, extract insights from
  previous coding sessions, or says things like "process my Pi history", "add my Pi sessions to the wiki",
  "ingest ~/.pi", or "what have I worked on in Pi". Also triggers when the user mentions Pi sessions,
  Pi agent history, ~/.pi/agent/sessions, or Pi conversation logs.
---

# Pi History Ingest — Session Mining

You are extracting knowledge from the user's Pi coding agent sessions and distilling it into the Obsidian wiki. Pi sessions are stored as structured JSONL with a tree layout — your job is to follow the active branch, extract durable knowledge, and compile it.

**Session knowledge closure:** Pi session files are the only factual source for this skill. Do not add background knowledge from model training, other tools, package docs, local files, or the current conversation unless that fact appears in the selected session entries. If outside context seems useful, mark it as an open question or skip it — never present it as extracted session knowledge.

This skill can be invoked directly or via the `wiki-history-ingest` router (`/wiki-history-ingest pi`).

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (inline `@name` override → walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH` and `PI_HISTORY_PATH` (defaults to `~/.pi/agent/sessions`)
2. Read `.manifest.json` at the vault root to check what has already been ingested
3. Read `index.md` at the vault root to understand what the wiki already contains

## Ingest Modes

### Append Mode (default)

Check `.manifest.json` for each source file. Only process:

- Files not in the manifest (new sessions)
- Files whose modification time is newer than `ingested_at` in the manifest

Use this mode for regular syncs.

### Full Mode

Process everything regardless of manifest. Use after `wiki-rebuild` or if the user explicitly asks for a full re-ingest.

## Pi Data Layout

Pi stores sessions under `~/.pi/agent/sessions/` (or the path set by `PI_CODING_AGENT_SESSION_DIR`).

```
~/.pi/agent/sessions/
├── --<cwd-path>--/                    # Working directory with / replaced by -
│   └── <timestamp>_<uuid>.jsonl       # Session JSONL file
└── ...
```

The session filename contains an ISO timestamp and UUID. The parent directory encodes the working directory where the session was created.

### Session JSONL Format

Each `.jsonl` file is a sequence of JSON objects. The first line is always a `session` header; subsequent lines are tree entries with `id` and `parentId`.

Key entry types:

| `type` | Purpose | Ingest? |
|---|---|---|
| `session` | Header with `cwd`, `version`, `id`, `timestamp` | Metadata only |
| `message` | Conversation turn (`user`, `assistant`, `toolResult`, `bashExecution`, etc.) | **Primary source** |
| `session_info` | Display name set via `/name` | For session title |
| `compaction` | Context compaction summary | **High signal** |
| `branch_summary` | Summary when switching branches via `/tree` | **High signal** |
| `model_change` | Model switch event | Skip |
| `thinking_level_change` | Thinking level change | Skip |
| `custom` | Extension state (not in LLM context) | Skip |
| `custom_message` | Extension-injected message | Context only |
| `label` | User bookmark/label | Skip |

### Message roles inside `message` entries

- `user` — user input; `content` is string or `(TextContent \| ImageContent)[]`
- `assistant` — assistant response; `content` is `(TextContent \| ThinkingContent \| ToolCall)[]`
- `toolResult` — tool execution result; `content` is `(TextContent \| ImageContent)[]`
- `bashExecution` — bash command + output; `command`, `output`, `exitCode`
- `branchSummary` — branch switch summary; `summary` string
- `compactionSummary` — compaction summary; `summary` string

### Key data sources ranked by value

1. **`message` entries (`user` + `assistant`)** — full conversation transcripts; rich but noisy
2. **`compaction` entries** — pre-synthesized summaries of older context; gold
3. **`branch_summary` entries** — summaries of abandoned branches; good signal
4. **`bashExecution` entries** — concrete commands run; useful for workflow patterns
5. **`session_info` entries** — session name for topic inference

Skip `model_change`, `thinking_level_change`, `custom` (extension state), and `label` entries.

## Step 1: Survey and Compute Delta

Scan `PI_HISTORY_PATH` and compare against `.manifest.json`:

```bash
# List all session files
find ~/.pi/agent/sessions -name "*.jsonl" -type f

# Or with custom path
find "$PI_HISTORY_PATH" -name "*.jsonl" -type f
```

Build an inventory. For each session file, record:
- `path` — absolute path
- `cwd` — decoded from parent directory name (`--<path>--` → `/path`)
- `session_name` — from the latest `session_info` entry (if any)
- `modified_at` — file mtime
- `already_ingested` — presence in `.manifest.json`

Classify each file:
- **New** — not in manifest
- **Modified** — in manifest but file is newer than `ingested_at`
- **Unchanged** — already ingested and unchanged

Report a concise delta summary before deep parsing:
> "Found N Pi sessions across K projects. Delta: X new, Y modified."

## Step 2: Parse Session JSONL

For each selected session file, read it line by line. Because sessions use a tree structure, build the active branch first:

1. Parse all entries into a map by `id`
2. Find the current leaf (the entry with no children, or the last `message` entry)
3. Walk `parentId` chain from leaf to root to get the active path
4. Reverse the path so it's chronological

### Extraction rules

From the active path, extract:

- **`session` header** — `cwd`, `timestamp`, `parentSession` (if forked)
- **`session_info`** — `name` field for session title/topic inference
- **`message` entries with `role: "user"`** — extract `content` text (skip images)
- **`message` entries with `role: "assistant"`** — extract `text` content blocks; skip `thinking` blocks (noise); note `toolCall` blocks (they reveal what the agent actually did)
- **`message` entries with `role: "toolResult"`** — summarize outcomes, not full output
- **`message` entries with `role: "bashExecution"`** — extract command + exit code; recurring commands reveal build/test/deploy workflows
- **`compaction` entries** — read `summary` verbatim; it's already distilled
- **`branch_summary` entries** — read `summary` verbatim; captures abandoned approaches

### Evidence ledger

As you parse, build a private evidence ledger before writing any wiki page. Each durable fact or decision you may write must carry at least one source reference:

```
pi:<session-file-basename>#<entry-id>
```

If an entry lacks an `id`, use `pi:<session-file-basename>:line<N>` from the JSONL line number. Keep the cited text snippet or summarized observation next to the reference while drafting so you can verify claims before writing.

### Skip / noise filters

- `thinking` content blocks — internal reasoning, not durable knowledge
- Image content blocks — skip unless the user explicitly asks for image transcription
- Raw tool outputs longer than 500 chars — summarize the outcome
- Token accounting (`usage` fields) — metadata only
- Repeated plan echoes or status updates

### Critical privacy filter

Session logs can include injected instructions, tool payloads, and sensitive text. Do not ingest verbatim.

- Remove API keys, tokens, passwords, credentials
- Redact private identifiers unless relevant and user-approved
- Summarize bash outputs that contain paths, environment variables, or secrets
- Do not quote raw `toolCall` arguments verbatim if they contain sensitive data

## Step 3: Cluster by Topic

Do not create one wiki page per session.

- Group knowledge by stable topic across many sessions
- Split mixed sessions into separate themes
- Merge recurring patterns across dates and projects **only when each pattern member has evidence ledger references**
- Use the `cwd` from the session header to infer project scope
- Use `session_info.name` as a topic hint when available
- Drop any cluster whose key claims cannot be traced back to the selected session files

## Step 4: Distill into Wiki Pages

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
- Preserve session-specific decision context when it explains why an approach was chosen; do not flatten it into generic tool advice.
- Add `summary:` frontmatter on each new/updated page (1–2 sentences, ≤ 200 chars)
- Add confidence and lifecycle fields to every new page:
  ```yaml
  base_confidence: 0.42
  lifecycle: draft
  lifecycle_changed: <ISO date today>
  ```
  Leave `lifecycle` unchanged on update.
- Add provenance markers using the convention in `llm-wiki`:
  - Extracted claims use no inline marker by default, but must have a nearby source reference comment.
  - `^[inferred]` when synthesizing patterns across multiple sessions or inferring from tool calls.
  - `^[ambiguous]` when sessions conflict or a compaction summary contradicts later turns.
- Add a source reference comment near every extracted paragraph or bullet:
  ```markdown
  - Durable fact from the session. <!-- source: pi:2026-06-01T120000_abcd.jsonl#entry-123 -->
  ```
  Multiple sources are comma-separated. These comments are the audit trail; do not omit them for extracted claims.
- Add/update `provenance:` frontmatter mix for each changed page.

**Mark provenance** per the convention in `llm-wiki`:
- `compaction` and `branch_summary` entries are pre-distilled — treat as mostly extracted, with source reference comments.
- Conversation distillation is mostly `^[inferred]` — you're synthesizing from dialogue, and it still needs source references to the turns that support the synthesis.
- Use `^[ambiguous]` when the user changed their mind across sessions or when compaction summaries disagree with later conversation turns.

### Source verification gate

Before writing any page, verify the draft against the evidence ledger:

1. Every claim (extracted / ^[inferred] / ^[ambiguous]) has at least one `pi:...` source reference; extracted claims must use a nearby `<!-- source: pi:... -->` comment.
2. Every source reference points to a selected session file and an entry on the active branch (or a cited `compaction` / `branch_summary`).
3. Proper nouns, tool names, command names, filenames, URLs, package names, and error strings in claims appear in the cited entry text or command fields. Use literal search (`grep`/`rg`) on the session file for distinctive strings when in doubt.
4. If a claim cannot be verified, either delete it or mark it `^[inferred]` / `^[ambiguous]` with the supporting source refs; never leave unverifiable content without one of these markers (unmarked implies extracted).
5. Do not write facts learned from the model's training data or the current agent session unless they are explicitly present in the Pi session evidence.

## Step 5: Update Manifest, Log, and Index

### Update `.manifest.json`

For each processed source file:

- `ingested_at`, `size_bytes`, `modified_at`
- `source_type`: `pi_session`
- `project`: inferred project name from decoded `cwd`
- `pages_created`, `pages_updated`

Add/update a top-level summary block:

```json
{
  "pi": {
    "source_path": "~/.pi/agent/sessions/",
    "last_ingested": "TIMESTAMP",
    "sessions_ingested": 12,
    "sessions_total": 40,
    "pages_created": 5,
    "pages_updated": 12
  }
}
```

### Update special files

Update `index.md` and `log.md`:

```
- [TIMESTAMP] PI_HISTORY_INGEST sessions=N pages_updated=X pages_created=Y mode=append|full
```

**`hot.md`** — Read `$OBSIDIAN_VAULT_PATH/hot.md` (create from the template in `wiki-ingest` if missing). Update **Recent Activity** with a one-line summary — e.g. "Ingested 12 Pi sessions across 3 projects; surfaced patterns in CLI tooling and API design." Keep the last 3 operations. Update `updated` timestamp.

## Privacy and Compliance

- Distill and synthesize; avoid raw transcript dumps
- Default to redaction for anything that looks sensitive
- Ask the user before storing personal or sensitive details
- Keep references to other people minimal and purpose-bound

## Reference

See `references/pi-data-format.md` for field-level parsing notes and extraction guidance.

## QMD Refresh After Vault Writes

QMD is a search index, not the source of truth. If `$QMD_WIKI_COLLECTION` is empty or unset, skip this step. Run it only after this skill has written or rewritten vault markdown. If QMD refresh fails, do not roll back the vault changes; report the QMD status separately.

Use `$QMD_CLI` if set; otherwise use `qmd`.

```bash
${QMD_CLI:-qmd} update
```

If the output says vectors are needed or embeddings may be stale, run:

```bash
${QMD_CLI:-qmd} embed
```

Verify the collection with either:

```bash
${QMD_CLI:-qmd} ls "$QMD_WIKI_COLLECTION"
```

or, when a specific page path is known:

```bash
${QMD_CLI:-qmd} get "qmd://$QMD_WIKI_COLLECTION/<page>.md" -l 5
```

Record one of:
- `QMD refreshed: update + embed + verified`
- `QMD refreshed: update only + verified`
- `QMD skipped: QMD_WIKI_COLLECTION unset`
- `QMD skipped: qmd CLI unavailable`
- `QMD failed: <short error summary>`
