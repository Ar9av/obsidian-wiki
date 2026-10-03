---
title: >-
  Retrieval-Augmented Generation
category: concepts
tags: [retrieval, llm]
sources:
  - "url:https://arxiv.org/abs/2005.11401"
summary: >-
  Fetching relevant passages at query time and placing them in the prompt, so answers rest on documents rather than model memory.
provenance:
  extracted: 0.75
  inferred: 0.25
  ambiguous: 0.0
base_confidence: 0.8
lifecycle: reviewed
lifecycle_changed: 2026-05-02
created: 2026-04-08T09:00:00Z
updated: 2026-05-02T09:00:00Z
---

# Retrieval-Augmented Generation

Retrieval-augmented generation (RAG) splits answering into two steps: retrieve passages relevant to the query, then generate an answer conditioned on them. It was introduced by Lewis et al. (2020).

## Key Ideas

- Retrieval keeps the [[concepts/context-window]] small by loading only the passages a query needs.
- Answer quality is bounded by retrieval quality: if the right chunk isn't retrieved, the model can't use it.
- Grounding answers in retrieved text reduces, but doesn't eliminate, [[concepts/hallucination]]. ^[inferred]
- Each query starts from raw chunks, so synthesis across documents is redone every time. That cost motivates compiling knowledge ahead of time ([[synthesis/rag-vs-compiled-wiki]]). ^[inferred]

## Related

- [[concepts/agent-memory]]
- [[entities/andrej-karpathy]]: the LLM Wiki gist argues for compilation over per-query retrieval.
- [[skills/evaluating-agents-with-golden-sets]]: how to measure whether retrieval is actually helping.

## Sources

- [https://arxiv.org/abs/2005.11401](https://arxiv.org/abs/2005.11401)
