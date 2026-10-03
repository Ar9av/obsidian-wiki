---
title: >-
  Writing Tool Schemas
category: skills
tags: [tooling, agents]
sources:
  - "url:https://docs.anthropic.com/en/docs/build-with-claude/tool-use"
  - "conversation:2026-05-14"
summary: >-
  How to write tool names, descriptions, and input schemas so a model picks the right tool and fills arguments correctly.
provenance:
  extracted: 0.65
  inferred: 0.35
  ambiguous: 0.0
base_confidence: 0.8
lifecycle: verified
lifecycle_changed: 2026-05-14
created: 2026-04-18T09:00:00Z
updated: 2026-05-14T09:00:00Z
---

# Writing Tool Schemas

A tool definition is the only documentation the model sees, so write it for a reader with no other context.

## Steps

1. **Name it for its action**: `search_orders`, not `orders_v2`.
2. **Say when to use it, and when not to.** If two tools overlap, the description must separate them.
3. **Describe every parameter**, with units, formats, and an example value.
4. **Constrain inputs** with `enum`, `required`, and `additionalProperties: false` ([[references/json-schema-basics]]).
5. **Return errors the model can act on**: what failed and what to try instead ([[references/http-status-codes-for-tool-errors]]).
6. **Test with real prompts** and read which tool the model chose and why.

## Key Ideas

- Most wrong-tool calls trace back to vague or overlapping descriptions, not model weakness. ^[inferred]
- Keep definitions stable so they stay in the [[concepts/prompt-caching]] prefix.

## Related

- [[concepts/tool-calling]]
- [[entities/model-context-protocol]]
- [[journal/2026-05-14-tool-schema-debugging]]

## Sources

- [https://docs.anthropic.com/en/docs/build-with-claude/tool-use](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- conversation:2026-05-14
