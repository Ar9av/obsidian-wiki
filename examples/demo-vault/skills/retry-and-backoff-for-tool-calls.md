---
title: >-
  Retry and Backoff for Tool Calls
category: skills
tags: [reliability, tooling]
sources:
  - "url:https://datatracker.ietf.org/doc/html/rfc9110"
summary: >-
  Retrying transient tool failures with exponential backoff and jitter, and surfacing permanent ones to the model instead.
provenance:
  extracted: 0.75
  inferred: 0.25
  ambiguous: 0.0
base_confidence: 0.8
lifecycle: verified
lifecycle_changed: 2026-05-14
created: 2026-04-25T09:00:00Z
updated: 2026-05-14T09:00:00Z
---

# Retry and Backoff for Tool Calls

Tool calls fail for two different reasons, and each needs a different response.

## Steps

1. **Classify the failure.** Timeouts, `429`, and `5xx` responses are usually transient. `4xx` errors other than `429` mean the request itself is wrong ([[references/http-status-codes-for-tool-errors]]).
2. **Retry transient failures** with exponential backoff (for example 1s, 2s, 4s) plus random jitter, so many clients don't retry in lockstep.
3. **Honor `Retry-After`** when the server sends it.
4. **Cap attempts** at 3–5 so a dead dependency doesn't stall the loop.
5. **Don't retry bad requests.** Return a clear error to the model so it can fix its arguments.
6. **Make writes idempotent** (an idempotency key, or a check-before-create step) before retrying them.

## Key Ideas

- The model is a poor retry loop: it spends tokens and may change arguments between attempts. Retry in the host. ^[inferred]

## Related

- [[concepts/tool-calling]]
- [[skills/evaluating-agents-with-golden-sets]]

## Sources

- [https://datatracker.ietf.org/doc/html/rfc9110](https://datatracker.ietf.org/doc/html/rfc9110)
