---
title: >-
  HTTP Status Codes for Tool Errors
category: references
tags: [reference, reliability]
sources:
  - "url:https://datatracker.ietf.org/doc/html/rfc9110"
summary: >-
  Which HTTP status codes signal a retryable failure and which mean the request must change.
provenance:
  extracted: 0.9
  inferred: 0.1
  ambiguous: 0.0
base_confidence: 0.9
lifecycle: verified
lifecycle_changed: 2026-04-25
created: 2026-04-25T09:00:00Z
updated: 2026-04-25T09:00:00Z
---

# HTTP Status Codes for Tool Errors

When a tool wraps an HTTP API, the status code tells the host whether to retry or hand the error back to the model ([[skills/retry-and-backoff-for-tool-calls]]).

| Code | Meaning | Retry? |
|---|---|---|
| `400` | Bad request: malformed or invalid arguments | No. Tell the model what was wrong |
| `401` / `403` | Not authenticated / not permitted | No. A configuration problem |
| `404` | Resource not found | No, unless it was just created |
| `408` | Request timeout | Yes, with backoff |
| `409` | Conflict with current state | Usually no. Re-read state first |
| `422` | Well-formed but semantically invalid | No |
| `429` | Too many requests | Yes. Honor `Retry-After` |
| `500` | Server error | Yes, a few times |
| `502` / `503` / `504` | Gateway or upstream unavailable | Yes, with backoff |

Status semantics are defined in RFC 9110 (429 in RFC 6585).

## Related

- [[concepts/tool-calling]]
- [[skills/writing-tool-schemas]]: error messages are part of the tool's interface.

## Sources

- [https://datatracker.ietf.org/doc/html/rfc9110](https://datatracker.ietf.org/doc/html/rfc9110)
