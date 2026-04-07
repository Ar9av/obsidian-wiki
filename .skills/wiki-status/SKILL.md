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

1. Read `.env` to get `OBSIDIAN_VAULT_PATH`, `OBSIDIAN_SOURCES_DIR`, `CLAUDE_HISTORY_PATH`
2. Read `.manifest.json` at the vault root — this is the ingest tracking ledger

## The Manifest

The manifest lives at `$OBSIDIAN_VAULT_PATH/.manifest.json`. It tracks every source file that has been ingested. If it doesn't exist, this is a fresh vault with nothing ingested.

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
    "~/.claude/projects/-Users-name-my-app/abc123.jsonl": {
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
      "source_path": "~/.claude/projects/-Users-name-my-app",
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

### Any other sources the user has pointed at previously
Check the manifest for source paths outside the standard directories.

## Step 2: Compute the Delta

Compare current sources against the manifest. Classify each source file:

| Status | Meaning | Action needed |
|---|---|---|
| **New** | File exists on disk, not in manifest | Needs ingesting |
| **Modified** | File in manifest, but `modified_at` on disk is newer than `ingested_at` | Needs re-ingesting |
| **Unchanged** | File in manifest, not modified since ingest | Nothing to do |
| **Deleted** | In manifest, but file no longer exists on disk | Note it — wiki pages may be stale |

For Claude history specifically, also compute:
- New projects (directories in `~/.claude/projects/` not in manifest)
- New conversations within existing projects
- Updated memory files

## Step 3: Report the Status

Present a clear summary:

```markdown
# Wiki Status

## Overview
- **Total wiki pages:** 87 across 6 categories
- **Total sources ingested:** 42
- **Projects tracked:** 6
- **Last ingest:** 2026-04-06T11:00:00Z

## Delta (what's changed since last ingest)

### New sources (never ingested): 12
| Source | Type | Size |
|---|---|---|
| ~/Documents/research/new-paper.pdf | document | 2.1 MB |
| ~/.claude/projects/-Users-.../session-xyz.jsonl | claude_conversation | 340 KB |
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
```

## Step 4: Recommend Action

Based on the delta, recommend one of:

| Situation | Recommendation |
|---|---|
| Delta is small (<20% of total) | **Append** — just ingest the new/modified sources |
| Delta is large (>50% of total) | **Rebuild** — archive and reprocess everything |
| Many deleted sources | **Lint first** — check for stale pages, then decide |
| First time / empty vault | **Full ingest** — process everything |
| User just wants to see status | **No action** — just report |

Tell the user:
- "You have X new sources and Y modified sources. I'd recommend [append/rebuild]."
- "Want me to [ingest the delta / rebuild from scratch / just look at a specific project]?"

## Insights Mode

Triggered when the user asks something like "wiki insights", "what's central in my wiki", "show me the hubs", "cross-domain bridges", "what pages are most important", or "wiki structure". This mode is *additive* — it doesn't replace the delta report, it analyzes the *shape* of the wiki itself.

Where the delta report tells the user what's pending, insights mode tells them what they've already built and where the interesting structure lives. Complements `wiki-lint` (which finds *problems*) by surfacing *interesting structure*.

### What to compute

1. **Anchor pages (top hubs).** Pages with the highest number of incoming `[[wikilinks]]`. These are the load-bearing concepts of the wiki — usually the right places to start reading.
   - Glob all `.md` files in the vault
   - For each page, Grep the rest of the vault for `[[<page-name>]]` and count incoming references
   - Rank top 10
   - Also note outgoing link counts — pages that are both heavily incoming *and* heavily outgoing are connector hubs

2. **Cross-domain bridges.** Pairs of pages connected via a 2-hop wikilink path (A → M → B) where A and B share *no tags*. These are accidental bridges between disjoint topic areas — usually the most interesting threads for the user to revisit.
   - For each page A, walk one hop to its outgoing links
   - From each of those, walk one more hop
   - Filter to A→M→B where the tag sets of A and B are disjoint
   - Rank by how disjoint the tag sets are; show top 10

3. **Orphan-adjacent suggestions.** Pages that are linked from an anchor page but link to *nothing themselves*. These are dead-ends in heavily-trafficked parts of the wiki — prime candidates for cross-linking.

4. **Cluster sketch.** Group anchor pages by shared tags into rough clusters and label each with its dominant tag. (No real graph algorithm — just tag intersection. Obsidian's native graph view does the proper version.)

### Output

Write the result to `_insights.md` at the vault root. This file is regenerable on every run — overwrite freely. Suggested gitignore: add `_insights.md` if the user version-controls their vault.

```markdown
# Wiki Insights — <TIMESTAMP>

## Anchor Pages (top 10 hubs)
| Page | Incoming | Outgoing | Tags |
|---|---|---|---|
| [[concepts/transformer-architecture]] | 23 | 8 | ml, architecture |
| [[entities/andrej-karpathy]] | 17 | 4 | person, ml |
| ...

## Cross-Domain Bridges
- [[concepts/scaling-laws]] → [[skills/cooking-techniques]] via [[concepts/exponential-growth]]
  - Tags share: *none* — accidental bridge between disjoint topics
- ...

## Orphan-Adjacent (dead-end pages near hubs)
- [[concepts/foo]] — linked from 3 hubs but has 0 outbound links. Cross-linker candidate.
- ...

## Rough Clusters
- **#ml** — transformer-architecture, attention-mechanism, scaling-laws, andrej-karpathy
- **#systems** — distributed-consensus, raft, paxos
- ...

## Suggested Questions
- Why does [[concepts/scaling-laws]] keep showing up next to cooking content? (cross-domain bridge)
- [[concepts/foo]] is a dead-end — what should it link to?
```

After writing the file, append to `log.md`:
```
- [TIMESTAMP] STATUS_INSIGHTS anchors=10 bridges=N orphan_adjacent=M
```

### When to skip

- Vaults with fewer than 20 pages — there's not enough graph structure for the analysis to mean anything. Tell the user and skip.
- After a fresh `wiki-rebuild` — wait until at least one ingest has happened.

## Notes

- If the manifest doesn't exist, report everything as "new" and recommend a full ingest
- This skill only reads and reports — it doesn't modify anything (except writing `_insights.md` in insights mode, which is regenerable)
- The actual ingest work is done by the ingest skills (`wiki-ingest`, `claude-history-ingest`, `data-ingest`)
- Those skills are responsible for updating the manifest after they finish
