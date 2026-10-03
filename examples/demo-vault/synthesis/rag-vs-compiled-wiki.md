---
title: >-
  RAG vs Compiled Wiki
category: synthesis
tags: [retrieval, knowledge-management, memory]
sources:
  - "url:https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f"
  - "conversation:2026-05-20"
summary: >-
  Retrieval re-derives answers from raw chunks per query; a compiled wiki pays the synthesis cost once and keeps it current.
provenance:
  extracted: 0.45
  inferred: 0.45
  ambiguous: 0.1
base_confidence: 0.65
lifecycle: reviewed
lifecycle_changed: 2026-06-02
created: 2026-05-20T09:00:00Z
updated: 2026-06-02T09:00:00Z
---

# RAG vs Compiled Wiki

Two ways to give an agent knowledge it wasn't trained on.

| | [[concepts/retrieval-augmented-generation\|RAG]] | Compiled wiki |
|---|---|---|
| When synthesis happens | At every query | At ingest, then kept current |
| Unit of storage | Raw chunks | Pages about concepts and entities |
| Cross-document links | Re-found each time | Written down as links |
| Contradictions | Hidden in separate chunks | Can be flagged on the page |
| Human-readable | Rarely | Yes ([[entities/obsidian]]) |
| Cost profile | Cheap ingest, cost on every query | Costly ingest, cheap queries ^[inferred] |

## Finding

For a corpus you return to repeatedly, compiling wins: the expensive reading is done once and improves over time, as [[entities/andrej-karpathy]]'s gist argues. ^[inferred] For a huge, fast-changing corpus you query rarely, plain retrieval is simpler. Many systems combine the two: they retrieve over compiled pages instead of raw chunks. ^[ambiguous]

## Related

- [[concepts/agent-memory]]
- [[concepts/hallucination]]
- [[synthesis/where-agent-memory-should-live]]

## Sources

- [https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- conversation:2026-05-20
