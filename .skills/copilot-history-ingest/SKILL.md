---
name: copilot-history-ingest
description: >
  Ingest GitHub Copilot CLI session history into an Obsidian wiki as distilled knowledge pages. Use this skill
  when the user wants to capture their Copilot CLI sessions into a personal wiki — extracting architecture
  decisions, debug notes, and patterns into searchable Obsidian pages. Triggers on phrases like "ingest my
  copilot sessions into obsidian", "add my copilot history to my wiki", "pull my copilot session history into
  the vault", "capture what I've learned from copilot into obsidian", "just the new sessions since last time",
  or "mine patterns across my copilot sessions". Also triggers when the user mentions session-store.db,
  ~/.copilot/session-state, or VS Code copilot-chat transcripts in the context of building a wiki or knowledge
  base. Does NOT trigger for general copilot usage questions, searching sessions, or backing up history.
---

# Copilot History Ingest — Conversation Mining

You are extracting knowledge from the user's past GitHub Copilot CLI conversations and distilling it into the Obsidian wiki. Conversations are rich but messy — your job is to find the signal and compile it.

This skill can be invoked directly or via the `wiki-history-ingest` router (`/wiki-history-ingest copilot`).

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH`, `COPILOT_HISTORY_PATH` (defaults to `~/.copilot/session-state`), and `COPILOT_VSCODE_STORAGE_PATH` (VS Code `workspaceStorage`; platform-specific — ask the user if absent)
2. Read `.manifest.json` at the vault root to check what's already been ingested
3. Read `index.md` at the vault root to know what the wiki already contains

## Ingest Modes

### Append Mode (default)

Check `.manifest.json` for each source file (events JSONL, transcript JSONL, checkpoint, session-store DB). Only process:

- Sessions not in the manifest (new sessions)
- Sessions whose `updated_at` is newer than their `ingested_at` in the manifest

This is usually what you want — the user ran a few new sessions and wants to capture the delta.

### Full Mode

Process everything regardless of manifest. Use after a `wiki-rebuild` or if the user explicitly asks.

## GitHub Copilot Data Layout

Copilot stores data in three locations. Scan **all three**.

### Source 1: `~/.copilot/session-state/` (CLI sessions)

```
~/.copilot/session-state/
├── <session-uuid>/
│   ├── workspace.yaml           # Session metadata (id, cwd, summary_count, created_at, updated_at)
│   ├── vscode.metadata.json     # VS Code context (workspaceFolder, repositoryProperties, customTitle)
│   ├── events.jsonl             # Full event log — all turns, tool calls, reasoning
│   ├── session.db               # Per-session SQLite (todos/todo_deps only — skip for ingestion)
│   ├── index.md                 # Session summary written at session end
│   ├── checkpoints/             # Checkpoint JSON files (mid-session summaries)
│   │   └── <uuid>.json          # title, overview, history, work_done, technical_details,
│   │                            #   important_files, next_steps
│   ├── files/                   # Artifacts produced during session (plans, diagrams, etc.)
│   └── research/                # Research artifacts
└── ...
```

### Source 2: `~/.copilot/session-store.db` (Global SQLite)

The canonical cross-session database. This is the **highest-value** source: structured, queryable, and pre-summarised.

```
sessions       — id, cwd, repository, branch, summary, created_at, updated_at, host_type
turns          — session_id, turn_index, user_message, assistant_response, timestamp
checkpoints    — session_id, checkpoint_number, title, overview, history, work_done,
                 technical_details, important_files, next_steps, created_at
session_files  — session_id, file_path, tool_name, turn_index, first_seen_at
session_refs   — session_id, ref_type (commit/pr/issue), ref_value, turn_index, created_at
search_index   — FTS5 virtual table (content, session_id, source_type, source_id)
```

### Source 3: VS Code Workspace Storage (`<workspaceStorage>/<hash>/GitHub.copilot-chat/`)

VS Code extension data, keyed by workspace hash. The path is platform-specific and must come from `.env` or user input.

```
<hash>/GitHub.copilot-chat/
├── transcripts/
│   └── <session-uuid>.jsonl     # Conversation transcripts (same JSONL format as events.jsonl)
├── memory-tool/
│   └── memories/
│       └── <base64-session-id>/ # Per-session saved artifacts (plan.md, etc.)
│           └── plan.md
└── codebase-external.sqlite     # Codebase index (skip — no conversation knowledge)
```

### Key data sources ranked by value:

1. **Checkpoints** (`session-store.db` `checkpoints` table + per-session `checkpoints/*.json`) — Pre-distilled summaries with `overview`, `work_done`, `technical_details`, `important_files`, `next_steps`. Gold.
2. **Session summaries** (`session-store.db` `sessions.summary` + `index.md`) — One-paragraph synopsis per session.
3. **Turns** (`session-store.db` `turns` table + `events.jsonl` / transcript JSONL) — Full conversation. Rich but verbose.
4. **Memory artifacts** (`memory-tool/memories/<id>/plan.md` etc.) — Pre-written plans and structured notes the user saved explicitly. Worth importing verbatim (or lightly summarised).
5. **File access patterns** (`session_files` table + `tool.execution_*` events) — Which files the agent repeatedly touched — reveals high-value project files.
6. **Session refs** (`session_refs` table) — Commits, PRs, and issues linked to sessions.
7. **`vscode.metadata.json`** — Workspace folder path, branch, `customTitle` (user-set session label). Useful for grouping and naming.

## Step 1: Survey and Compute Delta

Scan all three data locations and compare against `.manifest.json`:

```bash
# --- Source 1: per-session directories ---
# Find all session directories (each has workspace.yaml)
ls ~/.copilot/session-state/

# For each session, read workspace.yaml for id/cwd/updated_at
# and vscode.metadata.json for customTitle / repositoryProperties

# --- Source 2: global database ---
# Query session-store.db with sqlite3 (or Python sqlite3)
SELECT s.id, s.cwd, s.repository, s.branch, s.summary, s.updated_at,
       COUNT(DISTINCT t.turn_index) AS turn_count,
       COUNT(DISTINCT c.id)         AS checkpoint_count
FROM sessions s
LEFT JOIN turns t ON t.session_id = s.id
LEFT JOIN checkpoints c ON c.session_id = s.id
GROUP BY s.id
ORDER BY s.updated_at DESC;

# --- Source 3: VS Code workspace storage ---
# For each <hash> directory under workspaceStorage, check for GitHub.copilot-chat/
# Find transcript files
ls <workspaceStorage>/<hash>/GitHub.copilot-chat/transcripts/
```

Build a unified inventory — one entry per session UUID — and classify:

- **New** — not in manifest → needs ingesting
- **Modified** — in manifest but `updated_at` is newer → needs re-ingesting
- **Unchanged** — in manifest and not modified → skip in append mode

Report to the user: "Found X sessions in session-state, Y in session-store.db, Z VS Code transcript files. Checkpoints: A. Delta: B new, C modified."

## Step 2: Ingest Checkpoints and Summaries First

Checkpoints are already distilled — process them before touching raw turns.

### From `session-store.db`:

```sql
SELECT s.id, s.cwd, s.repository, s.branch, s.summary,
       c.checkpoint_number, c.title, c.overview, c.work_done,
       c.technical_details, c.important_files, c.next_steps,
       c.created_at
FROM checkpoints c
JOIN sessions s ON c.session_id = s.id
ORDER BY s.updated_at DESC, c.checkpoint_number ASC;
```

### From per-session `checkpoints/*.json`:

Each checkpoint file has: `title`, `overview`, `history`, `work_done`, `technical_details`, `important_files`, `next_steps`.

Read `index.md` (if present) as a session-level summary — it's typically written at session end and is already concise.

### What to extract:

- `overview` → high-level description of what the session accomplished
- `work_done` → concrete tasks completed (good for skills / project pages)
- `technical_details` → implementation specifics (good for concepts pages)
- `important_files` → high-value files in the project (good for project pages)
- `next_steps` → open threads (good for linking to ongoing project work)

## Step 3: Parse Session Turns

Read turns from `session-store.db` (preferred — already parsed) or from `events.jsonl` / transcript JSONL.

### From `session-store.db`:

```sql
SELECT turn_index, user_message, assistant_response, timestamp
FROM turns
WHERE session_id = '<uuid>'
ORDER BY turn_index ASC;
```

### From `events.jsonl` / transcript JSONL:

Each file is one session. Each line is a JSON event. See `references/copilot-data-format.md` for the full schema.

**Relevant event types:**

| `type`                | What it is                              | Worth reading?                            |
| --------------------- | --------------------------------------- | ----------------------------------------- |
| `session.start`       | Session metadata (cwd, branch, version) | Yes — establishes project context         |
| `user.message`        | User turn                               | Yes — `data.content`                      |
| `assistant.message`   | Assistant turn                          | Yes — `data.content` (text) + `data.toolRequests` |
| `tool.execution_start`| Tool call                               | Skim — reveals what files/commands were used |
| `tool.execution_end`  | Tool result                             | No — usually noise                        |

**Extraction strategy for `assistant.message`:**

- `data.content` is the assistant's text response — extract this
- `data.reasoningText` is internal reasoning — skip (it's the unpacked `reasoningOpaque` field)
- `data.toolRequests` lists tool calls — skim tool names and arguments for file access patterns
- Skip `type: "tool.execution_end"` entirely

## Step 3b: Process Memory Artifacts

For each session that has a `memory-tool/memories/<base64-id>/` directory in VS Code workspace storage, read any markdown files saved there (typically `plan.md`). These are documents the user explicitly saved — treat them as high-quality, user-authored content.

Decode the base64 directory name to get the session UUID:

```python
import base64
session_id = base64.b64decode(dir_name).decode('utf-8')
```

Memory artifacts map to project `skills/` or `concepts/` pages, depending on content type.

## Step 3c: Extract File and Ref Patterns

From `session-store.db`:

```sql
-- Most-touched files per project
SELECT repository, file_path, COUNT(*) AS touch_count
FROM session_files
GROUP BY repository, file_path
ORDER BY touch_count DESC;

-- Linked commits/PRs/issues per session
SELECT session_id, ref_type, ref_value, turn_index
FROM session_refs
ORDER BY session_id, turn_index;
```

**File access patterns** reveal which files are architecturally important — note them on project pages.

**Session refs** link Copilot sessions to git history — useful for connecting wiki knowledge to concrete code changes.

## Step 4: Cluster by Topic

Don't create one wiki page per session. Instead:

- Group extracted knowledge **by topic** across sessions
- A single session about "debugging auth + setting up CI" → two separate topics
- Three sessions across different days about "React performance" → one merged topic
- `cwd` / `repository` give you a natural first-level grouping; `vscode.metadata.json`'s `customTitle` gives a human-readable session label

## Step 5: Distill into Wiki Pages

Each Copilot project maps to a project directory in the vault. Derive the project name from `cwd` or `repository`:

```
C:\Users\name\git\my-project   → my-project
/Users/name/code/another-app   → another-app
```

Prefer `repository` (e.g., `owner/repo`) from `session-store.db` over raw `cwd` when available.

### Project-specific vs. global knowledge

| What you found                      | Where it goes               | Example                                              |
| ----------------------------------- | --------------------------- | ---------------------------------------------------- |
| Project architecture decisions      | `projects/<name>/concepts/` | `projects/my-project/concepts/main-architecture.md`  |
| Project-specific debugging patterns | `projects/<name>/skills/`   | `projects/my-project/skills/api-rate-limiting.md`    |
| General concept the user learned    | `concepts/` (global)        | `concepts/react-server-components.md`                |
| Recurring problem across projects   | `skills/` (global)          | `skills/debugging-hydration-errors.md`               |
| A tool/service used                 | `entities/` (global)        | `entities/vercel-functions.md`                       |
| Patterns across many sessions       | `synthesis/` (global)       | `synthesis/common-debugging-patterns.md`             |

For each project with content, create or update the project overview page at `projects/<name>/<name>.md` — **named after the project, not `_project.md`**. Obsidian's graph view uses the filename as the node label, so `_project.md` makes every project show up as `_project` in the graph. Naming it `<name>.md` gives each project a distinct, readable node name.

**Important:** Distill the _knowledge_, not the conversation. Don't write "In a session on March 15, the user asked about X." Write the knowledge itself, with the session as a source attribution.

**Write a `summary:` frontmatter field** on every new/updated page — 1–2 sentences, ≤200 chars, answering "what is this page about?" for a reader who hasn't opened it. `wiki-query`'s cheap retrieval path reads this field to avoid opening page bodies.

**Add confidence and lifecycle fields** to every new page's frontmatter:
```yaml
base_confidence: 0.42
lifecycle: draft
lifecycle_changed: <ISO date today>
```
Leave `lifecycle` unchanged on update.

**Mark provenance** per the convention in `llm-wiki` (Provenance Markers section):

- **Checkpoints and index.md** are pre-distilled by the system — treat checkpoint-derived claims as extracted (the system wrote them from observed actions).
- **Memory artifacts** are user-authored — treat as extracted.
- **Conversation turn distillation** is mostly inferred. You're synthesizing a coherent claim from many turns. Apply `^[inferred]` liberally to synthesized patterns, generalizations across sessions, and "what the user really meant" interpretations.
- Use `^[ambiguous]` when the user changed direction mid-session or when the session ended unresolved.
- Write a `provenance:` frontmatter block on every new/updated page summarizing the rough mix.

## Step 6: Update Manifest, Journal, and Special Files

### Update `.manifest.json`

For each session processed, add/update its entry with:

- `ingested_at`, `session_id`, `updated_at`
- `source_type`: one of `"copilot_session"`, `"copilot_checkpoint"`, `"copilot_transcript"`, `"copilot_memory_artifact"`
- `project`: the decoded project name
- `pages_created` and `pages_updated` lists

Also update the `projects` section of the manifest:

```json
{
  "project-name": {
    "repository": "owner/repo",
    "cwd": "C:\\Users\\name\\git\\project-name",
    "vault_path": "projects/project-name",
    "last_ingested": "TIMESTAMP",
    "sessions_ingested": 5,
    "sessions_total": 8,
    "checkpoints_ingested": 12,
    "memory_artifacts_ingested": 3
  }
}
```

### Create journal entry + update special files

Update `index.md` and `log.md` per the standard process:

```
- [TIMESTAMP] COPILOT_HISTORY_INGEST projects=N sessions=M checkpoints=C pages_updated=X pages_created=Y mode=append|full
```

**`hot.md`** — Read `$OBSIDIAN_VAULT_PATH/hot.md` (create from the template in `wiki-ingest` if missing). Update **Recent Activity** with a one-line summary — e.g. "Ingested 5 Copilot sessions across 2 projects; surfaced patterns in API design and testing strategy." Keep the last 3 operations. Update **Active Threads** if any ongoing project is now better understood. Update `updated` timestamp.

## Privacy

- Distill and synthesize — don't copy raw conversation text verbatim
- Skip anything that looks like secrets, API keys, passwords, tokens
- `data.reasoningOpaque` / `data.reasoningText` in assistant events is internal reasoning — skip entirely, never copy to wiki
- If you encounter personal/sensitive content, ask the user before including it
- The user's conversations may reference other people — be thoughtful about what goes in the wiki

## Reference

See `references/copilot-data-format.md` for detailed data structure documentation.
