# Hermes Agent — Data Format Reference

Field-level notes for parsing `~/.hermes/` artifacts during wiki ingest.

## Cache Root

`~/.hermes/` — or `$HERMES_HOME` for non-default profiles. All paths below are relative to this root.

## memories/

Each file is one discrete memory the agent persisted.

### Markdown memories (`*.md`)

Optional YAML frontmatter, then prose body:

```markdown
---
tags: [python, async, debugging]
created_at: 2026-03-10T14:22:00Z
project: my-api
---
When using `asyncio.gather` with return_exceptions=True, failed tasks return the exception
object rather than raising — check `isinstance(result, Exception)` on each item.
```

Fields of interest:
- `tags` — maps directly to wiki tags; normalize to kebab-case
- `created_at` — use for provenance / journal category decisions
- `project` — route to `projects/<project>/` when set

### JSON memories (`*.json`)

```json
{
  "content": "...",
  "created_at": "2026-03-10T14:22:00Z",
  "tags": ["python", "async"],
  "project": "my-api",
  "source": "session:abc123"
}
```

Same field semantics as the markdown variant. `source` links back to the originating session.

## sessions/

Present only when session logging is enabled (`config.yaml: logging.sessions: true`).

### Directory layout

```
sessions/
└── 2026-03-10/
    └── abc123.jsonl
```

### JSONL line schemas

**User / assistant turns:**

```json
{"role": "user",      "content": "How do I debounce a React input?"}
{"role": "assistant", "content": "Use useCallback + useEffect with a setTimeout..."}
```

**Tool use:**

```json
{
  "type": "tool_use",
  "id": "tu_abc",
  "name": "read_file",
  "input": {"path": "/home/ubuntu/project/src/App.tsx"}
}
```

**Tool result:**

```json
{
  "type": "tool_result",
  "tool_use_id": "tu_abc",
  "content": "..."
}
```

**Session metadata (first line):**

```json
{
  "type": "session_meta",
  "id": "abc123",
  "cwd": "/home/ubuntu/projects/my-app",
  "model": "claude-sonnet-4-6",
  "started_at": "2026-03-10T14:00:00Z"
}
```

`cwd` is the most reliable project inference signal — use it to route knowledge to the right `projects/<name>/` page.

## config.yaml

Rarely useful for ingest. Useful fields if needed:

```yaml
model: claude-sonnet-4-6
hermes_home: ~/.hermes        # resolved path, respects $HERMES_HOME
logging:
  sessions: true              # whether session JSONL files are written
  memories: true              # whether memories are persisted
```

## .hub/

Skills Hub state. **Skip entirely during ingest.** Contains:

- `lock.json` — installed skill manifest (not user knowledge)
- `audit.log` — install/update history
- `quarantine/` — flagged skills awaiting review

## Extraction Priority

| Source | Signal | Noise |
|---|---|---|
| `memories/*.md` | High — curated, stable | Low |
| `memories/*.json` | High — structured | Low |
| `sessions/**/*.jsonl` — assistant turns | Medium | Medium |
| `sessions/**/*.jsonl` — tool pairs | Low | High |
| `config.yaml` | Very low | — |
| `.hub/` | None | — |
