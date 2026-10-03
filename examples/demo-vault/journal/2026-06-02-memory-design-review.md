---
title: >-
  2026-06-02 Memory Design Review
category: journal
tags: [memory, agents]
sources:
  - "conversation:2026-06-02"
summary: >-
  Session note: deciding to keep durable agent memory as markdown pages with provenance, and recap it at session start.
provenance:
  extracted: 0.6
  inferred: 0.3
  ambiguous: 0.1
base_confidence: 0.5
lifecycle: draft
lifecycle_changed: 2026-06-02
created: 2026-06-02T09:00:00Z
updated: 2026-06-02T09:00:00Z
---

# 2026-06-02 Memory Design Review

*Session note.*

## Question

Should the assistant's long-term memory go in a vector store or in the notes vault?

## Decision

Keep durable facts and decisions as markdown pages in the vault, with provenance markers, and inject a short recap at session start. Keep raw transcripts as episodic logs and distill them on request. See [[synthesis/where-agent-memory-should-live]].

## Why

Wrong memories need to be easy to find and fix, and a human can't audit embeddings. ^[inferred]

## Open

Whether to add a search index once the vault passes a few thousand pages. ^[ambiguous]

## Related

- [[concepts/agent-memory]]
- [[entities/obsidian]]

## Sources

- conversation:2026-06-02
