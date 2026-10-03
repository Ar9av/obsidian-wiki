---
title: >-
  Context Window
category: concepts
tags: [llm, agents]
sources:
  - "url:https://docs.anthropic.com/en/docs/build-with-claude/context-windows"
summary: >-
  The bounded token budget a model reads per call; everything an agent knows in the moment has to fit inside it.
provenance:
  extracted: 0.8
  inferred: 0.2
  ambiguous: 0.0
base_confidence: 0.85
lifecycle: verified
lifecycle_changed: 2026-05-20
created: 2026-04-08T09:00:00Z
updated: 2026-05-20T09:00:00Z
---

# Context Window

The context window is the maximum number of tokens a model can attend to in a single request: the system prompt, conversation history, tool definitions, tool results, and the model's own output all draw from the same budget.

## Key Ideas

- Every turn re-sends the history, so long agent loops grow the context until something has to be dropped or summarized.
- Tool results are often the biggest consumer. A single unfiltered API response can crowd out the instructions that matter. ^[inferred]
- Larger windows don't remove the need for curation; models can attend less reliably to material buried in the middle of a long context. ^[ambiguous]
- [[concepts/prompt-caching]] makes a stable prefix cheaper to re-send, but doesn't make the window bigger.
- Knowledge that must survive past one window belongs in [[concepts/agent-memory]], not in the transcript.

## Related

- [[concepts/retrieval-augmented-generation]]: fetches only what fits.
- [[synthesis/rag-vs-compiled-wiki]]
- [[concepts/hallucination]]: what a model does when the needed fact isn't in the window.

## Sources

- [https://docs.anthropic.com/en/docs/build-with-claude/context-windows](https://docs.anthropic.com/en/docs/build-with-claude/context-windows)
