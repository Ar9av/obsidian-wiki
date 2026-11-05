# Codex Data Format — Detailed Reference

This reference describes practical, observed structures for Codex local history ingestion.

## Root Layout

`~/.codex/` usually contains:

- `sessions/YYYY/MM/DD/rollout-*.jsonl` — primary structured session logs
- `archived_sessions/` — archived rollouts
- `session_index.jsonl` — session id/name/update index
- `history.jsonl` — transcript history (depends on config)
- `config.toml` — history persistence controls

## Session Index

`~/.codex/session_index.jsonl` entries are one JSON object per line, commonly:

```json
{"id":"<thread-id>","thread_name":"<title>","updated_at":"<timestamp>"}
```

Use this as the inventory backbone for append/full mode deltas.

## Rollout JSONL

`rollout-*.jsonl` files are event streams with envelope fields:

```json
{
  "timestamp": "2026-04-12T09:40:02.337Z",
  "type": "session_meta|turn_context|event_msg|response_item",
  "payload": { "...": "..." }
}
```

Common `type` values:

- `session_meta` — run metadata (id, cwd, model/provider, etc.)
- `turn_context` — turn-scoped context envelope
- `event_msg` — runtime events (task lifecycle, token/accounting, tool-call markers)
- `response_item` — model response items (messages, tool calls, reasoning blocks)

### Typical payload subtypes

Observed examples include:

- `event_msg.payload.type`: `task_started`, `user_message`, `agent_message`, `mcp_tool_call_end`, `exec_command_end`, `token_count`
- `response_item.payload.type`: `message`, `function_call`, `function_call_output`, `reasoning`

## Extraction Strategy

### Keep

- User intent from user-message records
- Assistant conclusions/decisions from assistant message records
- High-signal tool outputs that encode reusable knowledge

### Skip

- Pure telemetry (`token_count`, low-level plumbing events)
- Internal reasoning traces unless user explicitly asks to retain them
- Verbose execution dumps with no durable insight

## Privacy Notes

Rollouts can contain sensitive data:

- Injected instruction layers
- Tool inputs/outputs
- Potential secrets in command output

Always redact secrets and summarize instead of copying raw transcript content.

## Config Interaction

`~/.codex/config.toml` keys that affect ingestion completeness:

- `history.persistence = "save-all" | "none"`
- `history.max_bytes = <int>` (truncation/compaction cap)

`codex exec --ephemeral` runs may not persist rollout files.
