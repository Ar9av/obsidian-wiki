---
name: wiki-status
description: >
  Show the current state of the wiki — what's been ingested, what's pending, and the delta between sources
  and wiki content. Use this skill when the user asks "what's the status", "how much is ingested",
  "what's left to process", "show me the delta", "what changed since last ingest", "wiki dashboard",
  or wants an overview of their knowledge base health and completeness. Also use before deciding whether
  to append or rebuild. Includes an insights mode triggered by "wiki insights", "what's central",
  "show me the hubs", "central pages", "what's connected", "wiki structure" — analyzes the shape of
  the wiki itself to surface top hubs, cross-domain bridges, and orphan-adjacent pages.
---

# Wiki Status — Audit & Delta

You are computing the current state of the wiki: what's been ingested, what's new since last ingest, and what the delta looks like. This helps the user decide whether to append (ingest the delta) or rebuild (archive and reprocess everything).

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (inline `@name` override → walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH`, `OBSIDIAN_SOURCES_DIR`, `CLAUDE_HISTORY_PATH`, and `CODEX_HISTORY_PATH`.
2. Read `.manifest.json` at the vault root — this is the ingest tracking ledger

## The Manifest

The manifest lives at `$OBSIDIAN_VAULT_PATH/.manifest.json`. It tracks every source file that has been ingested. If it doesn't exist, this is a fresh vault with nothing ingested.

> **Source keys are canonical absolute paths** (`~` and env vars expanded). Never mix `~`-relative and absolute keys — the same file would be tracked twice and re-ingested. See `llm-wiki/SKILL.md` → `.manifest.json`. Repair a mixed manifest with `scripts/manifest.py normalize <vault>`.

```json
{
  "version": 1,
  "last_updated": "2026-04-06T10:30:00Z",
  "sources": {
    "/absolute/path/to/file.md": {
      "ingested_at": "2026-04-06T10:30:00Z",
      "size_bytes": 4523,
      "modified_at": "2026-04-05T08:00:00Z",
      "source_type": "document",
      "project": null,
      "pages_created": ["concepts/transformers.md"],
      "pages_updated": ["entities/vaswani.md"]
    },
    "/Users/name/.claude/projects/-Users-name-my-app/abc123.jsonl": {
      "ingested_at": "2026-04-06T11:00:00Z",
      "size_bytes": 128000,
      "modified_at": "2026-04-06T09:00:00Z",
      "source_type": "claude_conversation",
      "project": "my-app",
      "pages_created": ["entities/my-app.md"],
      "pages_updated": ["skills/react-debugging.md"]
    }
  },
  "projects": {
    "my-app": {
      "source_path": "/Users/name/.claude/projects/-Users-name-my-app",
      "vault_path": "projects/my-app",
      "last_ingested": "2026-04-06T11:00:00Z",
      "conversations_ingested": 5,
      "conversations_total": 8,
      "memory_files_ingested": 3
    }
  },
  "stats": {
    "total_sources_ingested": 42,
    "total_pages": 87,
    "total_projects": 6,
    "last_full_rebuild": null
  }
}
```

## Step 1: Scan Current Sources

Build an inventory of everything available to ingest right now:

### Documents (from `OBSIDIAN_SOURCES_DIR`)
```
Glob each directory in OBSIDIAN_SOURCES_DIR for all text files
Record: path, size, modification time
```

### Claude History (from `CLAUDE_HISTORY_PATH`)
```
Glob: ~/.claude/projects/*/          → project directories
Glob: ~/.claude/projects/*/*.jsonl   → conversation files
Glob: ~/.claude/projects/*/memory/*.md → memory files
Record: path, size, modification time, parent project
```

### Codex History (from `CODEX_HISTORY_PATH`)
```
Glob: ~/.codex/session_index.jsonl            → session inventory index
Glob: ~/.codex/sessions/**/rollout-*.jsonl    → session rollout transcripts
Glob: ~/.codex/history.jsonl                  → optional local history log
Glob: ~/.codex/archived_sessions/**/rollout-*.jsonl → archived rollouts (if user wants archive coverage)
Record: path, size, modification time, inferred project from cwd when available
```

### Any other sources the user has pointed at previously
Check the manifest for source paths outside the standard directories.

## Step 2: Compute the Delta

Compare current sources against the manifest. Classify each source file:

| Status | Meaning | Action needed |
|---|---|---|
| **New** | File exists on disk, not in manifest | Needs ingesting |
| **Modified** | File in manifest, hash differs from `content_hash` | Needs re-ingesting |
| **Touched** | File in manifest, mtime newer but hash unchanged | Skip — content identical, no re-ingest needed |
| **Unchanged** | File in manifest, mtime and hash both match | Nothing to do |
| **Deleted** | In manifest, but file no longer exists on disk | Note it — wiki pages may be stale |

When a manifest entry has no `content_hash` (older entry), fall back to mtime comparison only.

For Claude history specifically, also compute:
- New projects (directories in `~/.claude/projects/` not in manifest)
- New conversations within existing projects
- Updated memory files

For Codex history specifically, also compute:
- New rollout files under `sessions/**`
- Updated `session_index.jsonl` entries (session title/freshness changes)
- Archived rollout delta only when archive coverage is requested

## Step 3: Report the Status

**Visibility tally (before rendering the report):** Grep frontmatter across all vault `.md` pages for `visibility/internal` and `visibility/pii` tag values. Count:
- `public` = pages with `visibility/public` tag **or** no `visibility/` tag at all
- `internal` = pages with `visibility/internal` tag
- `pii` = pages with `visibility/pii` tag

Include this in the Overview section as `Page visibility: N public · M internal · K pii`. Skip the line if all pages are untagged (fully public vault).

Present a clear summary:

```markdown
# Wiki Status

## Overview
- **Total wiki pages:** 87 across 6 categories
- **Page visibility:** 72 public · 11 internal · 4 pii
- **Total sources ingested:** 42
- **Projects tracked:** 6
- **Last ingest:** 2026-04-06T11:00:00Z
- **Staged writes pending:** 4 pages · 2 patches (oldest: 3 days ago)  ← only when WIKI_STAGED_WRITES=true

## Delta (what's changed since last ingest)

### New sources (never ingested): 12
| Source | Type | Size |
|---|---|---|
| ~/Documents/research/new-paper.pdf | document | 2.1 MB |
| ~/.claude/projects/-Users-.../session-xyz.jsonl | claude_conversation | 340 KB |
| ~/.codex/sessions/2026/04/12/rollout-...jsonl | codex_rollout | 220 KB |
| ... | | |

### Modified sources (need re-ingesting): 3
| Source | Last ingested | Last modified | Delta |
|---|---|---|---|
| ~/notes/architecture.md | 2026-04-01 | 2026-04-05 | 4 days newer |
| ... | | | |

### New projects (not yet in wiki): 2
- **tractorex** (3 conversations, 2 memory files)
- **papertech** (1 conversation, 0 memory files)

### Deleted sources (ingested but gone): 0

## Summary
- **Ready to ingest:** 12 new + 3 modified = 15 sources
- **Up to date:** 27 sources unchanged
- **Recommendation:** Append (delta is small relative to total)

## Token Footprint (estimated)

| Scope | Pages | ~Tokens |
|---|---|---|
| core tier | 12 | 18,400 |
| supporting tier | 87 | 94,200 |
| peripheral tier | 43 | 31,600 |
| **Full wiki (all)** | **142** | **144,200** |

Index-only pass (frontmatter + summaries): ~8,900 tokens
Typical query (index + 5 full pages):      ~14,200 tokens

⚠️  Full wiki exceeds 100K tokens. Consider:
  - Demoting peripheral pages (promote tier suggestions from wiki-status insights mode)
  - Running /wiki-lint --consolidate to merge near-duplicates
  - Using wiki-query fast mode for most queries
```

## Step 3b: Compute Token Footprint

After building the status summary, compute the token footprint estimate:

1. **Per-tier page sizes** — Glob all `.md` pages. Read the `tier:` frontmatter field of each (cheap grep). Group pages by tier value (`core`, `supporting`, `peripheral`; unset → `supporting`).

2. **Estimate tokens** — For each page, estimate token count as `file_size_bytes / 4` (4 chars/token heuristic — no actual tokenizer needed). Sum per tier and total.

3. **Index-only estimate** — Estimate the cost of an index-only pass: sum `len(title) + len(summary) + len(tags)` for each page frontmatter (~100 chars each on average), divided by 4.

4. **Typical query estimate** — Index-only estimate + average full-read cost of 5 pages (`total_chars / total_pages * 5 / 4`).

5. **Threshold check** — Read `WIKI_TOKEN_WARN_THRESHOLD` from config (default: `100000`). If `0`, skip the warning. If full-wiki token estimate exceeds the threshold, emit a `⚠️` warning with the three remediation suggestions shown in the template above.

6. **Include in every standard status run** — both normal and insights mode. The methodology note (`4 chars/token heuristic`) appears as a footnote below the table.

## Step 4: What to Do Next

Replace the old single-line Recommendation with a ranked **What to Do Next** section. Gather these signals before rendering:

### 4a: Gather signals

0. **Staged writes pending** (only when `WIKI_STAGED_WRITES=true`) — Glob `$OBSIDIAN_VAULT_PATH/_staging/**/*.md` and `**/*.patch.md`. Count new pages and patches separately. Report the oldest file's age (mtime). This is always listed first if any staged files exist — it has the highest intent signal (the LLM already did the work; the human just needs to review).

1. **`_raw/` files** — list every file at the top level of `$OBSIDIAN_VAULT_PATH/_raw/` that isn't a `.gitkeep`, excluding the `_archived/` subdirectory (already-promoted drafts kept for provenance, not pending work). Count and name them.

2. **Stale core pages** — scan all vault `.md` files. A page is "stale" when its `updated` frontmatter field is ≥90 days before today's date AND it has ≥5 incoming wikilinks (i.e., it's "core" — other pages depend on it). List them by name + last-updated date.

3. **Orphan pages** — pages with zero incoming wikilinks. To compute: glob all `.md` pages, extract every `[[wikilink]]`, count references to each page, collect pages with `incoming == 0`. Show up to 5 names; report total count.

4. **Synthesis opportunities** — check `hot.md` for any recent `/wiki-synthesize` run summary. If the last synthesis run reported N opportunities, surface that count. If no synthesis has been run recently (not in `hot.md` or `log.md` within last 14 days), flag it as "synthesis scan overdue".

5. **Source delta** — from Step 2: count of new + modified sources ready to ingest.

6. **Lint issues** — check `log.md` for a recent `/wiki-lint` run (within last 30 days). If a recent run recorded broken links or missing frontmatter, surface the count. If no lint run appears in the log, flag "lint not run recently".

### 4b: Rank and render

Score each category and emit a ranked list, **capped at 6 items**. Always rank in this priority order (skip a category if its count is 0 or it has nothing to report):

| Priority | Category | Trigger |
|---|---|---|
| 0 | Staged writes pending | Any `.md`/`.patch.md` in `_staging/` (only when `WIKI_STAGED_WRITES=true`) |
| 1 | `_raw/` files waiting | Any files present in `_raw/` |
| 2 | Stale core pages | Any page: updated ≥90 days ago AND ≥5 incoming links |
| 3 | Orphan pages | Any pages with zero incoming wikilinks |
| 4 | Synthesis opportunities | N opportunities from last synthesize run, OR scan overdue |
| 5 | New/modified sources | Count from delta in Step 2 |
| 6 | Lint issues | Known issues from last lint run, OR lint overdue |

Render as:

```markdown
## What to Do Next

0. 📋  6 staged pages waiting for review (oldest: 3 days ago)
   → 4 new pages + 2 patches in _staging/
   run: /wiki-stage-commit

1. 📥  Ingest 3 files waiting in _raw/
   → architecture-notes.md, meeting-2026-05-10.md, paper-draft.pdf
   run: /wiki-ingest

2. 🔄  Refresh 2 stale core pages (not updated in 90+ days)
   → [[System Architecture]] (last updated 2026-02-10), [[API Design]] (2026-01-15)
   run: open these pages and re-run /wiki-update

3. 🔗  Link 7 orphan pages  →  run: /cross-linker
   Disconnected: [[Redis Caching]], [[JWT Tokens]], +5 more

4. 🧩  2 synthesis opportunities identified  →  run: /wiki-synthesize
   [[Redis Caching]] × [[Session Management]] (co-occur in 8 pages)

5. ✅  4 sources modified since last ingest  →  run: /wiki-ingest (append mode)

6. 🩺  Lint not run in 30+ days — run: /wiki-lint
```

**Empty state:** If all categories have nothing to report (no staged files, no `_raw/` files, no orphans, no stale pages, no synthesis opportunities, no new sources, no lint issues), output instead:

```markdown
## What to Do Next

✅  Wiki is healthy — nothing urgent.
    All sources up to date · no orphans · no stale core pages · no _raw/ files pending · no staged writes
```

**Overflow:** If more than 6 items would be shown, add a footer line: `_(N more items available — run /wiki-status --full to see all)_`. The `--full` flag is not yet implemented; this is forward-looking copy that sets expectations.

## Insights Mode

Triggered when the user asks something like "wiki insights", "what's central in my wiki", "show me the hubs", "cross-domain bridges", "what pages are most important", or "wiki structure". This mode is *additive* — it doesn't replace the delta report, it analyzes the *shape* of the wiki itself.

Where the delta report tells the user what's pending, insights mode tells them what they've already built and where the interesting structure lives. Complements `wiki-lint` (which finds *problems*) by surfacing *interesting structure*.

### What to compute

**First, build the wikilink graph.** Glob all `.md` pages, extract every `[[wikilink]]`, and build:
- `incoming[page]` = count of other pages that link to this page
- `outgoing[page]` = count of pages this page links out to
- `tags[page]` = set of tags from frontmatter
- `category[page]` = directory prefix (concepts/, entities/, skills/, etc.)

You'll reuse this graph across all sections below.

---

1. **Anchor pages (top hubs).** Pages with the most incoming links — the load-bearing concepts.
   - Rank all pages by `incoming` count, take top 10
   - For each, note both incoming and outgoing counts: pages with high incoming *and* high outgoing are connector hubs (most valuable)
   - Pages with high incoming but zero outgoing are sink hubs — flag as cross-linker candidates

2. **Bridge pages.** Pages that connect otherwise-disconnected tag clusters — removing them would partition the graph. These are often more structurally important than raw hub count suggests.
   - For each page P, find pairs of pages (A, B) where:
     - A links to P, B is linked from P (or vice versa)
     - A and B share **no tags** with each other
     - P is the only path between A's tag cluster and B's tag cluster within 2 hops
   - Rank by how many cross-cluster pairs P bridges; show top 5
   - Label each: "`P` bridges `[tag-cluster-A]` ↔ `[tag-cluster-B]`"

3. **Tag cluster cohesion.** For each tag with ≥ 5 pages, score how tightly the pages within it are interconnected:
   - `n` = number of pages sharing this tag
   - `actual_links` = number of wikilinks between any two pages in this tag group
   - `cohesion = actual_links / (n × (n−1) / 2)` — ratio of actual links to maximum possible
   - **Fragmented clusters** (cohesion < 0.15, n ≥ 5): these pages share a topic but aren't woven together. Surface them as cross-linker targets.
   - Show top 5 tags by cohesion (strongest clusters) and bottom 5 (most fragmented)

4. **Surprising connections.** Cross-category wikilinks that are non-obvious — scored by how unexpected they are:
   - Score each wikilink that crosses category boundaries (e.g., `concepts/` → `entities/`, `skills/` → `synthesis/`):
     - **+3** if the linking page or claim is marked `^[ambiguous]` (uncertain connection, worth reviewing)
     - **+2** if the linking page is marked `^[inferred]` (synthesized, not directly stated)
     - **+2** if the categories are in different knowledge layers (e.g., `concepts` ↔ `entities` more surprising than `concepts` ↔ `concepts`)
     - **+2** if source page has ≤ 2 total links (peripheral) but target has ≥ 8 (hub) — unexpected reach from edge to center
   - Show top 5 scored connections with a plain-language reason for each

5. **Orphan-adjacent suggestions.** Pages linked from a top-10 hub but with zero outgoing links of their own. Dead-ends in high-traffic areas — prime cross-linker candidates.

6. **Rough clusters.** Group anchor pages by dominant tag. (Simple tag intersection — just for orientation.)

7. **Graph delta since last run.** Compare the current link graph to the snapshot stored in the previous `_insights.md`:
   - Read the `<!-- GRAPH_SNAPSHOT: ... -->` line at the bottom of the previous `_insights.md` (if it exists) — it contains a compact JSON edge list
   - Compute: new pages added, pages removed, new wikilinks created, wikilinks removed
   - Flag: pages that were isolated last run but now have incoming links ("newly connected: X, Y")
   - Flag: pages that lost incoming links since last run ("link target may have been renamed: A, B")
   - If no previous snapshot exists, skip this section

8. **Tier assignment suggestions.** After computing hubs and bridges, recommend `tier:` changes. Never write `tier:` to pages — only surface suggestions so the human can decide.
   - **Promote to `core`:** pages with ≥5 incoming links OR top-5 bridge position that currently have `tier: supporting` or no `tier:` field
   - **Demote to `peripheral`:** pages with ≤1 incoming link AND not updated in 90+ days that currently have `tier: supporting` or `tier: core`
   - Show up to 10 suggestions (promotions first, then demotions), formatted as:
     ```
     Tier Suggestions:
     ↑ core    [[concepts/attention-mechanism]] — 14 incoming links, currently tier=supporting
     ↑ core    [[entities/andrej-karpathy]]     — bridge (3 cluster pairs), currently unset
     ↓ peripheral [[concepts/old-concept]]       — 0 incoming, 120 days stale
     ```
   - If all high-link pages already have `tier: core` and all low-link pages have `tier: peripheral`, emit: "Tier assignments look healthy — no changes suggested."

9. **Suggested questions.** Questions this wiki structure is uniquely positioned to answer — or that reveal gaps:
   - From `^[ambiguous]` claims: "Resolve: What is the exact relationship between `X` and `Y`?"
   - From bridge pages: "Explore: Why does `P` connect `[cluster-A]` to `[cluster-B]`?"
   - From pages with zero incoming links: "Link: `X` has no incoming links — what should reference it?"
   - From fragmented clusters (cohesion < 0.15): "Audit: Should tag `[T]` be split into more focused sub-tags?"
   - Show up to 7, prioritizing AMBIGUOUS first, then bridge nodes, then isolates

---

### Output

Write the result to `_insights.md` at the vault root. Overwrite freely — it's regenerable. At the very end, embed a compact graph snapshot as an HTML comment so the next run can diff against it.

```markdown
# Wiki Insights — <TIMESTAMP>

## Anchor Pages (top 10 hubs)
| Page | Incoming | Outgoing | Note |
|---|---|---|---|
| [[concepts/transformer-architecture]] | 23 | 8 | connector hub |
| [[entities/andrej-karpathy]] | 17 | 0 | sink hub — cross-linker candidate |

## Bridge Pages (top 5)
| Page | Bridges | Cross-cluster pairs |
|---|---|---|
| [[concepts/exponential-growth]] | #ml ↔ #economics | 4 pairs |

## Tag Cluster Cohesion
### Most cohesive (well-linked)
- **#ml** — 12 pages, cohesion 0.41
### Most fragmented (cross-linker targets)
- **#systems** — 7 pages, cohesion 0.06 ⚠️ run cross-linker on this tag

## Surprising Connections (top 5)
- [[concepts/scaling-laws]] → [[entities/gordon-moore]] — score 5
  - Reason: cross-layer (concepts ↔ entities), marked ^[inferred]
- ...

## Orphan-Adjacent (dead-ends near hubs)
- [[concepts/foo]] — linked from 3 hubs, 0 outbound links

## Rough Clusters
- **#ml** — transformer-architecture, attention-mechanism, scaling-laws
- **#systems** — distributed-consensus, raft, paxos

## Graph Delta Since Last Run
- +3 new pages, +11 new wikilinks
- Newly connected: [[concepts/bar]], [[entities/baz]]
- Lost incoming links: [[references/old-paper]] (target may have been renamed)

## Tier Suggestions
↑ core    [[concepts/attention-mechanism]] — 14 incoming links, currently tier=supporting
↑ core    [[entities/andrej-karpathy]]     — top bridge (4 cluster pairs), currently unset
↓ peripheral [[concepts/old-concept]]       — 0 incoming, 132 days stale

## Questions Worth Asking
1. Resolve: What is the exact relationship between `scaling-laws` and `moore's-law`? (^[ambiguous] claim)
2. Explore: Why does `exponential-growth` bridge #ml and #economics?
3. Link: `references/foo.md` has no incoming links — what should reference it?
4. Audit: Should tag `#systems` be split? (cohesion 0.06, 7 pages)

<!-- GRAPH_SNAPSHOT: {"nodes":["concepts/foo","entities/bar"],"edges":[["concepts/foo","entities/bar"]]} -->
```

After writing the file, append to `log.md`:
```
- [TIMESTAMP] STATUS_INSIGHTS anchors=10 bridges=N cohesion_checked=T surprising=5 questions=7 delta="+N pages +M links" tier_suggestions=N
```

### When to skip

- Vaults with fewer than 20 pages — not enough graph structure. Tell the user and skip.
- After a fresh `wiki-rebuild` — wait until at least one ingest has happened.

## Notes

- If the manifest doesn't exist, report everything as "new" and recommend a full ingest
- This skill only reads and reports — it doesn't modify anything (except writing `_insights.md` in insights mode, which is regenerable)
- The actual ingest work is done by the ingest skills (`wiki-ingest`, `claude-history-ingest`, `codex-history-ingest`)
- Those skills are responsible for updating the manifest after they finish

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
