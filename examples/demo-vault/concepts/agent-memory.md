---
title: >-
  Agent Memory
category: concepts
tags: [memory, agents]
sources:
  - "conversation:2026-06-02"
summary: >-
  Anything an agent can recall beyond the current context window: notes, profiles, compiled knowledge, or retrieved history.
provenance:
  extracted: 0.6
  inferred: 0.35
  ambiguous: 0.05
base_confidence: 0.7
lifecycle: reviewed
lifecycle_changed: 2026-06-02
created: 2026-04-12T09:00:00Z
updated: 2026-06-02T09:00:00Z
---

# Agent Memory

Agent memory is the state that outlives one [[concepts/context-window]]. Without it, every session starts from zero and the user re-explains themselves.

## Key Ideas

- **Working memory** is the context window itself, which is fast but disappears when the session ends.
- **Episodic memory** records what happened: transcripts, logs, session notes like [[journal/2026-06-02-memory-design-review]].
- **Semantic memory** holds distilled facts and concepts, which is what a compiled wiki provides. ^[inferred]
- Memory is only useful if it is retrievable at the right moment: by search, by an index, or by injecting a short recap at session start.
- Stale or wrong memories are worse than none, because the agent trusts them. Provenance and review state help an agent judge what to rely on. ^[inferred]
- How much to store automatically versus on request is unsettled; aggressive capture fills memory with noise. ^[ambiguous]

## Related

- [[synthesis/where-agent-memory-should-live]]
- [[concepts/retrieval-augmented-generation]]
- [[entities/obsidian]]: a human-readable home for semantic memory.

## Sources

- conversation:2026-06-02
