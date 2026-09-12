---
title: Eventual Consistency
category: concepts
tags: [distributed-systems, correctness]
sources: [bench-fixture]
created: 2026-01-05
updated: 2026-06-01
tier: supporting
summary: Replicas converge on the same value given no new writes, so a read may briefly return a stale value.
---
# Eventual Consistency

Replicas converge on the same value given no new writes, so a read may briefly return a stale value.

- [[idempotency]]
- [[reliability-tradeoffs]]
