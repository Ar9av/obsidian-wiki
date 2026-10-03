---
title: >-
  Where Agent Memory Should Live
category: synthesis
tags: [memory, agents, knowledge-management]
sources:
  - "conversation:2026-06-02"
summary: >-
  Trade-offs between vector stores, databases, and plain markdown as the home for an agent's long-term memory.
provenance:
  extracted: 0.35
  inferred: 0.5
  ambiguous: 0.15
base_confidence: 0.5
lifecycle: draft
lifecycle_changed: 2026-06-02
created: 2026-06-02T09:00:00Z
updated: 2026-06-02T09:00:00Z
---

# Where Agent Memory Should Live

Where [[concepts/agent-memory]] is stored decides who can read it, fix it, and trust it.

## Options

- **Vector store**: good for fuzzy recall over large, unstructured text. Opaque to humans, and hard to correct one fact at a time. ^[inferred]
- **Database or event log**: precise and queryable. Good for structured facts; poor for narrative knowledge.
- **Markdown files** (for example an [[entities/obsidian]] vault): readable, diffable, and editable by the human and the agent alike. Search is weaker without an index.

## Finding

Durable knowledge the human should be able to audit belongs in plain files with provenance. High-volume episodic traces can live in a log, then be distilled into pages. ^[inferred] Whether a vector index over the files is worth its complexity depends on vault size. ^[ambiguous]

## Related

- [[synthesis/rag-vs-compiled-wiki]]
- [[journal/2026-06-02-memory-design-review]]
- [[concepts/context-window]]

## Sources

- conversation:2026-06-02
