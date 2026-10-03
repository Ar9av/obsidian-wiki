---
title: >-
  Andrej Karpathy
category: entities
tags: [knowledge-management, llm]
sources:
  - "url:https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f"
summary: >-
  AI researcher whose LLM Wiki gist describes having an LLM compile sources into a maintained, interlinked markdown wiki.
provenance:
  extracted: 0.85
  inferred: 0.15
  ambiguous: 0.0
base_confidence: 0.8
lifecycle: reviewed
lifecycle_changed: 2026-04-08
created: 2026-04-08T09:00:00Z
updated: 2026-04-08T09:00:00Z
---

# Andrej Karpathy

Andrej Karpathy is an AI researcher and educator. He was a founding member of OpenAI and later led AI for Autopilot at Tesla. For this vault his relevance is one document: the **LLM Wiki** gist.

## Key Ideas

- The gist proposes that an LLM incrementally builds and maintains a wiki from raw sources, rather than re-deriving answers from the sources on every question.
- It separates raw sources, the LLM-maintained wiki, and a schema file that tells the LLM how to maintain it.
- It suggests [[entities/obsidian]] as the place a human browses the result.
- The argument is essentially compile-once versus retrieve-every-time; see [[synthesis/rag-vs-compiled-wiki]]. ^[inferred]

## Related

- [[concepts/retrieval-augmented-generation]]
- [[concepts/agent-memory]]

## Sources

- [https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
