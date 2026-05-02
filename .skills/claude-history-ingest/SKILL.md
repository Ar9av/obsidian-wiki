---
name: claude-history-ingest
description: >
  Ingest Claude Code conversation history into the Obsidian wiki. Use this skill when the user wants to mine
  their past Claude conversations for knowledge, import their ~/.claude folder, extract insights from
  previous coding sessions, or says things like "process my Claude history", "add my conversations to the wiki",
  "what have I discussed with Claude before". Also triggers when the user mentions their .claude folder,
  Claude projects, session data, past conversation logs, local-agent-mode sessions, or audit logs.
---

# Claude History Ingest — Conversation Mining

You are extracting knowledge from the user's past Claude Code conversations and distilling it into the Obsidian wiki. Conversations are rich but messy — your job is to find the signal and compile it.

This skill can be invoked directly or via the `wiki-history-ingest` router (`/wiki-history-ingest claude`).

## Before You Start

1. Read `.env` to get `OBSIDIAN_VAULT_PATH` and `CLAUDE_HISTORY_PATH` (defaults to `~/.claude`)
2. Read `.manifest.json` at the vault root to check what's already been ingested
3. Read `index.md` at the vault root to know what the wiki already contains

## Ingest Modes

### Append Mode (default)

Check `.manifest.json` for each source file (conversation JSONL, memory file). Only process:

- Files not in the manifest (new conversations, new memory files, new projects)
- Files whose modification time is newer than their `ingested_at` in the manifest

This is usually what you want — the user ran a few new sessions and wants to capture the delta.

### Full Mode

Process everything regardless of manifest. Use after a `wiki-rebuild` or if the user explicitly asks.

## Claude Code Data Layout

Claude Code stores data in two locations. Scan **both**.

### Source 1: `~/.claude/` (CLI sessions)

```
~/.claude/
├── projects/                          # Per-project directories
│   ├── -Users-name-project-a/         # Path-derived name (slashes → dashes)
│   │   ├── <session-uuid>.jsonl       # Conversation data (JSONL)
│   │   └── memory/                    # Structured memories
│   │       ├── MEMORY.md              # Memory index
│   │       ├── user_*.md              # User profile memories
│   │       ├── feedback_*.md          # Workflow feedback memories
│   │       └── project_*.md           # Project context memories
│   ├── -Users-name-project-b/
│   │   └── ...
├── sessions/                          # Session metadata (JSON)
│   └── <pid>.json                     # {pid, sessionId, cwd, startedAt, kind, entrypoint}
├── history.jsonl                      # Global session history
├── tasks/                             # Subagent task data
├── plans/                             # Saved plans
└── settings.json
```

### Source 2: `~/Library/Application Support/Claude/local-agent-mode-sessions/` (Desktop app agent sessions)

The Claude desktop app stores local agent mode sessions here. The structure is deeply nested:

```
~/Library/Application Support/Claude/local-agent-mode-sessions/
└── <outer-uuid>/
    └── <inner-uuid>/
        ├── local_<session-uuid>.json          # Session metadata
        └── local_<session-uuid>/
            ├── audit.jsonl                    # Audit log — tool calls, file reads, commands run
            └── .claude/
                └── projects/
                    └── <path-encoded-name>/   # Same path-encoding as ~/.claude/projects/
                        └── <uuid>.jsonl       # Conversation transcript (same JSONL format as CLI)
```

**How to find all local-agent-mode sessions:**

```bash
# Find all session metadata files
find ~/Library/Application\ Support/Claude/local-agent-mode-sessions -name "local_*.json" -maxdepth 4

# Find all audit logs
find ~/Library/Application\ Support/Claude/local-agent-mode-sessions -name "audit.jsonl"

# Find all conversation transcripts
find ~/Library/Application\ Support/Claude/local-agent-mode-sessions -name "*.jsonl" -path "*/.claude/projects/*"
```

**Session metadata (`local_<uuid>.json`)** — JSON file with fields like `sessionId`, `cwd`, `startedAt`, `model`, `title`. Read this first to understand the session context before opening the transcript.

**Audit log (`audit.jsonl`)** — Each line is a JSON record of one agent action: tool calls (Read, Write, Bash, Edit), file accesses, shell commands executed, MCP calls. Useful for understanding *what the agent actually did* — often richer signal than the conversation text alone. Fields: `type`, `toolName`, `input`, `output`, `timestamp`, `sessionId`.

**Conversation transcript (`.claude/projects/.../<uuid>.jsonl`)** — Identical format to CLI conversation JSONL. Parse the same way as `~/.claude/projects/*/*.jsonl`.

### Key data sources ranked by value (both locations combined):

1. **Memory files** (`~/.claude/projects/*/memory/*.md`) — Pre-distilled, already wiki-friendly. Gold.
2. **Conversation JSONL** (both `~/.claude/projects/*/*.jsonl` and desktop app transcripts) — Full conversation transcripts. Rich but noisy.
3. **Audit logs** (`audit.jsonl` in desktop sessions) — Tool-call level record of what was done. Useful for extracting concrete actions, file patterns, and command patterns even when the conversation is sparse.
4. **Session metadata** (`sessions/*.json` and `local_*.json`) — Tells you which project, when, and what CWD.

## Step 1: Survey and Compute Delta

Scan both data locations and compare against `.manifest.json`:

```bash
# --- Source 1: CLI sessions (~/.claude) ---
# Find all projects
Glob: ~/.claude/projects/*/

# Find memory files (highest value)
Glob: ~/.claude/projects/*/memory/*.md

# Find conversation JSONL files
Glob: ~/.claude/projects/*/*.jsonl

# --- Source 2: Desktop app local-agent-mode sessions ---
DESKTOP_SESSIONS="$HOME/Library/Application Support/Claude/local-agent-mode-sessions"

# Session metadata
find "$DESKTOP_SESSIONS" -name "local_*.json" -maxdepth 4

# Audit logs
find "$DESKTOP_SESSIONS" -name "audit.jsonl"

# Conversation transcripts
find "$DESKTOP_SESSIONS" -name "*.jsonl" -path "*/.claude/projects/*"
```

Build a unified inventory and classify each file:

- **New** — not in manifest → needs ingesting
- **Modified** — in manifest but file is newer → needs re-ingesting
- **Unchanged** — in manifest and not modified → skip in append mode

Report to the user: "Found X CLI projects, Y desktop sessions. Memory files: A. Conversations: B. Audit logs: C. Delta: D new, E modified."

## Step 2: Ingest Memory Files First

Memory files are already structured with YAML frontmatter:

```markdown
---
name: memory-name
description: one-line description
type: user|feedback|project|reference
---

Memory content here.
```

For each memory file:

- Read it and parse the frontmatter
- `user` type → feeds into an entity page about the user, or concept pages about their domain
- `feedback` type → feeds into skills pages (workflow patterns, what works, what doesn't)
- `project` type → feeds into entity pages for the project
- `reference` type → feeds into reference pages pointing to external resources

The `MEMORY.md` index file in each project is a quick summary — read it first to decide which individual memory files are worth reading in full.

## Step 3: Parse Conversation JSONL

Each JSONL file is one conversation session. Each line is a JSON object:

```json
{
  "type": "user|assistant|progress|file-history-snapshot",
  "message": {
    "role": "user|assistant",
    "content": "text string"
  },
  "uuid": "...",
  "timestamp": "2026-03-15T10:30:00.000Z",
  "sessionId": "...",
  "cwd": "/path/to/project",
  "version": "2.1.59"
}
```

For assistant messages, `content` may be an array of content blocks:

```json
{
  "content": [
    {"type": "thinking", "text": "..."},
    {"type": "text", "text": "The actual response..."},
    {"type": "tool_use", "name": "Read", "input": {...}}
  ]
}
```

**What to extract from conversations:**

- Filter to `type: "user"` and `type: "assistant"` entries only
- For assistant entries, extract `text` blocks (skip `thinking` and `tool_use` — those are noise)
- The `cwd` field tells you which project this conversation belongs to
- The project directory name (e.g., `-Users-name-Documents-projects-my-app`) tells you the project path

**Skip these:**

- `type: "progress"` — internal agent progress updates
- `type: "file-history-snapshot"` — file state tracking
- Subagent conversations (under `subagents/` subdirectories) — unless the user specifically asks

## Step 3b: Parse Audit Logs (desktop sessions only)

For each `audit.jsonl` found under `local-agent-mode-sessions/`, read it line by line. Each line is a JSON record of one agent action:

```json
{
  "type": "tool_call",
  "toolName": "Bash",
  "input": {"command": "npm test"},
  "output": "...",
  "timestamp": "2026-04-10T14:22:00Z",
  "sessionId": "..."
}
```

**What to extract from audit logs:**

- **File access patterns** — which files does the agent repeatedly Read or Edit? These are the high-value files in the project. Note them as project references.
- **Shell commands** — recurring Bash commands reveal the project's build/test/deploy workflow. Distill these into a `skills/` page (e.g. "how this project is built and tested").
- **Tool call sequences** — if the agent always does Read → Edit → Bash in a particular order, that's a workflow pattern worth capturing.
- **Error patterns** — failed tool calls (non-zero exit codes, error outputs) reveal pain points, known rough edges, or recurring bugs.
- **MCP tool calls** — calls to MCP tools reveal which external services and APIs the project integrates with.

**Skip from audit logs:**

- Routine file reads with no pattern (e.g. reading config files once)
- Tool outputs that are just noise (long stack traces, verbose logs) — summarize the error class, not the full output
- Anything that looks like secrets, tokens, or credentials in command arguments or outputs

**Cross-reference with the conversation transcript:** The audit log tells you *what happened*; the conversation tells you *why*. When both are available for the same session, use them together — the audit log grounds the conversation in concrete actions.

Read the paired `local_<uuid>.json` session metadata before processing the audit log — it gives you `cwd`, `startedAt`, and `title` to contextualize the actions.

## Step 4: Cluster by Topic

Don't create one wiki page per conversation. Instead:

- Group extracted knowledge **by topic** across conversations
- A single conversation about "debugging auth + setting up CI" → two separate topics
- Three conversations across different days about "React performance" → one merged topic
- The project directory name gives you a natural first-level grouping

## Step 5: Distill into Wiki Pages

Each Claude project maps to a project directory in the vault. The project directory name from `~/.claude/projects/` encodes the original path — decode it to get a clean project name:

```
-Users/Documents/projects/my-Project   → myproject
-Users/Documents/projects/Another-app  → anotherapp
```

### Project-specific vs. global knowledge

| What you found                     | Where it goes               | Example                                             |
| ---------------------------------- | --------------------------- | --------------------------------------------------- |
| Project architecture decisions     | `projects/<name>/concepts/` | `projects/my-project/concepts/main-architecture.md` |
| Project-specific debugging         | `projects/<name>/skills/`   | `projects/my-project/skills/api-rate-limiting.md`   |
| General concept the user learned   | `concepts/` (global)        | `concepts/react-server-components.md`               |
| Recurring problem across projects  | `skills/` (global)          | `skills/debugging-hydration-errors.md`              |
| A tool/service used                | `entities/` (global)        | `entities/vercel-functions.md`                      |
| Patterns across many conversations | `synthesis/` (global)       | `synthesis/common-debugging-patterns.md`            |

For each project with content, create or update the project overview page at `projects/<name>/<name>.md` — **named after the project, not `_project.md`**. Obsidian's graph view uses the filename as the node label, so `_project.md` makes every project show up as `_project` in the graph. Naming it `<name>.md` gives each project a distinct, readable node name.

**Important:** Distill the _knowledge_, not the conversation. Don't write "In a conversation on March 15, the user asked about X." Write the knowledge itself, with the conversation as a source attribution.

**Write a `summary:` frontmatter field** on every new/updated page — 1–2 sentences, ≤200 chars, answering "what is this page about?" for a reader who hasn't opened it. `wiki-query`'s cheap retrieval path reads this field to avoid opening page bodies.

**Add confidence and lifecycle fields** to every new page's frontmatter:
```yaml
base_confidence: 0.42
lifecycle: draft
lifecycle_changed: <ISO date today>
```
On update, leave `lifecycle` and `lifecycle_changed` unchanged — only a human editor transitions lifecycle state.

**Mark provenance** per the convention in `llm-wiki` (Provenance Markers section):

- **Memory files** are mostly extracted — the user wrote them by hand and they're already distilled. Treat memory-derived claims as extracted unless you're stitching together claims from multiple memory files.
- **Conversation distillation** is mostly inferred. You're synthesizing a coherent claim from many turns of dialogue, often filling in implicit reasoning. Apply `^[inferred]` liberally to synthesized patterns, generalizations across sessions, and "what the user really meant" interpretations.
- Use `^[ambiguous]` when the user changed their mind across sessions or when assistant and user contradicted each other and the resolution is unclear.
- Write a `provenance:` frontmatter block on every new/updated page summarizing the rough mix.

## Step 6: Update Manifest, Journal, and Special Files

### Update `.manifest.json`

For each source file processed, add/update its entry with:

- `ingested_at`, `size_bytes`, `modified_at`
- `source_type`: one of `"claude_conversation"`, `"claude_memory"`, `"claude_audit_log"`, `"claude_desktop_session"`
- `project`: the decoded project name
- `pages_created` and `pages_updated` lists

Also update the `projects` section of the manifest:

```json
{
  "project-name": {
    "source_path": "~/.claude/projects/-Users-...",
    "vault_path": "projects/project-name",
    "last_ingested": "TIMESTAMP",
    "conversations_ingested": 5,
    "conversations_total": 8,
    "memory_files_ingested": 3,
    "desktop_sessions_ingested": 2,
    "audit_logs_ingested": 2
  }
}
```

### Create journal entry + update special files

Update `index.md` and `log.md` per the standard process:

```
- [TIMESTAMP] CLAUDE_HISTORY_INGEST projects=N conversations=M desktop_sessions=D audit_logs=A pages_updated=X pages_created=Y mode=append|full
```

**`hot.md`** — Read `$OBSIDIAN_VAULT_PATH/hot.md` (create from the template in `wiki-ingest` if missing). Update **Recent Activity** with a one-line summary — e.g. "Ingested 5 Claude conversations across 2 projects; surfaced patterns in API design and testing strategy." Keep the last 3 operations. Update **Active Threads** if any ongoing project is now better understood. Update `updated` timestamp.

## Privacy

- Distill and synthesize — don't copy raw conversation text verbatim
- Skip anything that looks like secrets, API keys, passwords, tokens
- If you encounter personal/sensitive content, ask the user before including it
- The user's conversations may reference other people — be thoughtful about what goes in the wiki

## Reference

See `references/claude-data-format.md` for more details on the data structures.
