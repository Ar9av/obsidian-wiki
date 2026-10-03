---
title: >-
  Tool Calling
category: concepts
tags: [agents, tooling]
sources:
  - "url:https://docs.anthropic.com/en/docs/build-with-claude/tool-use"
summary: >-
  The model emits a structured request to run a named function; the host runs it and returns the result as the next message.
provenance:
  extracted: 0.85
  inferred: 0.15
  ambiguous: 0.0
base_confidence: 0.85
lifecycle: verified
lifecycle_changed: 2026-05-14
created: 2026-04-09T09:00:00Z
updated: 2026-05-14T09:00:00Z
---

# Tool Calling

Tool calling lets a model act beyond text. The host declares tools (a name, a description, and an input schema), the model replies with a structured call, the host executes it, and the result goes back into the conversation.

## Key Ideas

- The model never executes anything itself; the host decides whether and how to run each call.
- The description and schema are the model's only documentation, so they decide whether it picks the right tool. See [[skills/writing-tool-schemas]].
- Inputs are typically validated against [[references/json-schema-basics]] before execution.
- Tools fail. Network errors, rate limits, and bad arguments need a clear, model-readable error message ([[references/http-status-codes-for-tool-errors]]) and a retry policy ([[skills/retry-and-backoff-for-tool-calls]]).
- [[entities/model-context-protocol]] standardizes how hosts discover and call tools served by other processes.

## Related

- [[concepts/context-window]]: tool definitions and results both consume it.
- [[journal/2026-05-14-tool-schema-debugging]]

## Sources

- [https://docs.anthropic.com/en/docs/build-with-claude/tool-use](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
