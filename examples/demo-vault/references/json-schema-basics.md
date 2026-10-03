---
title: >-
  JSON Schema Basics
category: references
tags: [reference, tooling]
sources:
  - "url:https://json-schema.org"
summary: >-
  The JSON Schema keywords that matter most when defining tool inputs: type, properties, required, enum, and additionalProperties.
provenance:
  extracted: 0.95
  inferred: 0.05
  ambiguous: 0.0
base_confidence: 0.9
lifecycle: verified
lifecycle_changed: 2026-04-18
created: 2026-04-18T09:00:00Z
updated: 2026-04-18T09:00:00Z
---

# JSON Schema Basics

JSON Schema is a vocabulary for describing and validating JSON documents. Tool inputs in [[concepts/tool-calling]] and [[entities/model-context-protocol]] are declared with it.

## Key Keywords

| Keyword | Meaning |
|---|---|
| `type` | `object`, `array`, `string`, `number`, `integer`, `boolean`, or `null` |
| `properties` | the schema for each named field of an object |
| `required` | the fields that must be present |
| `enum` | the only allowed values |
| `additionalProperties` | `false` rejects fields the schema doesn't name |
| `description` | human- and model-readable documentation for a field |
| `minimum` / `maximum`, `minLength` / `maxLength` | numeric and length bounds |
| `items` | the schema for each element of an array |

## Key Ideas

- `enum` and `additionalProperties: false` catch many malformed or [[concepts/hallucination|hallucinated]] arguments before they reach your code. ^[inferred]

## Related

- [[skills/writing-tool-schemas]]

## Sources

- [https://json-schema.org](https://json-schema.org)
