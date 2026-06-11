---
name: wiki-query
description: >
  Answer questions by searching the compiled Obsidian wiki. Use this skill when the user asks a question
  about their knowledge base, wants to find information across their wiki, asks "what do I know about X",
  "find everything related to Y", or wants synthesized answers with citations from their wiki pages.
  Also use when the user wants to explore connections between topics in their wiki, or asks a multi-hop
  "how is X connected to Y", "what links X to Y", "trace the chain from X to Z", or "what does X depend on
  transitively" question — answered by walking typed edges across multiple hops. Works from any project.
  Includes an index-only fast mode triggered by "quick answer", "just scan", "don't read the pages",
  "fast lookup" — returns answers from page summaries and frontmatter without reading page bodies.
---

# Wiki Query — Knowledge Retrieval

You are answering questions against a compiled Obsidian wiki, not raw source documents. The wiki contains pre-synthesized, cross-referenced knowledge.

## This skill is READ-ONLY

`wiki-query` answers questions. It MUST NOT create or modify any wiki content. The ONLY write it may perform is the single Step 6 append to `log.md`.

Never, even when a change seems obviously helpful:
- create or edit pages under `concepts/`, `entities/`, `skills/`, `references/`, `synthesis/`, `journal/`, or `projects/`
- modify `index.md`, `hot.md`, `_insights.md`, or `.manifest.json`

If the user's message contains a new finding, an action request ("save this", "ban X", "record that"), or anything implying a change, **do not perform it.** Answer the question, PROPOSE the change, and route the user to the right skill:
- quick note / gotcha → `wiki-capture --quick`
- a full new page → `wiki-capture`
- a project-knowledge sync → `wiki-update`

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). Prefer `~/.obsidian-wiki/config` for cross-project queries when present, even if it is a symlink to the vault `.env`. This gives `OBSIDIAN_VAULT_PATH` and any QMD variables. Works from any project directory.
2. **Load QMD settings from the resolved config** before deciding retrieval strategy. If `QMD_WIKI_COLLECTION` is set, treat QMD as available subject only to transport/tool checks below. If it is empty or unset, say briefly why QMD is being skipped before using grep/page reads.
3. If `$OBSIDIAN_VAULT_PATH/hot.md` exists, read it first — it gives you instant context on recent activity. If the user's question is about something ingested recently, hot.md may answer it before you even open `index.md`.
4. Read `$OBSIDIAN_VAULT_PATH/index.md` to understand the wiki's scope and structure

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
- **Relationship query** — "How does X relate to Y?" / "What contradicts X?" → Find both pages, their cross-references, and their `relationships:` frontmatter blocks for typed edges
- **Path / multi-hop query** — "How is X connected to Y?" / "What links X to Y?" / "Trace the chain from X to Z" / "What does X depend on transitively?" → X and Y don't link directly; the connection runs through intermediate pages. Use the multi-hop graph traversal in Step 4b.
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
- **Apply tier ordering within each rank bucket:** when two candidates score equally, prefer `tier: core` over `tier: supporting` over `tier: peripheral`. Read the `tier:` frontmatter field with the same cheap grep as other fields. Pages without a `tier:` field are treated as `supporting`.

If you're in **index-only mode**, stop here. Answer from `summary:` fields, titles, and `index.md` descriptions only. Label the answer clearly: **"(index-only answer — page bodies not read; facts below are from page summaries and may miss nuance)"**. Then skip to Step 5.

### Step 2b: QMD Semantic Pass (optional — requires `QMD_WIKI_COLLECTION` in resolved config)

**GUARD: If `$QMD_WIKI_COLLECTION` is empty or unset after config resolution, skip this entire step and proceed to Step 3. Mention the missing variable in your working update.**

> **No QMD?** Skip to Step 3 and use `Grep` directly on the vault. QMD is faster and concept-aware but the grep path is fully functional. See `.env.example` for setup.

If `QMD_WIKI_COLLECTION` is set, run QMD before reaching for `Grep` unless the question is already fully answered by `hot.md` or `index.md` metadata. QMD is especially preferred when the question is semantic, project-specific, asks for related context, or uses terms that may not appear verbatim in titles/frontmatter.

Choose the QMD transport from `$QMD_TRANSPORT`:

- `mcp` (default): use the QMD MCP tool configured in the agent.
- `cli`: run the local qmd CLI. Use `$QMD_CLI` if set; otherwise use `qmd`.

For detailed CLI command selection, maintenance, and VM caveats, use the local
`$qmd-cli` skill when it is installed.

If the selected transport is unavailable (no MCP tool, `qmd` not on PATH, or the command errors), skip QMD and continue with Step 3.

For MCP transport:

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

For CLI transport, pick the command from `$QMD_CLI_SEARCH_MODE`:

Keep operator-like or punctuation-heavy tokens such as `no-sudo`, `ansible_become=false`, and `~/.local/bin` in the `lex:` line. Rewrite the `vec:` line as plain natural language without hyphenated `-term` words; QMD treats `-term` as negation, and negation is not supported in `vec`/`hyde` queries.

- `quality` (default): best relevance; slower on CPU.
  ```bash
  ${QMD_CLI:-qmd} query $'lex: <key terms>\nvec: <question rephrased as a description>' -c "$QMD_WIKI_COLLECTION" -n 8 --files
  ```
- `balanced`: hybrid search without LLM reranking; use when `quality` is too slow.
  ```bash
  ${QMD_CLI:-qmd} query $'lex: <key terms>\nvec: <question rephrased as a description>' -c "$QMD_WIKI_COLLECTION" -n 8 --no-rerank --files
  ```
- `fast`: semantic-only recall, or `search` instead when exact names, file paths, or error messages matter.
  ```bash
  ${QMD_CLI:-qmd} vsearch "<question rephrased as a description>" -c "$QMD_WIKI_COLLECTION" -n 8 --files
  ```

Use `${QMD_CLI:-qmd} get "#docid"` to retrieve a ranked document by docid when CLI output provides one.

The returned snippets or ranked files act as pre-read section summaries. If they answer the question fully, skip Step 3 and go straight to Step 4 (reading only the pages QMD ranked highest). If not, use the ranked file list to guide which files to grep or read in Step 3.

**Also search `papers` when the question may have source material in `_raw/`:**

If `QMD_PAPERS_COLLECTION` is set and the user is asking about a topic likely covered by ingested papers (research, theory, background), run a parallel search against the papers collection. Cite raw sources separately from compiled wiki pages in your answer.

### Step 3: Section Pass (medium cost — only if Steps 2/2b are inconclusive)

For each of the top candidates, pull the relevant section *without reading the whole page*:

- Use `Grep -A 10 -B 2 "<query-term>" <candidate-file>` to get just the lines around the match.
- This usually returns 15–30 lines per hit instead of 100–500.
- If the section grep gives a clear answer, go straight to Step 5.

### Step 4: Full Read (expensive — last resort)

Only when Steps 2 and 3 don't answer the question:

- `Read` the top **3** candidates in full. When choosing which 3 to read, apply tier ordering: read `core` pages before `supporting`, and skip `peripheral` pages unless they are the only match.
- Follow at most one hop of `[[wikilinks]]` from those pages if the answer requires cross-references.
- **For relationship queries** ("How does X relate to Y?" / "What contradicts X?"): also read the `relationships:` frontmatter block of the candidate pages. Each entry gives a typed, directional edge (`extends`, `implements`, `contradicts`, `derived_from`, `uses`, `replaces`, `related_to`). Surface these explicitly in your answer — "Page A *contradicts* Page B (typed edge)" is more useful than "Page A links to Page B".
- Check "Open Questions" sections for known gaps.
- If you're still short, **then** fall back to a broad content grep across the vault. Tell the user you escalated — this is the expensive path and they should know.

### Step 4b: Multi-hop Graph Traversal (typed edges)

Plain retrieval surfaces pages that *mention* the query terms. It cannot answer **path / multi-hop queries** — "How is X connected to Y?", "What does X depend on transitively?", "Trace the chain from X to Z" — when X and Y never appear on the same page. The answer lives in the *shape* of the typed-edge graph, not in any single page body. This is the step that walks it.

Run this step **only** for path/multi-hop queries (or when a relationship query returns no direct edge between the two pages). It is built entirely from frontmatter — never read page bodies here.

1. **Build the typed-edge adjacency (cheap).** Grep every page's `relationships:` block in one pass — `Grep -A 20 "^relationships:" <vault>/**/*.md` (frontmatter only). Each entry yields a directed, typed edge `source —type→ target`. Add the reverse direction as a traversable edge too (mark it `(reverse)`), since "connected to" is symmetric even though the typed assertion is directional. Plain body `[[wikilinks]]` count as untyped `related_to` edges only if you need them to complete a path — prefer typed edges first.

2. **Locate the endpoints.** Resolve X (and Y, if the query names two) to page paths using the registry from Step 2. If an endpoint is ambiguous, pick the `tier: core` candidate and note the assumption.

3. **Bounded BFS.** Walk outward from X over the adjacency:
   - **Max depth 3 hops** by default (the connection is rarely meaningful beyond that). Raise to 4 only if the user says "deep" / "however many hops it takes".
   - **Frontier cap:** stop expanding a node once the visited set exceeds ~60 pages — report partial results rather than fanning out across the whole vault.
   - For a **two-endpoint query** (X→Y): stop as soon as you find the shortest path; then continue briefly to surface up to 2 alternate paths if they exist.
   - For a **one-endpoint query** (X transitively): collect all nodes reachable within the depth limit, grouped by hop distance.

4. **Report the path(s) with edge types.** Show the chain, not just the endpoints — the typed edges *are* the answer:

   ```
   [[concepts/transformers]] —uses→ [[concepts/attention]] —derived_from→ [[concepts/rnn-seq2seq]] —contradicts (reverse)→ [[concepts/lstm]]
   ```

   State the hop count and whether any hop is a `(reverse)` traversal or an untyped `related_to` fallback (those chains are weaker — flag them). If no path exists within the depth limit, say so explicitly: "No typed-edge path from X to Y within 3 hops — they are in disconnected regions of the graph." That is itself a useful finding (a graph gap).

**Cost guard:** this step reads only frontmatter via grep. If the adjacency grep returns nothing (no page uses `relationships:` yet), report that the graph has no typed edges to traverse and suggest running `cross-linker` to populate them, then fall back to ordinary one-hop retrieval.

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

**Surface the project source path (project-scoped queries).** When the cited pages are project-scoped — their path is under `projects/<name>/...`, or their frontmatter carries a `source_path` field — resolve where the actual code lives so a proposed fix can name real files and a follow-up turn can edit them:

1. Read `$OBSIDIAN_VAULT_PATH/.manifest.json` and look up `.projects.<name>.source_cwd` — this is the authoritative path.
2. Fallback: if the project isn't in the manifest, use the page's `source_path` frontmatter.

Include a **`Source code:`** line in the answer with that absolute path. When the query implies a code fix is wanted, name the specific files to edit using that path (e.g. `<source_cwd>/public/lib/anticheat.js`) and **offer to implement it as an explicit, separate next step** — but never edit during the query itself (see the READ-ONLY guard above).

### Step 6: Log the Query

Append to `log.md`. This `log.md` append is the *only* write this skill performs — do not edit anything else.
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
>
> **Source code:** `<source_cwd>` — to implement, the relevant files are `…`.
> (Say the word and I'll switch out of query mode to make the change.)

The **Source code** line is optional — include it only for project-scoped queries where you resolved a `source_cwd` (see Step 5).
