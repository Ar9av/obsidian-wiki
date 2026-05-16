---
name: wiki-dedup
description: >
  Scan the Obsidian wiki for page-level identity collisions — different pages covering the same
  concept under different names (e.g. "RSC" vs "React Server Components") — and merge them.
  Use this skill when the user says "dedup my wiki", "find duplicate pages", "merge duplicates",
  "identity resolution", "consolidate my wiki", "I have duplicate pages", or "my wiki has two pages
  for the same thing". Distinct from wiki-lint (which checks structure) and cross-linker (which adds
  links) — this skill makes destructive page-level merges and requires careful confirmation.
---

# Wiki Dedup — Identity Resolution and Page-Level Deduplication

You are finding and merging wiki pages that cover the same concept under different names. This is a write-heavy, potentially destructive skill — page merges cannot be automatically undone. Work carefully and confirm before acting in merge mode.

**Follow the Retrieval Primitives table in `llm-wiki/SKILL.md`.** The candidate-detection pass uses only frontmatter and titles (cheap). Only open full page bodies for confirmed candidate pairs.

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH` and `OBSIDIAN_LINK_FORMAT`.
2. Read `index.md` to get the full page inventory with one-line descriptions and tags.
3. Read `log.md` briefly — if a dedup run just happened, note what was already merged.

## Modes

| Mode | Flag | Behavior |
|---|---|---|
| **Audit** | *(default)* | Report candidates only — no writes |
| **Merge** | `--merge` | Show each confirmed pair, ask for confirmation before merging |
| **Auto-merge** | `--auto` | Merge all high-confidence pairs (`score ≥ 0.90`) non-interactively |

If the user doesn't specify, run in **Audit** mode and present findings before asking whether to proceed.

## Step 1: Build the Page Registry

Glob all `.md` files in the vault (excluding `_archives/`, `_raw/`, `.obsidian/`, `index.md`, `log.md`, `hot.md`, `_insights.md`, and any file that contains `redirects_to:` in its frontmatter — those are already merged redirect stubs).

For each remaining page, extract from frontmatter:
- `node_id` — relative path from vault root, without `.md`
- `title` — frontmatter `title` field
- `aliases` — frontmatter `aliases` list (may be absent)
- `tags` — frontmatter `tags` list
- `category` — directory prefix

Build a lookup table: `node_id → {title, aliases, tags, category, summary}`.

## Step 2: Detect Candidate Pairs

For every pair of pages in the registry, compute a **similarity score** using these signals:

### 2a. Title similarity signals

| Signal | How to assess | Max contribution |
|---|---|---|
| **Token overlap** | Jaccard similarity of lowercased title word-tokens (split on spaces, hyphens, underscores, punctuation) | 0.65 |
| **Edit distance** | Normalized edit distance on lowercased titles: `1 - (edits / max(len_a, len_b))` | 0.40 |
| **Substring containment** | One title is a substring of the other (e.g. "RSC" ⊂ "React Server Components") | 0.50 |
| **Alias cross-match** | Page A's title appears in page B's `aliases`, or vice versa | 0.65 |

Composite title score = `min(max(token_overlap, edit_distance, substring), 0.65) + alias_cross_bonus`.

You don't need exact arithmetic — make a confident judgement about degree of similarity.

**Title extraction note:** Some pages use YAML block scalars (`title: >-` or `title: |`). When the `title:` value is `>-`, `>`, `|`, or `|-`, the actual title is on the next indented line — read it from there. Never compare the literal string `>-` as a title.

### 2b. Semantic signals (cheap pass)

| Signal | Points |
|---|---|
| Same `category` directory | +0.10 |
| Tag overlap ≥ 3 shared tags | +0.15 |
| Tag overlap ≥ 2 shared tags | +0.05 |
| Same first tag (dominant tag) | +0.05 |

### 2c. Threshold

Flag pairs with composite score ≥ **0.75** as **candidates**. Pairs scoring 0.90+ are **high-confidence**.

Score ranges → confidence labels:

| Score | Label |
|---|---|
| ≥ 0.90 | HIGH — almost certainly the same concept |
| 0.75–0.89 | MEDIUM — likely the same, verify |
| 0.60–0.74 | LOW — possible abbreviation or specialisation; skip unless user asks |

Only carry HIGH and MEDIUM candidates into Step 3.

### 2d. Quick exit rule

If the vault has fewer than 10 pages, skip the pair loop and report "vault too small to have meaningful duplicates". If the vault has more than 500 pages, process candidates in batches of 50 pairs — pause and report progress between batches.

## Step 3: Semantic Verdict

For each candidate pair (sorted by score descending):

1. Read both pages in full (full page read — justified because candidate pool is small).
2. Ask: are these pages covering the **same concept**, or are they distinct?

Assign one of three verdicts:

| Verdict | Meaning |
|---|---|
| `merge` | Same concept — different name, abbreviation, alias, or accidental duplicate. Safe to merge. |
| `keep-separate` | Related but distinct — e.g. "Server Actions" vs "Server Components" are related React features, not duplicates. |
| `needs-review` | Ambiguous — substantial overlap but also meaningful differences. Flag for the user to decide. |

Attach a short reason to each verdict (one sentence). This appears in the report and the log.

## Step 4: Audit Report

Always produce this report, even in merge/auto-merge mode (so the user sees what will happen):

```markdown
## Wiki Dedup Report

### High-Confidence Candidates (score ≥ 0.90): N pairs

| Score | Page A | Page B | Verdict | Reason |
|---|---|---|---|---|
| 0.95 | `concepts/rsc.md` | `concepts/react-server-components.md` | merge | "RSC" is the abbreviation; both pages cover identical material |
| 0.91 | `entities/vaswani-2017.md` | `references/attention-is-all-you-need.md` | keep-separate | One is a person stub, one is a paper reference |

### Medium-Confidence Candidates (score 0.75–0.89): N pairs

| Score | Page A | Page B | Verdict | Reason |
|---|---|---|---|---|
| 0.82 | `concepts/fine-tuning.md` | `concepts/finetuning.md` | merge | Same concept, hyphenation variant |

### Needs Human Review: N pairs

| Score | Page A | Page B | Reason |
|---|---|---|---|
| 0.78 | `concepts/agents.md` | `concepts/autonomous-agents.md` | Substantial overlap but "agents" may intentionally be broader |

### Summary
- Pages scanned: N
- Candidate pairs found: M
- Recommended merges: X
- Keep separate: Y
- Needs review: Z
```

In **Audit mode**, stop here and ask: "Run `--merge` to interactively merge the recommended pairs, or `--auto` to merge all high-confidence ones automatically?"

## Step 5: Merge

For each `merge` verdict pair (in merge or auto-merge mode):

In **merge mode**: show the pair and verdict, then ask: "Merge `[Page A]` into `[Page B]`? (yes/skip/review)". Skip on anything other than yes.

In **auto-merge mode**: only process HIGH-confidence (`score ≥ 0.90`) merges without prompting.

### 5a: Pick the canonical page

Apply these tiebreakers in order until one wins:

1. **More incoming wikilinks** — grep the vault for `[[node_id]]` references; higher count wins
2. **Richer content** — longer page body (more lines) wins
3. **More sources** — larger `sources:` list wins
4. **Title length** — longer, more descriptive title wins (e.g. "React Server Components" beats "RSC")
5. **Alphabetical** — earlier title wins

The canonical page is the **survivor**. The other page becomes the **secondary** (to be merged in, then replaced with a redirect stub).

### 5b: Merge content into the canonical page

Read both pages. Update the canonical page:

- **`aliases:`** — add secondary page's title and all its aliases (no duplicates)
- **`tags:`** — merge both tag lists (deduplicate, cap at 5 domain tags + system tags)
- **`sources:`** — merge both source lists (deduplicate)
- **`relationships:`** — merge both relationship lists (deduplicate by target, prefer typed entries over untyped)
- **`base_confidence`** — recompute using the union of sources and the formula from `llm-wiki/SKILL.md`
- **`updated`** — set to now
- **`summary:`** — rewrite to cover the merged scope if the secondary page added new ground
- **Body content** — merge unique sections and bullets from the secondary page. Do not blindly append — integrate the content. Avoid duplicating claims already present in the canonical page. Use `^[inferred]` markers where synthesis is needed.
- **`provenance:`** — recompute after merging

### 5c: Write a redirect stub at the secondary page path

```markdown
---
title: <secondary page title>
redirects_to: "[[<canonical node_id>]]"
aliases: [<secondary aliases>]
category: <secondary category>
tags: []
created: <secondary original created>
updated: <ISO timestamp now>
---

This page has been merged into [[<canonical page title>]].
```

The `redirects_to:` field tells any skill reading this page to follow the redirect rather than treat it as content.

### 5d: Rewrite wikilinks vault-wide

Grep the entire vault for any link pointing at the secondary slug:

- `[[secondary-slug]]` → `[[canonical-slug]]`
- `[[secondary-slug|display text]]` → `[[canonical-slug|display text]]`
- If `OBSIDIAN_LINK_FORMAT=markdown`: `[text](../path/to/secondary.md)` → `[text](../path/to/canonical.md)`

**Safety rules:**
- Never rewrite inside code blocks (``` fences or `inline code`)
- Never rewrite inside the redirect stub itself (that's the one place the old slug should remain legible)
- Never use `rm` or destructive shell ops — only Edit/Write tools
- Rewrite one file at a time, verifying each before moving on
- If a file has zero occurrences, skip it

### 5e: Update tracking files

**`index.md`** — Remove the secondary page's entry. Update the canonical page's entry with the merged summary.

**`.manifest.json`** — For the secondary page's source entries: add `"merged_into": "<canonical node_id>"` to each. For the canonical page: merge in the secondary's `pages_created` and `pages_updated` lists.

**`hot.md`** — Update Recent Activity: "Merged N duplicate pairs; canonical pages updated."

### 5f: Final check

After all merges, grep the vault for any remaining `[[secondary-slug]]` references (in non-stub files). If any survive, report them — the rewrite step may have missed a non-standard link format.

## Step 6: Log

Append to `log.md`:
```
- [TIMESTAMP] DEDUP mode=audit|merge|auto-merge pages_scanned=N pairs_found=M merged=X kept_separate=Y needs_review=Z wikilinks_rewritten=W
```

## Redirect Stub Handling

Other skills should handle redirect stubs as follows:

- **`wiki-export`** — skip pages with `redirects_to:` in frontmatter; they are not content nodes
- **`wiki-query`** — if a search hits a redirect stub, follow `redirects_to:` and read the canonical page instead
- **`wiki-lint`** — validate that every `redirects_to:` wikilink resolves to an existing, non-stub page (a redirect chain — stub pointing to stub — is an error)
- **`cross-linker`** — treat redirect stubs as non-targets; never add a new `[[wikilink]]` pointing at a stub page

## Tips

- **Audit first, always.** Even in auto-merge mode, the audit report is shown. Read it before trusting the results.
- **Check `needs-review` last.** These are the hard cases — don't batch them with obvious merges.
- **Abbreviations are the most common case.** "GPT" / "GPT-4" / "GPT4", "RSC" / "React Server Components", "LLM" / "Large Language Models" — these score high on substring containment and are almost always safe to merge.
- **Different versions are not duplicates.** "GPT-3" and "GPT-4" are related but distinct. "fine-tuning" and "fine-tuning-llms" may be distinct (technique vs. specific application).
- **Run `cross-linker` after dedup.** The redirect stubs leave the graph in a slightly inconsistent state. Cross-linker will tighten it up.
