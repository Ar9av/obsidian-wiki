---
name: wiki-query
description: >
  Answer questions by searching the compiled Obsidian wiki. Use this skill when the user asks a question
  about their knowledge base, wants to find information across their wiki, asks "what do I know about X",
  "find everything related to Y", or wants synthesized answers with citations from their wiki pages.
  Also use when the user wants to explore connections between topics in their wiki. Works from any project.
  Includes an index-only fast mode triggered by "quick answer", "just scan", "don't read the pages",
  "fast lookup" — returns answers from page summaries and frontmatter without reading page bodies.
---

# Wiki Query — Knowledge Retrieval

You are answering questions against a compiled Obsidian wiki, not raw source documents. The wiki contains pre-synthesized, cross-referenced knowledge.

## Before You Start

1. Read `~/.obsidian-wiki/config` to get `OBSIDIAN_VAULT_PATH` (works from any project). Fall back to `.env` if you're inside the obsidian-wiki repo.
2. If `$OBSIDIAN_VAULT_PATH/hot.md` exists, read it first — it gives you instant context on recent activity. If the user's question is about something ingested recently, hot.md may answer it before you even open `index.md`.
3. Read `$OBSIDIAN_VAULT_PATH/index.md` to understand the wiki's scope and structure

## Visibility Filter (optional)

By default, **all pages are returned** regardless of visibility tags. This preserves existing behavior — nothing changes unless the user asks for it.

If the user's query includes phrases like **"public only"**, **"user-facing"**, **"no internal content"**, **"as a user would see it"**, or **"exclude internal"**, activate **filtered mode**:

- Build a **blocked tag set**: `{visibility/internal, visibility/pii}`
- In the Index Pass (Step 2), skip any candidate whose frontmatter tags contain a blocked tag
- In Section/Full Read passes (Steps 3–4), do not read or cite any blocked page
- Synthesize the answer **only from allowed pages** — do not mention that excluded pages exist

Pages with no `visibility/` tag, or tagged `visibility/public`, are always included.

In filtered mode, note the filter in the Step 6 log entry: `mode=filtered`.

## Retrieval Protocol

**Follow the Retrieval Primitives table in `llm-wiki/SKILL.md`.** Reading is the dominant cost of this skill — use the cheapest primitive that answers the question and escalate only when it can't. Never jump straight to full-page reads.

### Step 1: Understand the Question

Classify the query type:
- **Factual lookup** — "What is X?" → Find the relevant page(s)
- **Relationship query** — "How does X relate to Y?" → Find both pages and their cross-references
- **Synthesis query** — "What's the current thinking on X?" → Find all pages that touch X, synthesize
- **Gap query** — "What don't I know about X?" → Find what's missing, check open questions sections

Also decide the **mode**:
- **Index-only mode** — triggered by "quick answer", "just scan", "don't read the pages", "fast lookup". Stops at Step 3. Answers from frontmatter + `index.md` only.
- **Normal mode** — the full tiered pipeline below.

### Step 2: Index Pass (cheap)

Build a candidate set *without opening any page bodies*:

- You've already read `index.md` above — use it as the first filter. It lists every page with a one-line description and tags.
- Use `Grep` to scan page **frontmatter only** for title, tag, alias, and summary matches. A pattern like `^(title|tags|aliases|summary):` scoped to vault `.md` files is far cheaper than content grep.
- Collect the top 5–10 candidate page paths ranked by:
  1. Exact title or alias match
  2. Tag match
  3. Summary field contains the query term
  4. `index.md` entry contains the query term

If you're in **index-only mode**, stop here. Answer from `summary:` fields, titles, and `index.md` descriptions only. Label the answer clearly: **"(index-only answer — page bodies not read; facts below are from page summaries and may miss nuance)"**. Then skip to Step 5.

### Step 2b: QMD Semantic Pass (optional — requires `QMD_WIKI_COLLECTION` in `.env`)

**GUARD: If `$QMD_WIKI_COLLECTION` is empty or unset, skip this entire step and proceed to Step 3.**

> **No QMD?** Skip to Step 3 and use `Grep` directly on the vault. QMD is faster and concept-aware but the grep path is fully functional. See `.env.example` for setup.

If `QMD_WIKI_COLLECTION` is set and the index pass didn't produce clear candidates — or the question requires semantic matching rather than exact terms — use QMD before reaching for `Grep`:

```
mcp__qmd__query:
  collection: <QMD_WIKI_COLLECTION>   # e.g. "knowledge-base-wiki"
  intent: <the user's question>
  searches:
    - type: lex    # keyword match — good for exact names, file paths, error messages
      query: <key terms>
    - type: vec    # semantic match — good for concepts, patterns, "what is X like"
      query: <question rephrased as a description>
```

The returned snippets act as pre-read section summaries. If they answer the question fully, skip Step 3 and go straight to Step 4 (reading only the pages QMD ranked highest). If not, use the ranked file list to guide which files to grep or read in Step 3.

**Also search `papers` when the question may have source material in `_raw/`:**

If `QMD_PAPERS_COLLECTION` is set and the user is asking about a topic likely covered by ingested papers (research, theory, background), run a parallel search against the papers collection. Cite raw sources separately from compiled wiki pages in your answer.

### Step 3: Section Pass (medium cost — only if Steps 2/2b are inconclusive)

For each of the top candidates, pull the relevant section *without reading the whole page*:

- Use `Grep -A 10 -B 2 "<query-term>" <candidate-file>` to get just the lines around the match.
- This usually returns 15–30 lines per hit instead of 100–500.
- If the section grep gives a clear answer, go straight to Step 5.

### Step 4: Full Read (expensive — last resort)

Only when Steps 2 and 3 don't answer the question:

- `Read` the top **3** candidates in full.
- Follow at most one hop of `[[wikilinks]]` from those pages if the answer requires cross-references.
- Check "Open Questions" sections for known gaps.
- If you're still short, **then** fall back to a broad content grep across the vault. Tell the user you escalated — this is the expensive path and they should know.

### Step 5: Synthesize an Answer

Compose your answer from wiki content:
- Cite specific wiki pages using `[[page-name]]` notation
- Note which step the answer came from ("found in summary" vs "grepped section" vs "full page read") — helps the user understand confidence
- If the wiki has contradictions, present both sides
- If the wiki doesn't cover something, say so explicitly
- Suggest which sources might fill the gap

**Page trust annotations:** For every page cited in your answer, check its `lifecycle` frontmatter and compute `is_stale = (today − updated) > 90 days`. Annotate risky pages inline so the user knows which citations to verify:

| Condition | Annotation |
|---|---|
| `lifecycle: archived` | `(ARCHIVED: superseded by [[target]])` — use the successor instead |
| `lifecycle: disputed` | `(DISPUTED, marked <lifecycle_changed>: <lifecycle_reason or "reason unspecified">)` |
| `is_stale` + `lifecycle: verified` | `(VERIFIED but stale: last updated <updated>)` — reader should re-verify before relying |
| `is_stale` (other lifecycle) | `(stale: last updated <updated>)` |

Examples in a synthesized answer:
```
[[concept-page]] (stale: last updated 2026-01-15) — Original claim was X.
[[verified-page]] (VERIFIED but stale: last updated 2025-09-10) — Reader should reverify before relying.
[[disputed-page]] (DISPUTED, marked 2026-04-30: contradicted by [[new-source]]) — Earlier said Y, now uncertain.
[[old-page]] (ARCHIVED: superseded by [[new-page]]) — Use the successor.
```

Pages with no lifecycle field (legacy pages predating the schema) are treated the same as `draft` — annotate if stale, skip otherwise. Never fabricate a `lifecycle_reason`; if the field is absent, omit the reason from the annotation.

### Step 6: Log the Query

Append to `log.md`:
```
- [TIMESTAMP] QUERY query="the user's question" result_pages=N mode=normal|index_only|filtered escalated=true|false
```

## Answer Format

Structure answers like this:

> **Based on the wiki:**
>
> [Your synthesized answer with [[wikilinks]] to source pages]
>
> **Pages consulted:** [[page-a]], [[page-b]], [[page-c]]
>
> **Gaps:** [What the wiki doesn't cover that might be relevant]
