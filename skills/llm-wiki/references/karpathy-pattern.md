# Karpathy's LLM Wiki Pattern — Original Reference

Source: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

## Core Insight

"The wiki is a persistent, compounding artifact. The knowledge is compiled once and then kept current, not re-derived on every query."

Human curates sources and asks questions; LLM maintains the knowledge system. Obsidian becomes the IDE, the LLM becomes the programmer, and the wiki becomes the codebase.

## Why This Beats RAG

Traditional RAG rediscovers knowledge on every query — it searches raw sources, pulls relevant chunks, and synthesizes an answer from scratch. The LLM Wiki compiles knowledge once into maintained pages, so queries hit pre-synthesized, cross-referenced content.

## Key Operations

| Operation | What it does | When to use |
|---|---|---|
| **Ingest** | Read new sources, extract key information, update 10-15 wiki pages, maintain consistency | When new documents arrive |
| **Query** | Answer questions against compiled wiki with citations | When the user asks something |
| **Lint** | Identify contradictions, orphaned pages, stale claims, missing cross-references | Periodic maintenance |

## Recommended Tools

- **Obsidian** — IDE for browsing and exploring the wiki
- **Web Clipper** — Browser extension for converting articles to markdown
- **Marp** — Markdown-based slide decks from wiki content
- **Dataview** — Obsidian plugin for querying page metadata
- **qmd** — Local search engine with BM25/vector hybrid search

## Applications

- Personal tracking (goals, psychology, self-improvement)
- Research (building comprehensive understanding over weeks/months)
- Book annotation (companion wikis with characters, themes, plot connections)
- Team/business (wikis from Slack threads, meeting transcripts)
- Due diligence, competitive analysis, trip planning

## Community Extensions Worth Knowing

- **Provenance tracking** — Record which source files produced each claim, detect staleness through content hashing
- **Hierarchical inheritance** — Parent-child page relationships instead of flat indexing
- **Decision records** — Capture why the wiki evolved, not just what changed
- **Two-tier LLMs** — Local models for sensitive data, cloud for the rest
- **Graph databases** — Typed ontologies instead of markdown links
