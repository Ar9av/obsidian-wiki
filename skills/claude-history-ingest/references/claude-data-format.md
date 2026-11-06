# Claude Code Data Format — Detailed Reference

## Projects Directory

`~/.claude/projects/` contains one directory per project the user has opened with Claude Code. Directory names encode the absolute path:

```
/Users/name/Documents/projects/my-app → -Users/name/Documents/projects/my-app
```

To recover the original path: replace leading `-` with `/`, then replace remaining `-` cautiously (dashes also appear in directory names). The `cwd` field in session/conversation data gives you the canonical path.

### Conversation JSONL Files

Located at `~/.claude/projects/<project-dir>/<session-uuid>.jsonl`.

Each line is one event. Relevant event types:

| `type`                  | What it is                  | Worth reading?                           |
| ----------------------- | --------------------------- | ---------------------------------------- |
| `user`                  | User message                | Yes — this is what the user asked/said   |
| `assistant`             | Assistant response          | Yes — extract `text` blocks from content |
| `progress`              | Tool execution progress     | No — internal plumbing                   |
| `file-history-snapshot` | File state at session start | No — just file listings                  |

#### User message structure

```json
{
  "type": "user",
  "message": { "role": "user", "content": "the user's message as a string" },
  "timestamp": "2026-03-15T10:30:00.000Z",
  "sessionId": "uuid",
  "cwd": "/Users/name/Documents/projects/my-app"
}
```

#### Assistant message structure

```json
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "content": [
      { "type": "thinking", "text": "internal reasoning (skip this)" },
      { "type": "text", "text": "The actual visible response" },
      {
        "type": "tool_use",
        "id": "...",
        "name": "Read",
        "input": { "file_path": "..." }
      }
    ]
  },
  "timestamp": "2026-03-15T10:30:05.000Z"
}
```

**Extraction strategy:** Only pull `text` type blocks from assistant content arrays. The `thinking` blocks are internal reasoning and `tool_use` blocks are mechanical actions — neither adds wiki-worthy knowledge.

### Memory Files

Located at `~/.claude/projects/<project-dir>/memory/`.

Each memory file has YAML frontmatter:

```markdown
---
name: descriptive-name
description: one-line summary used for relevance matching
type: user|feedback|project|reference
---

The memory content. For feedback/project types, structured as:
rule/fact, then **Why:** and **How to apply:** lines.
```

**Memory types and their wiki value:**

| Type        | Contains                                 | Maps to wiki                                           |
| ----------- | ---------------------------------------- | ------------------------------------------------------ |
| `user`      | User's role, preferences, expertise      | Entity page about the user, or context for other pages |
| `feedback`  | Workflow corrections and confirmations   | Skills pages — "how to work effectively"               |
| `project`   | Active work, goals, decisions, deadlines | Entity pages for projects                              |
| `reference` | Pointers to external resources           | Reference pages                                        |

`MEMORY.md` in each memory directory is an index with one-line summaries. Read it first to triage.

### Session Metadata

Located at `~/.claude/sessions/<pid>.json`. Light metadata:

```json
{
  "pid": 12345,
  "sessionId": "uuid",
  "cwd": "/Users/name/Documents/projects/my-app",
  "startedAt": "2026-03-15T10:30:00.000Z",
  "kind": "interactive",
  "entrypoint": "cli"
}
```

Useful for building a timeline of when the user worked on what.

### Global History

`~/.claude/history.jsonl` — append-only log of all sessions. Use for timeline reconstruction.

## Processing Order

For maximum efficiency:

1. **MEMORY.md indexes** — Quick triage of what each project knows
2. **Individual memory files** — Pre-distilled knowledge, highest signal-to-noise
3. **Conversation JSONL** — Rich but verbose, process selectively
4. **Session metadata** — Only if you need timeline context
