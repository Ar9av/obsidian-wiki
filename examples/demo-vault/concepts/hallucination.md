---
title: >-
  Hallucination
category: concepts
tags: [llm, reliability]
sources:
  - "conversation:2026-04-20"
summary: >-
  Fluent output that is unsupported or false; the model fills a gap with something plausible instead of saying it doesn't know.
provenance:
  extracted: 0.6
  inferred: 0.3
  ambiguous: 0.1
base_confidence: 0.7
lifecycle: reviewed
lifecycle_changed: 2026-05-02
created: 2026-04-20T09:00:00Z
updated: 2026-05-02T09:00:00Z
---

# Hallucination

Hallucination is output that sounds confident but isn't supported by the input or by fact: an invented citation, an API parameter that doesn't exist, a function the codebase never had.

## Key Ideas

- It is most likely when the needed fact is absent from the [[concepts/context-window]] and the question invites a specific answer.
- Grounding with [[concepts/retrieval-augmented-generation]] or a compiled wiki gives the model something real to cite. ^[inferred]
- Tool calls can hallucinate too: wrong argument names, made-up enum values. Strict schemas catch many of these before execution ([[references/json-schema-basics]]).
- Asking for citations makes unsupported claims easier to spot, though models can also fabricate the citations. ^[ambiguous]
- The only reliable way to know the rate on your task is to measure it ([[skills/evaluating-agents-with-golden-sets]]).

## Related

- [[synthesis/rag-vs-compiled-wiki]]
- [[concepts/agent-memory]]

## Sources

- conversation:2026-04-20
