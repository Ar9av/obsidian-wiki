# GitHub Copilot CLI Data Format — Detailed Reference

## Session-State Directory

`~/.copilot/session-state/` contains one directory per session the user has run with GitHub Copilot CLI. Each directory is named with a UUID.

### `workspace.yaml`

Minimal session metadata file, always present:

```yaml
id: <session-uuid>
cwd: /path/to/project
summary_count: 3
created_at: 2026-04-02T14:28:13.304Z
updated_at: 2026-04-29T12:00:00.000Z
```

`summary_count` reflects how many checkpoints were written. Sessions with `summary_count: 0` were either very short or completed without checkpointing — check `events.jsonl` for content anyway.

### `vscode.metadata.json`

VS Code context, written when the session is associated with a VS Code workspace:

```json
{
  "workspaceFolder": {
    "folderPath": "c:\\Users\\name\\git\\my-project",
    "timestamp": 1773245818098
  },
  "writtenToDisc": true,
  "repositoryProperties": {
    "repositoryPath": "c:\\Users\\name\\git\\my-project",
    "branchName": "feature/my-branch",
    "baseBranchName": "origin/main"
  },
  "customTitle": "User-written session label or system-set title"
}
```

`customTitle` is the most human-readable session label — use it as a heading when creating session-derived wiki content. May be absent on older sessions.

### `events.jsonl`

The full event log for one session. Each line is a JSON object representing one event in the session.

#### Event: `session.start`

```json
{
  "type": "session.start",
  "data": {
    "sessionId": "09371a50-9a50-484a-8743-5c696de1623a",
    "version": 1,
    "producer": "copilot-agent",
    "copilotVersion": "0.0.420",
    "startTime": "2026-03-02T15:10:04.678Z",
    "context": {
      "cwd": "C:\\Users\\name\\git\\my-project",
      "gitRoot": "C:\\Users\\name\\git\\my-project",
      "branch": "master"
    }
  },
  "id": "<event-uuid>",
  "timestamp": "2026-03-02T15:10:04.817Z",
  "parentId": null
}
```

`data.context.cwd` and `data.context.branch` establish the project context. Always read `session.start` first.

#### Event: `user.message`

```json
{
  "type": "user.message",
  "data": {
    "content": "review my staged but uncommitted changes for issues",
    "transformedContent": "<current_datetime>...</current_datetime>\n\nreview my staged...",
    "attachments": [],
    "interactionId": "9352571e-a0b9-4774-8ecb-40bc58f86e94"
  },
  "id": "<event-uuid>",
  "timestamp": "2026-03-02T15:10:45.058Z",
  "parentId": "<parent-event-uuid>"
}
```

Use `data.content` (not `data.transformedContent`) — the transformed version includes injected system context that's noise for wiki purposes.

#### Event: `assistant.message`

```json
{
  "type": "assistant.message",
  "data": {
    "messageId": "<uuid>",
    "content": "I'll review the staged changes in those three files.",
    "toolRequests": [
      {
        "toolCallId": "tooluse_...",
        "name": "report_intent",
        "arguments": { "intent": "Reviewing staged changes" },
        "type": "function"
      },
      {
        "toolCallId": "tooluse_...",
        "name": "powershell",
        "arguments": {
          "command": "git --no-pager diff --cached --stat",
          "description": "Show staged diff"
        },
        "type": "function"
      }
    ],
    "interactionId": "9352571e-a0b9-4774-8ecb-40bc58f86e94",
    "reasoningOpaque": "<base64-encrypted-reasoning>",
    "reasoningText": "The user wants me to review staged git changes..."
  },
  "id": "<event-uuid>",
  "timestamp": "2026-03-02T15:10:50.235Z",
  "parentId": "<parent-event-uuid>"
}
```

**Extraction strategy:**

- Extract `data.content` — the assistant's visible text response
- `data.toolRequests` — skim tool names and description arguments for file/command patterns; ignore `report_intent` calls
- **Skip `data.reasoningOpaque` entirely** — encrypted/encoded internal reasoning
- **Skip `data.reasoningText` entirely** — decrypted reasoning; internal only, never user-visible

#### Event: `assistant.turn_start`

```json
{
  "type": "assistant.turn_start",
  "data": { "turnId": "0", "interactionId": "..." },
  "id": "...",
  "timestamp": "..."
}
```

Marks the start of an assistant turn. Useful for turn boundary detection; no content to extract.

#### Event: `tool.execution_start`

```json
{
  "type": "tool.execution_start",
  "data": {
    "toolCallId": "tooluse_...",
    "toolName": "powershell",
    "arguments": { "command": "dotnet build ...", "description": "Build project" }
  },
  "id": "...",
  "timestamp": "..."
}
```

Reveals what tools (file reads, commands, searches) were invoked. File-related tools (`view`, `edit`, `create`) with their paths are worth noting for the `session_files` equivalent when reading events directly.

#### Event: `tool.execution_end`

Contains the raw tool output. Usually noise — skip unless diagnosing errors.

### `checkpoints/<uuid>.json`

Mid-session progress summaries, written automatically as the session progresses:

```json
{
  "title": "Implementing auth module",
  "overview": "Working on JWT authentication for the API...",
  "history": "1. Analyzed existing auth code\n2. Created IAuthService...",
  "work_done": "- Created IAuthService interface\n- Implemented JwtAuthService",
  "technical_details": "Uses RS256 signing. Token expiry configurable via settings...",
  "important_files": "- src/Auth/IAuthService.cs\n- src/Auth/JwtAuthService.cs",
  "next_steps": "- Wire up to DI container\n- Add refresh token support"
}
```

This is the highest-value structured content in the per-session directory — equivalent to Claude's memory files.

### `index.md`

Session-end summary written as a markdown file. Typically 1–3 paragraphs summarizing what was accomplished. Content varies by session length and complexity. Read this before opening `events.jsonl` to decide if the session is worth deep-processing.

---

## Global Session Store (`session-store.db`)

SQLite database at `~/.copilot/session-store.db`. The canonical cross-session record.

### Schema

#### `sessions`

| Column      | Type | Notes                                      |
| ----------- | ---- | ------------------------------------------ |
| `id`        | TEXT | Session UUID (PK)                          |
| `cwd`       | TEXT | Working directory                          |
| `repository`| TEXT | `owner/repo` format when available         |
| `branch`    | TEXT | Git branch name                            |
| `summary`   | TEXT | One-paragraph session summary              |
| `created_at`| TEXT | ISO 8601 timestamp                         |
| `updated_at`| TEXT | ISO 8601 timestamp — use for delta checks  |
| `host_type` | TEXT | `"vscode"`, `"cli"`, or similar            |

#### `turns`

| Column              | Type    | Notes                          |
| ------------------- | ------- | ------------------------------ |
| `id`                | INTEGER | PK                             |
| `session_id`        | TEXT    | FK → `sessions.id`             |
| `turn_index`        | INTEGER | 0-based turn sequence          |
| `user_message`      | TEXT    | Raw user message               |
| `assistant_response`| TEXT    | Assistant's text response      |
| `timestamp`         | TEXT    | ISO 8601 timestamp             |

Note: `user_message` here is the pre-transformation content — use this, not `transformedContent` from `events.jsonl`.

#### `checkpoints`

| Column              | Type    | Notes                          |
| ------------------- | ------- | ------------------------------ |
| `id`                | INTEGER | PK                             |
| `session_id`        | TEXT    | FK → `sessions.id`             |
| `checkpoint_number` | INTEGER | 1-based                        |
| `title`             | TEXT    | Short title                    |
| `overview`          | TEXT    | High-level summary             |
| `history`           | TEXT    | Step-by-step of what happened  |
| `work_done`         | TEXT    | Completed items                |
| `technical_details` | TEXT    | Implementation specifics       |
| `important_files`   | TEXT    | Key files touched              |
| `next_steps`        | TEXT    | Open threads                   |
| `created_at`        | TEXT    | ISO 8601 timestamp             |

#### `session_files`

| Column         | Type    | Notes                                              |
| -------------- | ------- | -------------------------------------------------- |
| `session_id`   | TEXT    | FK → `sessions.id`                                 |
| `file_path`    | TEXT    | Absolute path to the file                          |
| `tool_name`    | TEXT    | `"edit"`, `"create"`, `"view"`, etc.               |
| `turn_index`   | INTEGER | Which turn touched the file                        |
| `first_seen_at`| TEXT    | ISO 8601 timestamp                                 |

> ⚠️ No `id` column — use `COUNT(DISTINCT sf.file_path)` not `COUNT(DISTINCT sf.id)`.

Aggregate by `file_path` across sessions to identify architecturally important files.

#### `session_refs`

| Column       | Type    | Notes                                      |
| ------------ | ------- | ------------------------------------------ |
| `id`         | INTEGER | PK                                         |
| `session_id` | TEXT    | FK → `sessions.id`                         |
| `ref_type`   | TEXT    | `"commit"`, `"pr"`, `"issue"`              |
| `ref_value`  | TEXT    | Commit SHA, PR number, issue number        |
| `turn_index` | INTEGER | Which turn referenced it                   |
| `created_at` | TEXT    | ISO 8601 timestamp                         |

#### `search_index` (FTS5)

Full-text search index. Use for keyword discovery when surveying a large history:

```sql
SELECT content, session_id, source_type
FROM search_index
WHERE search_index MATCH 'auth OR authentication OR login'
LIMIT 20;
```

`source_type` values: `"turn"`, `"checkpoint_overview"`, `"checkpoint_history"`, `"checkpoint_work_done"`, `"checkpoint_technical"`, `"checkpoint_files"`, `"checkpoint_next_steps"`, `"workspace_artifact"`.

---

## VS Code Workspace Storage

### Location

The `workspaceStorage` directory is platform-specific:

| Platform | Default path                                                       |
| -------- | ------------------------------------------------------------------ |
| Windows  | `%APPDATA%\Code\User\workspaceStorage\`                            |
| macOS    | `~/Library/Application Support/Code/User/workspaceStorage/`       |
| Linux    | `~/.config/Code/User/workspaceStorage/`                           |

Each `<hash>/` subdirectory corresponds to a specific workspace (VS Code folder). The hash is derived from the workspace path — there is no human-readable mapping, so enumerate all `<hash>/GitHub.copilot-chat/` directories and use the `transcripts/` JSONL files' `session.start` events to identify which project each belongs to.

### Transcript JSONL (`transcripts/<uuid>.jsonl`)

Identical format to `events.jsonl` from Source 1. Parse using the same event type handlers. The `session.start` event's `data.context.cwd` tells you which project this belongs to.

### Memory Artifacts (`memory-tool/memories/<base64-session-id>/`)

Directory name is the session UUID encoded as base64. Files inside are markdown documents explicitly saved by the user or system during the session — typically `plan.md` containing the session plan.

Decode the directory name to link it to a session:

```python
import base64
# Pad to multiple of 4 before decoding
session_id = base64.b64decode(dir_name + '==').decode('utf-8')
```

---

## Processing Order

For maximum efficiency and signal-to-noise:

1. **`session-store.db` checkpoints** — Fastest, highest signal. Query all at once.
2. **`session-store.db` sessions.summary** — One-paragraph synopsis per session.
3. **Per-session `checkpoints/*.json` + `index.md`** — For sessions not yet in `session-store.db` or for additional detail.
4. **Memory artifacts** (`memory-tool/memories/`) — User-authored, high quality.
5. **`session-store.db` turns** — Full conversation, process selectively by topic.
6. **`events.jsonl` / transcript JSONL** — Only if `session-store.db` is absent or incomplete.
7. **`session_files` / `session_refs`** — For file pattern and git linkage metadata.
