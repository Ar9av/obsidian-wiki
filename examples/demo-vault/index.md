---
title: >-
  Wiki Index
generated_by: obsidian-wiki memory index
---

# Wiki Index

Demo vault: building reliable LLM agents. Every page is listed here.

## Concepts

- [[concepts/agent-memory]] — Anything an agent can recall beyond the current context window: notes, profiles, compiled knowledge, or retrieved history. ( #memory #agents)
- [[concepts/context-window]] — The bounded token budget a model reads per call; everything an agent knows in the moment has to fit inside it. ( #llm #agents)
- [[concepts/hallucination]] — Fluent output that is unsupported or false; the model fills a gap with something plausible instead of saying it doesn't know. ( #llm #reliability)
- [[concepts/prompt-caching]] — Reusing the processed form of an unchanged prompt prefix across requests to cut latency and cost. ( #llm #reliability)
- [[concepts/retrieval-augmented-generation]] — Fetching relevant passages at query time and placing them in the prompt, so answers rest on documents rather than model memory. ( #retrieval #llm)
- [[concepts/tool-calling]] — The model emits a structured request to run a named function; the host runs it and returns the result as the next message. ( #agents #tooling)

## Entities

- [[entities/andrej-karpathy]] — AI researcher whose LLM Wiki gist describes having an LLM compile sources into a maintained, interlinked markdown wiki. ( #knowledge-management #llm)
- [[entities/model-context-protocol]] — An open protocol for connecting AI applications to external tools, resources, and prompts served by separate processes. ( #protocols #tooling)
- [[entities/obsidian]] — A markdown note-taking app that works on a local folder of files and renders links between notes as a graph. ( #knowledge-management)

## Skills

- [[skills/evaluating-agents-with-golden-sets]] — Building a fixed set of tasks with known-good outcomes and re-running it on every change to catch regressions. ( #evaluation #reliability)
- [[skills/retry-and-backoff-for-tool-calls]] — Retrying transient tool failures with exponential backoff and jitter, and surfacing permanent ones to the model instead. ( #reliability #tooling)
- [[skills/writing-tool-schemas]] — How to write tool names, descriptions, and input schemas so a model picks the right tool and fills arguments correctly. ( #tooling #agents)

## References

- [[references/http-status-codes-for-tool-errors]] — Which HTTP status codes signal a retryable failure and which mean the request must change. ( #reference #reliability)
- [[references/json-schema-basics]] — The JSON Schema keywords that matter most when defining tool inputs: type, properties, required, enum, and additionalProperties. ( #reference #tooling)

## Synthesis

- [[synthesis/rag-vs-compiled-wiki]] — Retrieval re-derives answers from raw chunks per query; a compiled wiki pays the synthesis cost once and keeps it current. ( #retrieval #knowledge-management #memory)
- [[synthesis/where-agent-memory-should-live]] — Trade-offs between vector stores, databases, and plain markdown as the home for an agent's long-term memory. ( #memory #agents #knowledge-management)

## Journal

- [[journal/2026-05-14-tool-schema-debugging]] — Session note: an agent kept calling the wrong search tool; the fix was in the descriptions, not the prompt. ( #tooling #agents)
- [[journal/2026-06-02-memory-design-review]] — Session note: deciding to keep durable agent memory as markdown pages with provenance, and recap it at session start. ( #memory #agents)
