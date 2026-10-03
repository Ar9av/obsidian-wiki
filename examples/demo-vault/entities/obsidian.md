---
title: >-
  Obsidian
category: entities
tags: [knowledge-management]
sources:
  - "url:https://obsidian.md"
summary: >-
  A markdown note-taking app that works on a local folder of files and renders links between notes as a graph.
provenance:
  extracted: 0.9
  inferred: 0.1
  ambiguous: 0.0
base_confidence: 0.9
lifecycle: verified
lifecycle_changed: 2026-04-30
created: 2026-04-08T09:00:00Z
updated: 2026-04-30T09:00:00Z
---

# Obsidian

Obsidian is a note-taking application built on plain markdown files in a local folder (a "vault"). Notes link to each other with double-bracket wikilinks, and the graph view draws those links as a network.

## Key Ideas

- The files are ordinary markdown, so any tool, including an AI agent, can read and write them without an API.
- Backlinks and the graph view make a link-dense knowledge base browsable for a human. ^[inferred]
- YAML frontmatter at the top of a note is shown as properties and can drive queries and dashboards.
- That combination of human-readable files with machine-writable structure makes it a natural home for [[concepts/agent-memory]]. ^[inferred]

## Related

- [[entities/andrej-karpathy]]: the LLM Wiki gist suggests Obsidian as the viewer.
- [[synthesis/where-agent-memory-should-live]]

## Sources

- [https://obsidian.md](https://obsidian.md)
