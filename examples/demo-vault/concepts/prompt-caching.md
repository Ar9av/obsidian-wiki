---
title: >-
  Prompt Caching
category: concepts
tags: [llm, reliability]
sources:
  - "url:https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching"
summary: >-
  Reusing the processed form of an unchanged prompt prefix across requests to cut latency and cost.
provenance:
  extracted: 0.7
  inferred: 0.3
  ambiguous: 0.0
base_confidence: 0.55
lifecycle: draft
lifecycle_changed: 2026-04-15
created: 2026-04-15T09:00:00Z
updated: 2026-04-15T09:00:00Z
---

# Prompt Caching

Prompt caching lets a provider reuse work done on a prompt prefix that hasn't changed since a recent request. Agent loops resend the same system prompt and tool definitions on every turn, so the savings compound.

## Key Ideas

- Only an identical prefix can be reused. Put stable material (instructions, tool definitions, reference documents) first and volatile material last.
- Caches expire after a time-to-live, so a cache only pays off when requests arrive frequently. ^[inferred]
- Reordering tools or editing the system prompt invalidates the cache, which can look like a sudden cost spike. ^[inferred]
- Caching saves cost and time; it doesn't extend the [[concepts/context-window]].

## Related

- [[concepts/tool-calling]]: tool definitions are a natural cache prefix.
- [[skills/writing-tool-schemas]]

## Sources

- [https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
