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

**Writing profile:** Before drafting or rewriting natural-language Markdown, read and apply the `Writing Profile Resolution` section in `llm-wiki/SKILL.md`. Framework schema, provenance, safety, and operation-specific requirements take precedence.
`WRITING.md` preferences apply only to newly drafted or rewritten natural-language Markdown; preserve source content and structured records.

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (inline `@name` override → walk up CWD for `.env` → global config → prompt setup). This gives `OBSIDIAN_VAULT_PATH` and `OBSIDIAN_LINK_FORMAT` (default: `wikilink`).
2. Read `$OBSIDIAN_VAULT_PATH/index.md` to understand what's already in the wiki — don't re-research things the wiki covers well
3. Read `$OBSIDIAN_VAULT_PATH/hot.md` if it exists — it surfaces recent context
4. Check `$OBSIDIAN_VAULT_PATH/references/research-config.md` if it exists — it may define source preferences, domains to skip, or confidence rules for this vault
5. Check `$OBSIDIAN_VAULT_PATH/references/research-backends.md` if it exists — it registers optional CLI retrieval backends (social media, video transcripts, paid APIs, etc.). Load any available backends into your working state for this session.

When writing internal links in generated pages, apply the link format from `llm-wiki/SKILL.md` (Link Format section) using the `OBSIDIAN_LINK_FORMAT` value.

Confirm the research topic with the user if it's ambiguous. Then proceed.

## Research Configuration (optional)

If `references/research-config.md` exists in the vault, read it and apply any rules it defines:
- Source preferences (e.g., prefer academic sources, avoid certain domains)
- Domains to skip
- Confidence scoring adjustments
- Topic-specific constraints

If the file doesn't exist, proceed with defaults.

## Research Backends (optional)

If `references/research-backends.md` exists in the vault, load it before starting research. It defines zero or more CLI retrieval backends as a YAML list:

```yaml
backends:
  - name: yt-dlp-transcript      # friendly label
    binary: yt-dlp                # CLI binary (checked with `command -v`)
    invoke: "yt-dlp --skip-download --write-auto-sub --sub-lang en --sub-format json3 -o /tmp/ytvid '{url}'"
    when_to_use: YouTube video URLs, video transcripts
    cost_tier: free               # free | paid
    env_key: ""                   # required env var for paid tiers (empty = always enabled)
    output: text                  # json | text | markdown

  - name: perplexity-sonar
    binary: perplexity
    invoke: "perplexity search '{query}'"
    when_to_use: deep synthesis queries needing multi-source aggregation
    cost_tier: paid
    env_key: PERPLEXITY_API_KEY   # skipped if unset
    output: text
```

**Backend availability check (run once at session start):**
- For each backend: `command -v <binary> 2>/dev/null` — if not found, mark unavailable and note it in the run summary
- For `paid` backends: also check that `$env_key` is non-empty — if unset, mark unavailable and note it
- Build a list of *active backends* (available + key-gated checks pass) to use in Rounds 1–2

**Invocation rules (per angle/URL during research):**
- Substitute `{url}` or `{query}` in the `invoke` template with the current URL or search query
- Capture stdout; on non-zero exit code → skip this backend for this angle, note the short error, continue
- Fold backend output into the same claims/concepts/entities/contradictions extraction, citing the source URL the backend returns (or the query string for query-mode backends)
- A backend failure never aborts the research run — always fall back to `WebSearch`/`WebFetch`

**Free-first ordering:** Evaluate `free` backends before `paid` ones for each angle. If a free backend returns sufficient content, paid backends for the same angle can be skipped.

**No `research-backends.md`** → skip this section entirely; behavior is identical to today.

### Starter registry template

If the user asks for an example registry, offer this file at `$VAULT/references/research-backends.md`:

```yaml
# Optional CLI backends for wiki-research. Delete rows you don't need.
# Skill docs: .skills/wiki-research/SKILL.md — Research Backends section
backends:
  # --- free / local ---
  - name: defuddle-fetch
    binary: defuddle
    invoke: "defuddle '{url}'"
    when_to_use: any URL — cleaner extraction than WebFetch alone
    cost_tier: free
    env_key: ""
    output: markdown

  - name: yt-dlp-transcript
    binary: yt-dlp
    invoke: "yt-dlp --skip-download --write-auto-sub --sub-lang en --sub-format json3 -o /tmp/ytvid '{url}'"
    when_to_use: YouTube video URLs for transcript extraction
    cost_tier: free
    env_key: ""
    output: text

  # --- paid / gated (skipped when env key is unset) ---
  - name: perplexity-sonar
    binary: perplexity
    invoke: "perplexity search '{query}'"
    when_to_use: deep synthesis queries needing multi-source aggregation
    cost_tier: paid
    env_key: PERPLEXITY_API_KEY
    output: text
```

## Round 1 — Broad Survey

**Goal:** Get a wide map of the topic.

1. Decompose the topic into **3-5 distinct angles** (e.g., for "vector databases": what they are, when to use them, leading implementations, trade-offs, production gotchas)
2. For each angle, run **2-3 `WebSearch` queries** using varied phrasing
3. For the top 2-3 results per angle, use `WebFetch` (or `defuddle <url>` if available — cleaner extraction) to get content. For each URL, also invoke any *active backends* whose `when_to_use` matches (e.g., a YouTube URL triggers `yt-dlp-transcript`); fold their output into extraction alongside `WebFetch` results, citing the source URL the backend returns.
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

Run **up to 5 targeted searches** specifically addressing these gaps. Prefer primary sources, official documentation, and authoritative analyses over link aggregators. For gap-fill queries, also invoke any *active query-mode backends* (e.g., `perplexity-sonar`) by substituting `{query}` in their `invoke` template — fold results into extraction with backend name as citation context.

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
base_confidence: <0.17 + 0.5 × classify(url) for a single source>
lifecycle: draft
lifecycle_changed: <ISO date today>
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
base_confidence: <min(N_unique_sources/3,1.0)×0.5 + avg_source_quality×0.5>
lifecycle: draft
lifecycle_changed: <ISO date today>
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
- [TIMESTAMP] WIKI_RESEARCH topic="<topic>" rounds=N sources_fetched=N pages_created=M backends_used=[<name,...>|none]
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
- [ ] Backend summary reported: which backends were active, which were skipped (unavailable binary / unset key / error), and why

## QMD Refresh After Vault Writes

QMD is a search index, not the source of truth. If `$QMD_WIKI_COLLECTION` is empty or unset, skip this step. Run it only after this skill has written or rewritten vault markdown. If QMD refresh fails, do not roll back the vault changes; report the QMD status separately.

Use `$QMD_CLI` if set; otherwise use `qmd`.

```bash
${QMD_CLI:-qmd} update
```

If the output says vectors are needed or embeddings may be stale, run:

```bash
${QMD_CLI:-qmd} embed
```

Verify the collection with either:

```bash
${QMD_CLI:-qmd} ls "$QMD_WIKI_COLLECTION"
```

or, when a specific page path is known:

```bash
${QMD_CLI:-qmd} get "qmd://$QMD_WIKI_COLLECTION/<page>.md" -l 5
```

Record one of:
- `QMD refreshed: update + embed + verified`
- `QMD refreshed: update only + verified`
- `QMD skipped: QMD_WIKI_COLLECTION unset`
- `QMD skipped: qmd CLI unavailable`
- `QMD failed: <short error summary>`
