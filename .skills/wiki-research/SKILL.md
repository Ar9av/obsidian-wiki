---
name: wiki-research
description: >
  Autonomously research a topic via multi-round web search, synthesize findings, and file structured
  results into the Obsidian wiki. Use this skill when the user says "/wiki-research [topic]",
  "research X", "find everything about Y", "do a deep dive on Z", "autonomous research on X",
  or wants comprehensive, web-sourced knowledge on a topic filed directly into their wiki.
---

# Wiki Research — Autonomous Multi-Round Research

You are running an autonomous research loop on a topic, synthesizing what you find, and filing the results into the Obsidian wiki as permanent knowledge.

## Before You Start

1. Read `~/.obsidian-wiki/config` (preferred) or `.env` (fallback) to get `OBSIDIAN_VAULT_PATH` and `OBSIDIAN_LINK_FORMAT` (default: `wikilink`)
2. Read `$OBSIDIAN_VAULT_PATH/index.md` to understand what's already in the wiki — don't re-research things the wiki covers well
3. Read `$OBSIDIAN_VAULT_PATH/hot.md` if it exists — it surfaces recent context
4. Check `$OBSIDIAN_VAULT_PATH/references/research-config.md` if it exists — it may define source preferences, domains to skip, or confidence rules for this vault

When writing internal links in generated pages, apply the link format from `llm-wiki/SKILL.md` (Link Format section) using the `OBSIDIAN_LINK_FORMAT` value.

Confirm the research topic with the user if it's ambiguous. Then proceed.

## Research Configuration (optional)

If `references/research-config.md` exists in the vault, read it and apply any rules it defines:
- Source preferences (e.g., prefer academic sources, avoid certain domains)
- Domains to skip
- Confidence scoring adjustments
- Topic-specific constraints

If the file doesn't exist, proceed with defaults.

## Round 1 — Broad Survey

**Goal:** Get a wide map of the topic.

1. Decompose the topic into **3-5 distinct angles** (e.g., for "vector databases": what they are, when to use them, leading implementations, trade-offs, production gotchas)
2. For each angle, run **2-3 `WebSearch` queries** using varied phrasing
3. For the top 2-3 results per angle, use `WebFetch` (or `defuddle <url>` if available — cleaner extraction) to get content
4. From each fetched page, extract:
   - **Key claims** — what the source explicitly states
   - **Concepts** — ideas, terms, frameworks introduced
   - **Entities** — tools, people, organizations mentioned
   - **Contradictions** — places where sources disagree with each other

Track what's covered and what's missing as you go.

## Round 2 — Gap Fill

**Goal:** Close the holes left by Round 1.

Review what Round 1 produced:
- What questions did sources raise but not answer?
- Where do sources contradict each other?
- Which angles got thin coverage?

Run **up to 5 targeted searches** specifically addressing these gaps. Prefer primary sources, official documentation, and authoritative analyses over link aggregators.

Add findings to your working set. Update the contradiction list.

## Round 3 — Synthesis Check

**Goal:** Resolve contradictions; confirm depth is sufficient.

If major contradictions remain unresolved:
- Run one final targeted pass (2-3 searches) to find authoritative resolution
- If resolution is impossible, flag the contradiction explicitly in the synthesis page

If contradictions are minor or the topic feels well-covered after Round 2, skip additional searching and proceed to filing.

**Halt condition:** Stop when depth is achieved or 3 rounds are complete — do not loop indefinitely.

## Filing — Write Wiki Pages

Organize all findings into wiki pages across four output areas:

### 1. sources/ — One page per major reference

For each significant source (typically 4-8 pages total):

```yaml
---
title: >-
  <Source title>
category: references
tags: [<2-4 domain tags>]
sources:
  - "<URL>"
source_url: "<URL>"
created: <ISO-8601 timestamp>
updated: <ISO-8601 timestamp>
summary: >-
  <1-2 sentences describing what this source covers, ≤200 chars>
provenance:
  extracted: 0.X
  inferred: 0.X
  ambiguous: 0.X
---
```

Body: title, URL, what it covers, key claims (with provenance markers), limitations.

### 2. concepts/ — One page per substantive concept

For each significant concept surfaced across sources:

Standard concept frontmatter + body. Link concepts to each other and to source pages.

### 3. entities/ — Tools, organizations, people

For each significant entity encountered (tools, libraries, companies, key authors):

Standard entity frontmatter. Link back to concepts that use the entity and sources where it appears.

### 4. synthesis/Research: [Topic].md — Master synthesis

The primary output: a structured synthesis of everything found.

```yaml
---
title: >-
  Research: <Topic>
category: synthesis
tags: [<3-5 domain tags>, research]
sources: [<list of source URLs or page paths>]
created: <ISO-8601 timestamp>
updated: <ISO-8601 timestamp>
summary: >-
  Synthesis of <N>-round research on <topic>. Covers <core findings in ≤200 chars>.
provenance:
  extracted: 0.X
  inferred: 0.X
  ambiguous: 0.X
---

# Research: <Topic>

## Overview
<2-4 sentence executive summary of what the research found>

## Key Findings
<Bulleted list of the most important claims, each with a [[source page]] citation>

## Core Concepts
<Links to concept pages created, with one-line descriptions>

## Entities & Tools
<Links to entity pages, with one-line descriptions>

## Contradictions & Open Questions
<Where sources disagree or where the research hit limits>

## Sources Consulted
<Linked list of all source pages>
```

## Cross-linking

After filing all pages:
- Every concept page should link to at least 2 source pages
- Every source page should link to the concept pages it informed
- The synthesis page should link to all concept, entity, and source pages produced

Check `index.md` for existing pages on the same topics — merge into existing pages rather than creating duplicates.

## Update Tracking Files

**`.manifest.json`** — Add a `research` entry:
```json
{
  "type": "research",
  "topic": "<topic>",
  "researched_at": "TIMESTAMP",
  "rounds_completed": 3,
  "sources_fetched": N,
  "pages_created": ["..."],
  "pages_updated": ["..."]
}
```

**`index.md`** — Add all new pages under their respective sections.

**`log.md`** — Append:
```
- [TIMESTAMP] WIKI_RESEARCH topic="<topic>" rounds=N sources_fetched=N pages_created=M
```

**`hot.md`** — Update **Recent Activity** with the research topic and core finding. Update **Active Threads** if this is ongoing. Update `updated` timestamp.

## Quality Checklist

- [ ] 3 rounds completed (or halted at sufficient depth)
- [ ] Synthesis page exists at `synthesis/Research: [Topic].md`
- [ ] Source pages written for major references
- [ ] Concept and entity pages written for significant items
- [ ] Contradictions flagged in synthesis page
- [ ] All pages cross-linked
- [ ] `index.md`, `log.md`, `hot.md`, `.manifest.json` updated
