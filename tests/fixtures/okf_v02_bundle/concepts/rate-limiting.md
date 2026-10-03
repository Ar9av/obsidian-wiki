---
type: Concept
title: Rate Limiting
description: Token-bucket and sliding-window approaches to capping request rates.
tags: [backend, reliability]
generated:
  by: obsidian-wiki/2026.6.10.dev10+g9a915c953
  at: 2026-04-12T00:00:00Z
status: stable
verified:
  by: "human:vault-owner"
  at: 2026-04-12T15:00:00+00:00
sources:
  - resource: "https://example.com/rate-limits"
  - resource: "conversation:2026-04-12"
resource: "https://example.com/rate-limits"
category: concepts
created: 2026-04-10
updated: 2026-04-12
lifecycle: verified
lifecycle_changed: 2026-04-12
base_confidence: 0.8
---

# Rate Limiting

Token buckets refill at a fixed rate. See [Redis](../entities/redis.md) and [Exponential Backoff](backoff.md).

## Related
- [Redis](../entities/redis.md)
