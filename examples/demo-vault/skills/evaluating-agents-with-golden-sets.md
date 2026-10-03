---
title: >-
  Evaluating Agents with Golden Sets
category: skills
tags: [evaluation, reliability]
sources:
  - "conversation:2026-05-02"
summary: >-
  Building a fixed set of tasks with known-good outcomes and re-running it on every change to catch regressions.
provenance:
  extracted: 0.55
  inferred: 0.4
  ambiguous: 0.05
base_confidence: 0.7
lifecycle: reviewed
lifecycle_changed: 2026-05-20
created: 2026-05-02T09:00:00Z
updated: 2026-05-20T09:00:00Z
---

# Evaluating Agents with Golden Sets

A golden set is a fixed collection of inputs paired with known-good outcomes. Re-running it after each prompt, tool, or model change turns "it feels better" into a number.

## Steps

1. Collect 20–50 real tasks, including the failures that prompted the work.
2. For each, write what counts as success: an exact answer, a required tool call, or a rubric.
3. Run the agent on every task, several times, because outputs vary between runs.
4. Score automatically where possible. Use a model grader only with a written rubric, and spot-check it.
5. Track pass rate and cost per change. Never delete a failing case just to raise the score.

## Key Ideas

- Small sets catch big regressions; they can't resolve small differences. ^[inferred]
- Measure [[concepts/hallucination]] directly: include questions whose correct answer is "not in the sources".
- Check whether [[concepts/retrieval-augmented-generation]] actually retrieved the right passage, not just whether the answer looked right.

## Related

- [[skills/retry-and-backoff-for-tool-calls]]: flaky tools make evals flaky.
- [[synthesis/rag-vs-compiled-wiki]]

## Sources

- conversation:2026-05-02
