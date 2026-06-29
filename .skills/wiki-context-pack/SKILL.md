---
name: wiki-context-pack
description: >
  Produce a token-bounded context pack from the Obsidian wiki — a compact, structured slice of the most
  relevant pages for a topic or recent activity, designed for downstream consumption by another agent or skill.
  Use when the user says "/wiki-context-pack", "make a context pack", "give me a context slice for X",
  "pack the wiki for my agent", or "bounded context for Y". Different from wiki-query (which answers a
  question) — this produces reusable input material for a downstream task.
---

# Wiki Context Pack — Bounded Token Retrieval

You are producing a focused, token-bounded context pack from the wiki. Unlike `wiki-query` (which answers a question), this skill packages the most relevant wiki knowledge into a single markdown block that a downstream agent, skill, or user can consume directly.

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (inline `@name` override → walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH` and any QMD variables.
2. Read `$OBSIDIAN_VAULT_PATH/hot.md` if it exists — gives instant context on recent activity.
3. Read `$OBSIDIAN_VAULT_PATH/index.md` — the full page inventory.

## Invocation Forms

```
/wiki-context-pack "transformer attention mechanism" --budget 16000
/wiki-context-pack "my-project architecture decisions" --budget 8000
/wiki-context-pack --recent --budget 4000   # recent activity pack from hot.md
/wiki-context-pack "authentication patterns"          # default budget: 8000 tokens
```

Parse the user's invocation to extract:
- **topic** — the query string (required unless `--recent`)
- **`--budget N`** — token budget in tokens (default: `8000`; max: `100000`)
- **`--recent`** — pack the most recently updated/ingested pages instead of a topic query

## Algorithm

### Step 1: Relevance Pass (cheap)

Without opening page bodies:

1. Scan `index.md` and frontmatter for topic match. Score each page:
   - **+5** exact title or alias match
   - **+3** tag match
   - **+2** `summary:` field contains the query term
   - **+1** `index.md` entry description contains the query term

2. For `--recent` mode: sort pages by `updated:` frontmatter descending. Take top 20 as candidates.

3. For topic mode: collect the top 20 candidates by score. If QMD is configured (`QMD_WIKI_COLLECTION` set), run a semantic pass and merge with the frontmatter score (QMD rank adds **+4** to the page's score).

### Step 2: Tier-Aware Selection

Within the candidate set, sort by relevance score, then apply tier ordering within each score bucket (see `llm-wiki/SKILL.md`, Importance Tiering section):

1. All `core`-tier matches first
2. Then `supporting`
3. Then `peripheral` (only if budget allows)

Maintain this ordering when filling the budget in Step 3.

### Step 3: Compression

For each selected page (in tier/relevance order), compute its **compressed representation** — not a full read, but a structured distillation:

1. **Required**: title, `tier:`, `tags:`, `summary:` (from frontmatter — cheap, no body read needed)
2. **If budget allows**: add the page body, but stripped of:
   - Frontmatter block (already captured above)
   - The `## Sources` section (keep source names in a one-liner instead)
   - Duplicate wikilinks that are already mentioned in included pages
   - Boilerplate headers with no content following them
3. **Dedup overlapping content** — if two selected pages share a paragraph (or near-identical claim), keep it only in the more relevant page. Mark the removal: `_(content also in [[other-page]])_`.

Estimate tokens for each page representation as `len(text_chars) / 4`.

### Step 4: Budget Enforcement

Fill the pack greedily in tier/relevance order until the budget is exhausted:

1. Always include the frontmatter summary block for every selected page, even if the body doesn't fit.
2. If a page body doesn't fit in full, include a compressed excerpt: the first non-header paragraph plus the "Key Ideas" section (if present).
3. Drop `peripheral`-tier pages first when trimming.
4. Keep a running token count. Stop adding pages when the next page would exceed the budget.
5. Track how many pages were dropped and note it in the header.

### Step 5: Render Output

Emit a single markdown block:

```markdown
# Context Pack: <topic>
# Generated: <ISO timestamp>
# Budget: <budget> tokens | Actual: <actual> tokens | Pages: <N included> / <M candidates>
# Methodology: 4 chars/token estimate

---

## [[<category/page-name>]] (<tier>, ~<tokens> tokens)
tags: #tag1 #tag2
summary: <summary field text>

<compressed body or excerpt>

---

## [[<next-page>]] (<tier>, ~<tokens> tokens)
...
```

If `--recent` mode, the header reads:
```
# Context Pack: Recent Activity (last N pages)
```

**Empty result:** If no pages scored above 0 and `--recent` produced no results, output:
```
# Context Pack: <topic>
No relevant pages found. Consider running /wiki-ingest to add sources about this topic.
```

### Step 6: Log

Append to `$OBSIDIAN_VAULT_PATH/log.md`:
```
- [TIMESTAMP] CONTEXT_PACK topic="<topic>" budget=<N> actual_tokens=<M> pages_included=<K> pages_dropped=<D>
```

## Use Cases

- **Feed into `/wiki-research`** — pass the pack as context to avoid re-discovering known facts
- **Pass to `/wiki-synthesize`** — scoped input for a specific synthesis task
- **Provide to external agents via MCP or clipboard** — bounded, structured, citation-ready
- **Checkpoint context before a long multi-step task** — know what the wiki already knows before starting

## Notes

- The `4 chars/token` heuristic matches `wiki-status`'s token footprint estimate — consistent across skills
- The pack is a snapshot; it is not written to the vault. Re-run to refresh.
- For very large budgets (> 50K tokens), warn the user: "This pack is large. Consider narrowing your topic or using wiki-query for a targeted answer instead."
