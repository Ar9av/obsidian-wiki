---
title: >-
  Model Context Protocol
category: entities
tags: [protocols, tooling]
sources:
  - "url:https://modelcontextprotocol.io"
summary: >-
  An open protocol for connecting AI applications to external tools, resources, and prompts served by separate processes.
provenance:
  extracted: 0.85
  inferred: 0.15
  ambiguous: 0.0
base_confidence: 0.85
lifecycle: verified
lifecycle_changed: 2026-05-14
created: 2026-04-10T09:00:00Z
updated: 2026-05-14T09:00:00Z
---

# Model Context Protocol

The Model Context Protocol (MCP) is an open standard, introduced by Anthropic in 2024, for how AI applications connect to external capabilities. A host application talks to MCP servers, each exposing tools, resources, or prompts.

## Key Ideas

- It separates the app that runs the model from the code that provides capabilities, so one server can serve many hosts.
- Servers communicate over standard transports such as stdio for local processes and HTTP for remote ones.
- Tools exposed over MCP are still ordinary [[concepts/tool-calling]] from the model's point of view: a name, a description, and a JSON Schema input.
- Every connected server adds tool definitions to the [[concepts/context-window]], so connecting many servers has a real cost. ^[inferred]

## Related

- [[skills/writing-tool-schemas]]
- [[references/json-schema-basics]]

## Sources

- [https://modelcontextprotocol.io](https://modelcontextprotocol.io)
