---
title: >-
  2026-05-14 Tool Schema Debugging
category: journal
tags: [tooling, agents]
sources:
  - "conversation:2026-05-14"
summary: >-
  Session note: an agent kept calling the wrong search tool; the fix was in the descriptions, not the prompt.
provenance:
  extracted: 0.7
  inferred: 0.3
  ambiguous: 0.0
base_confidence: 0.6
lifecycle: reviewed
lifecycle_changed: 2026-05-14
created: 2026-05-14T09:00:00Z
updated: 2026-05-14T09:00:00Z
---

# 2026-05-14 Tool Schema Debugging

*Session note.*

## What happened

An agent with `search_docs` and `search_tickets` kept searching docs for customer issues. Prompt changes didn't help.

## Cause

Both descriptions said "Search for information." The model had nothing to tell them apart. ^[inferred]

## Fix

Rewrote both per [[skills/writing-tool-schemas]]: what each searches, when to use it, and one example query each. Added `enum` for the ticket status filter ([[references/json-schema-basics]]). Wrong-tool calls stopped on the golden set ([[skills/evaluating-agents-with-golden-sets]]).

## Takeaway

When the model picks the wrong tool, read the tool definitions before touching the prompt.

## Related

- [[concepts/tool-calling]]

## Sources

- conversation:2026-05-14
