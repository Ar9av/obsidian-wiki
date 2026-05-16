---
name: llm-wiki
description: >
  The foundational knowledge distillation pattern for building and maintaining an AI-powered Obsidian wiki.
  Based on Andrej Karpathy's LLM Wiki architecture. Use this skill whenever the user wants to understand the
  wiki pattern, set up a new knowledge base, or needs guidance on the three-layer architecture (raw sources →
  wiki → schema). Also use when discussing knowledge management strategy, wiki structure decisions, or how
  to organize distilled knowledge. This is the "theory" skill — other skills handle specific operations
  (ingesting, querying, linting).
---

# LLM Wiki — Knowledge Distillation Pattern

You are maintaining a persistent, compounding knowledge base. The wiki is not a chatbot — it is a **compiled artifact** where knowledge is distilled once and kept current, not re-derived on every query.

## Three-Layer Architecture

### Layer 1: Raw Sources (immutable)

The user's original documents — articles, papers, notes, PDFs, conversation logs, bookmarks, **and images** (screenshots, whiteboard photos, diagrams, slide captures). These are never modified by the system. They live wherever the user keeps them (configured via `OBSIDIAN_SOURCES_DIR` in `.env`). Images are first-class sources: the ingest skills read them via the Read tool's vision support and treat their interpreted content as inferred unless it's verbatim transcribed text. Image ingestion requires a vision-capable model — models without vision support should skip image sources and report which files were skipped.

Think of raw sources as the "source code" — authoritative but hard to query directly.

### Layer 2: The Wiki (LLM-maintained)

A collection of interconnected Obsidian-compatible markdown files organized by category. This is the compiled knowledge — synthesized, cross-referenced, and navigable. Each page has:

- YAML frontmatter (title, category, tags, sources, timestamps)
- Obsidian `[[wikilinks]]` connecting related concepts
- Clear provenance — every claim traces back to a source

The wiki lives at the path configured via `OBSIDIAN_VAULT_PATH` in `.env`.

### Layer 3: The Schema (this skill + config)

The rules governing how the wiki is structured — categories, conventions, page templates, and operational workflows. The schema tells the LLM *how* to maintain the wiki.

## Wiki Organization

The vault has two levels of structure: **categories** (what kind of knowledge) and **projects** (where the knowledge came from).

### Categories

Organize pages into these default categories (customizable in `.env`):

| Category | Purpose | Example |
|---|---|---|
| `concepts/` | Ideas, theories, mental models | `concepts/transformer-architecture.md` |
| `entities/` | People, orgs, tools, projects | `entities/andrej-karpathy.md` |
| `skills/` | How-to knowledge, procedures | `skills/fine-tuning-llms.md` |
| `references/` | Summaries of specific sources | `references/attention-is-all-you-need.md` |
| `synthesis/` | Cross-cutting analysis across sources | `synthesis/scaling-laws-debate.md` |
| `journal/` | Timestamped observations, session logs | `journal/2024-03-15.md` |

### Projects

Knowledge often belongs to a specific project. The `projects/` directory mirrors this:

```
$OBSIDIAN_VAULT_PATH/
├── projects/
│   ├── my-project/
│   │   ├── my-project.md      ← project overview (named after project)
│   │   ├── concepts/          ← project-scoped category pages
│   │   ├── skills/
│   │   └── ...
│   ├── another-project/
│   │   └── ...
│   └── side-project/
│       └── ...
├── concepts/                   ← global (cross-project) knowledge
├── entities/
├── skills/
└── ...
```

**When knowledge is project-specific** (a debugging technique that only applies to one codebase, a project-specific architecture decision), put it under `projects/<project-name>/<category>/`.

**When knowledge is general** (a concept like "React Server Components", a person like "Andrej Karpathy", a widely applicable skill), put it in the global category directory.

**Cross-referencing:** Project pages should `[[wikilink]]` to global pages and vice versa. A project's overview page should link to the key concept, skill, and entity pages relevant to that project — whether they live under the project or globally.

**Naming rule:** The project overview file must be named `<project-name>.md`, not `_project.md`. Obsidian's graph view uses the filename as the node label — `_project.md` makes every project appear as `_project` in the graph, making it unreadable. So `projects/my-project/my-project.md`, `projects/another-project/another-project.md`, etc.

Each project directory has an overview page structured like this:

```markdown
---
title: My Project
category: project
tags: [ai, web, backend]
source_path: ~/.claude/projects/-Users-name-Documents-projects-my-project
created: 2026-03-01T00:00:00Z
updated: 2026-04-06T00:00:00Z
---

# My Project

One-paragraph summary of what this project is.

## Key Concepts
- [[concepts/some-api]] — used for core functionality
- [[projects/my-project/concepts/main-architecture]] — project-specific architecture

## Related
- [[entities/some-service]] — deployment platform
```

## Special Files

Every wiki has these files at its root:

### `index.md`
A content-oriented catalog organized by category. Each entry has a one-line summary and tags. Rebuild this after every ingest operation. Format:

```markdown
# Wiki Index

## Concepts
- [[transformer-architecture]] — The dominant architecture for sequence modeling ( #ml #architecture)
- [[attention-mechanism]] — Core building block of transformers ( #ml #fundamentals)

## Entities
- [[andrej-karpathy]] — AI researcher, educator, former Tesla AI director ( #person #ml)
```
**Format rule**: Add a space after the opening `(` and tags.
❌ Don't: `description (#tag)` — breaks tag parsing
✅ Do: `description ( #tag)` — proper spacing and tag parsing

### `log.md`
Chronological append-only record tracking every operation. Each entry is parseable:

```markdown
## Log

- [2024-03-15T10:30:00Z] INGEST source="papers/attention.pdf" pages_updated=12 pages_created=3
- [2024-03-15T11:00:00Z] QUERY query="How do transformers handle long sequences?" result_pages=4
- [2024-03-16T09:00:00Z] LINT issues_found=2 orphans=1 contradictions=1
- [2024-03-17T10:00:00Z] ARCHIVE reason="rebuild" pages=87 destination="_archives/..."
- [2024-03-17T10:05:00Z] REBUILD archived_to="_archives/..." previous_pages=87
```

### `.manifest.json`
Tracks every source file that has been ingested — path, timestamps, what wiki pages it produced. This is the backbone of the delta system. See the `wiki-status` skill for the full schema.

The manifest enables:
- **Delta computation** — what's new or modified since last ingest
- **Append mode** — only process the delta, not everything
- **Audit** — which source produced which wiki page
- **Staleness detection** — source changed but wiki page hasn't been updated

## Page Templates

All pages share the same lightweight frontmatter. Different categories only differ in body structure.

The goal is not to make every page exhaustive. The goal is to make each page useful, easy to update, and well-connected.

---

## Shared Frontmatter

Use this frontmatter for all pages:

```markdown
---
title: Page Title
category: concepts
tags: []
aliases: []
sources: []
summary:
created:
updated:
---
```

Field meanings:

- `title`: The page title.
- `category`: The page category, such as `concepts`, `entities`, `skills`, `references`, `synthesis`, `journal`, or `project`.
- `tags`: Topic tags.
- `aliases`: Alternative names, abbreviations, Chinese names, English names, or other searchable variants.
- `sources`: Source pages or raw sources that support this page.
- `summary`: One or two sentences summarizing the page for quick preview.
- `created`: Creation timestamp.
- `updated`: Last updated timestamp.

Optional provenance block:

```yaml
provenance:
  extracted: 0.80
  inferred: 0.15
  ambiguous: 0.05
```

Use provenance markers inline:

- No marker = extracted or paraphrased from a source
- `^[inferred]` = synthesized, inferred, or extended beyond the source
- `^[ambiguous]` = unclear, disputed, or conflicting across sources

---

## `concepts/` Body Template

Use for ideas, theories, patterns, mechanisms, and mental models.

```markdown
# Concept Name

One short paragraph explaining what this concept is.

## Core Idea

- The 3-5 most important things to know.
- Keep each bullet short.
- Mark inferred or uncertain claims when needed. ^[inferred]

## How It Works

If the concept has an internal mechanism, explain how it works here.

For protocols, this section can be renamed to `Protocol Flow`.
For algorithms, this section can be renamed to `Algorithm`.
For architectures, this section can be renamed to `Architecture`.

## Use Cases

Explain when this concept is useful.

## Limits

Explain where this concept breaks down, is often misused, or should not be applied.

## Related Pages

- [[related-concept]]
- [[contrasting-concept]]
- [[larger-system]]

## Sources

- [[references/source-name]] — What this source contributed.
```

---

## `entities/` Body Template

Use for people, organizations, tools, products, projects, libraries, models, or systems.

```markdown
# Entity Name

One short paragraph explaining what this entity is.

## Overview

- What it is.
- Why it matters.
- What it is associated with.

## Role

Describe the entity's role in the relevant domain, project, or discussion.

## Key Facts

- Important fact.
- Important fact.
- Important fact.

## Related Pages

- [[related-concept]]
- [[related-project]]
- [[related-entity]]

## Sources

- [[references/source-name]] — What this source contributed.
```

---

## `skills/` Body Template

Use for procedures, workflows, techniques, and how-to knowledge.

```markdown
# Skill Name

One short paragraph explaining what this skill helps someone do.

## When To Use

- Situation where this skill applies.
- Situation where this skill applies.

## Steps

1. First step.
2. Second step.
3. Third step.

## Notes

- Practical tips.
- Edge cases.
- Common mistakes.

## Related Pages

- [[related-skill]]
- [[related-concept]]
- [[related-tool]]

## Sources

- [[references/source-name]] — What this source contributed.
```

---

## `references/` Body Template

Use for summaries of specific source documents.

Reference pages should stay close to the original source. Do not over-synthesize here; synthesis belongs in `concepts/` or `synthesis/`.

```markdown
# Source Title

Briefly summarize what this source is about.

## Key Points

- Main point from the source.
- Main point from the source.
- Main point from the source.

## Claims

- Claim made by the source.
- Claim made by the source.
- Unclear or disputed claim. ^[ambiguous]

## Mentions

- [[mentioned-concept]]
- [[mentioned-entity]]
- [[mentioned-skill]]

## Pages Updated

- [[concepts/page-name]] — What was added or changed.
- [[entities/page-name]] — What was added or changed.
```

---

## `synthesis/` Body Template

Use for cross-source analysis, comparisons, debates, and higher-level conclusions.

```markdown
# Synthesis Title

One short paragraph explaining the question or theme being synthesized.

## Question

What question this page is trying to answer.

## Sources Compared

- [[references/source-a]]
- [[references/source-b]]

## Synthesis

- What the sources collectively suggest.
- Where they agree.
- What pattern emerges across them. ^[inferred]

## Disagreements

- Source A says one thing.
- Source B says another.
- The conflict is currently unresolved. ^[ambiguous]

## Current Understanding

The best current understanding based on available sources.

## Related Pages

- [[related-concept]]
- [[related-synthesis]]

## Sources

- [[references/source-a]]
- [[references/source-b]]
```

---

## `journal/` Body Template

Use for timestamped observations, session notes, and working logs.

Journal pages can be looser than other pages. Their main purpose is to preserve context, not to become polished concept pages.

```markdown
# 2026-04-28

## Notes

- Observation, idea, or session note.
- Observation, idea, or session note.

## Decisions

- Decision made and why.

## Follow-ups

- [ ] Thing to revisit.
- [ ] Source to ingest.
- [ ] Page to update.

## Links

- [[related-page]]
```

---

## `projects/` Project Overview Body Template

Use for `projects/<project-name>/<project-name>.md`.

```markdown
# Project Name

One short paragraph explaining what this project is.

## Overview

- What the project does.
- What problem it solves.
- Current state.

## Key Pages

- [[projects/project-name/concepts/page]]
- [[projects/project-name/skills/page]]
- [[concepts/global-page]]

## Important Decisions

- Important project decision.
- Important project decision.

## Open Questions

- Question to resolve.
- Question to resolve.

## Related Pages

- [[related-concept]]
- [[related-entity]]
- [[related-project]]
```

---

## Template Selection Rule

Choose the template by asking:

- Is this an idea, pattern, mechanism, or theory? → `concepts/`
- Is this a person, organization, tool, model, product, or system? → `entities/`
- Is this something someone can do? → `skills/`
- Is this a summary of a single source? → `references/`
- Is this comparing or synthesizing multiple sources? → `synthesis/`
- Is this a dated note or session log? → `journal/`
- Is this an overview of one project? → `projects/<project-name>/<project-name>.md`

Do not force every page to include every section. If a section would be empty or repetitive, omit it.

## Provenance Markers

Every claim on a wiki page has one of three provenance states. Mark them inline so the reader (and future ingest passes) can tell signal from synthesis.

| State | Marker | Meaning |
|---|---|---|
| **Extracted** | *(no marker — default)* | A paraphrase of something a source actually says. |
| **Inferred** | `^[inferred]` suffix | An LLM-synthesized claim — a connection, generalization, or implication the source doesn't state directly. |
| **Ambiguous** | `^[ambiguous]` suffix | Sources disagree, or the source is unclear. |

Example:

```markdown
- Transformers parallelize across positions, unlike RNNs.
- This is why they scale better on modern hardware. ^[inferred]
- GPT-4 was trained on roughly 13T tokens. ^[ambiguous]
```

**Why this syntax:**
- `^[...]` is footnote-adjacent in Obsidian — renders cleanly and never collides with `[[wikilinks]]`.
- Inline (suffix) so a single bullet stays a single bullet.
- Default = extracted means existing pages without markers stay valid.

**Frontmatter summary:** Optionally surface the rough mix at the page level so the user can scan for speculation-heavy pages without reading them:

```yaml
provenance:
  extracted: 0.72   # rough fraction of sentences/bullets with no marker
  inferred: 0.25
  ambiguous: 0.03
```

These are best-effort numbers written by the ingest skill at create/update time. `wiki-lint` recomputes them and flags drift. The block is optional — pages without it are treated as fully extracted by convention.

## Retrieval Primitives

Reading the vault is the dominant cost of every read-side skill. Use the cheapest primitive that can answer the question and **escalate only when the cheaper one is insufficient**. Any skill that needs content from the vault should follow this table rather than jumping straight to full-page reads.

| Need | Primitive | Relative cost |
|---|---|---|
| Does a page exist? What's its title/category/tags? | Read `index.md`; `Grep` frontmatter blocks (scope with a pattern that targets `^---` blocks at file heads) | **Cheapest** |
| 1–2 sentence preview of a page | Read the `summary:` field in its frontmatter | **Cheap** |
| A specific claim or section inside a page | `Grep -A <n> -B <n> "<term>" <file>` — returns only the matching lines plus context | **Medium** |
| Whole-page content | `Read <file>` | **Expensive** — last resort |
| Relationships across pages | `Grep "\[\[.*?\]\]"` across the vault, or walk wikilinks from a known page | Case-by-case |

**The rule:** escalate only when the cheaper primitive can't answer the question. If you can answer from `summary:` fields alone, don't read page bodies. If a grepped section with `-A 10 -B 2` gives you the claim, don't read the whole page. A 500-line page opened to read 15 lines is 485 lines of wasted tokens.

**Why this matters:** a 20-page vault lets you get away with full-vault scans. A 200-page vault does not. The primitives above are how the skills framework scales to large vaults without a database.

Skills that consume this table: `wiki-query`, `cross-linker`, `wiki-lint`, `wiki-status` (insights mode). Any new skill that reads the vault should cite this section rather than reinvent the pattern.

## Core Principles

1. **Compile, don't retrieve.** The wiki is pre-compiled knowledge. When you ingest a source, update every relevant page — don't just create a summary of the source.

2. **Compound over time.** Each ingest should make the wiki smarter, not just bigger. Merge new information into existing pages, resolve contradictions, strengthen cross-references.

3. **Provenance matters.** Every claim should trace to a source. When updating a page, note which source prompted the update.

4. **Mark inferences.** Default sentences are extracted. Mark synthesized claims with `^[inferred]` and contested claims with `^[ambiguous]`. A wiki that hides its guessing rots silently; one that marks it stays trustworthy.

5. **Human curates, LLM maintains.** The human decides what sources to add and what questions to ask. The LLM handles the bookkeeping — updating cross-references, maintaining consistency, noting contradictions.

6. **Obsidian is the IDE.** The user browses and explores the wiki in Obsidian. Everything must be valid Obsidian markdown with working wikilinks.

## Environment Variables

The wiki is configured through environment variables (see `.env.example`). The only required variable is the vault path — everything else has sensible defaults.

- `OBSIDIAN_VAULT_PATH` — Where the wiki lives **(required)**
- `OBSIDIAN_SOURCES_DIR` — Where raw source documents are
- `OBSIDIAN_CATEGORIES` — Comma-separated list of categories
- `CLAUDE_HISTORY_PATH` — Where to find Claude conversation data

No API keys are needed — the agent running these skills already has LLM access built in.

## Modes of Operation

The wiki supports three ingest modes:

| Mode | When to use | What happens |
|---|---|---|
| **Append** | Small delta, incremental updates | Compute delta via manifest, ingest only new/modified sources |
| **Rebuild** | Major drift, fresh start needed | Archive current wiki to `_archives/`, clear, reprocess all sources |
| **Restore** | Need to go back | Bring back a previous archive |

Use `wiki-status` to see the delta and get a recommendation. Use `wiki-rebuild` for archive/rebuild/restore operations.

## Reference

For details on specific operations, see the companion skills:
- **wiki-status** — Audit what's ingested, compute delta, recommend append vs rebuild
- **wiki-rebuild** — Archive current wiki, rebuild from scratch, or restore from archive
- **wiki-ingest** — Distill source documents into wiki pages
- **claude-history-ingest** — Ingest Claude conversation history
- **codex-history-ingest** — Ingest Codex CLI session history
- **data-ingest** — Ingest any raw text data
- **wiki-query** — Answer questions against the wiki
- **wiki-lint** — Audit and maintain wiki health
- **wiki-setup** — Initialize a new vault
