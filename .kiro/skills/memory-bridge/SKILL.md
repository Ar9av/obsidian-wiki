---
name: memory-bridge
description: >
  Browse and compare wiki knowledge by which AI tool originally produced it. Use this skill when the user
  says "/memory-bridge", "browse codex memory", "what did codex know about X", "show me claude knowledge",
  "cross-tool memory", "what does hermes know that claude doesn't", "show me knowledge from <tool>",
  "compare my AI tool memories", or wants to explore knowledge gaps between tools. Works from any project.
  Diff mode ("what's different", "unique to codex", "gaps between tools") is the killer feature — it surfaces
  blind spots between tools that the user may not know exist.
---

# Memory Bridge — Cross-Tool Knowledge Browser

You are helping the user browse and compare their Obsidian wiki knowledge filtered by which AI tool originally produced it. The wiki tracks source provenance in `.manifest.json` and page `sources:` frontmatter — this skill surfaces that metadata as a navigable view.

## Before You Start

1. Read `~/.obsidian-wiki/config` to get `OBSIDIAN_VAULT_PATH`. Fall back to `.env` inside the obsidian-wiki repo.
2. Read `$OBSIDIAN_VAULT_PATH/.manifest.json` — this is the source-of-truth for what tool produced what.
3. Read `$OBSIDIAN_VAULT_PATH/index.md` for page titles and one-line descriptions.

## Commands

Parse the user's invocation to determine mode:

| Invocation | Mode |
|---|---|
| `/memory-bridge <tool>` | **Browse** — list all wiki pages sourced from `<tool>` |
| `/memory-bridge <tool> "<topic>"` | **Search** — pages from `<tool>` that mention `<topic>` |
| `/memory-bridge diff` | **Diff** — pages unique to each tool; overlap; blind spots |
| `/memory-bridge diff <tool-a> <tool-b>` | **Diff** — compare two specific tools |
| `/memory-bridge map` | **Map** — full origin matrix: every page × every tool that touched it |

Recognized tool names: `claude`, `codex`, `hermes`, `openclaw`, `copilot`, `manual` (hand-written), `ingest` (wiki-ingest documents).

## Step 1: Build the Source Map

Read `.manifest.json`. For each source entry, extract:
- `source_type` — maps to tool name:
  - `claude_conversation`, `claude_memory`, `claude_audit_log`, `claude_desktop_session` → `claude`
  - `codex_rollout`, `codex_index`, `codex_history` → `codex`
  - `hermes_memory`, `hermes_session` → `hermes`
  - `openclaw_memory`, `openclaw_daily_note`, `openclaw_session`, `openclaw_dreams` → `openclaw`
  - `copilot_session`, `copilot_checkpoint`, `copilot_transcript`, `copilot_memory_artifact` → `copilot`
  - `document` → `ingest`
  - anything else → `manual`
- `pages_created` and `pages_updated` — the wiki pages that came out of this source

Build a map:

```
tool_pages = {
  "claude": set(pages created/updated by claude sources),
  "codex":  set(pages created/updated by codex sources),
  ...
}
```

A page can appear in multiple tools' sets if multiple tools contributed to it.

## Step 2: Execute the Mode

### Browse Mode

Filter `tool_pages[<tool>]` and present as a grouped list:

```
## Knowledge from <tool> (<N> pages)

### By category
- concepts/ — N pages
- entities/ — N pages
- skills/   — N pages
...

### Pages
| Page | Category | Tags | Last updated |
|------|----------|------|--------------|
| [[page-name]] | concept | tag1, tag2 | 2026-04-10 |
...
```

Read frontmatter for the listed pages (grep for `^(title|category|tags|updated):`) — do not read full page bodies unless the user asks.

### Search Mode

Within the filtered page set, run:
```
grep -l "<topic>" <pages in tool set>
```
Then grep section headers (`^##`) around matches to give context without full reads. Present results as a ranked list with the matching excerpt.

### Diff Mode

Compute:
- `only_in_a` = `tool_pages[a]` − `tool_pages[b]`
- `only_in_b` = `tool_pages[b]` − `tool_pages[a]`
- `shared` = `tool_pages[a]` ∩ `tool_pages[b]`

If no specific tools are given, compare all tools pairwise (limit to pairs with >0 overlap or unique pages to keep output concise).

Present:

```
## Memory Bridge Diff — <tool-a> vs <tool-b>

### Only in <tool-a> (<N> pages)
These concepts exist in your wiki from <tool-a> sessions but <tool-b> has never touched them.
<list with one-line descriptions from index.md>

### Only in <tool-b> (<N> pages)
<list>

### Shared (<N> pages)
Both tools have contributed to these pages.
<list — only show if ≤15; otherwise just the count>

### Notable gaps
<highlight the most interesting asymmetries — e.g. "codex has 12 pages on build tooling that claude has never seen">
```

### Map Mode

Build a matrix showing every page and which tools have touched it. Cap at 50 rows; sort by number of contributing tools descending (most cross-tool pages first — these are the richest nodes).

```
| Page | claude | codex | hermes | copilot |
|------|--------|-------|--------|---------|
| [[react-patterns]] | ✓ | ✓ | — | ✓ |
| [[rust-ownership]] | — | ✓ | — | — |
```

## Step 3: Spawn impl-validator (if available)

After generating output, if the `impl-validator` skill is available in the current environment, spawn it as a subagent:

```
impl-validator check:
  goal: "Browse/diff wiki knowledge by source tool and surface cross-tool blind spots"
  artifacts: [the output you just generated]
  checks:
    - Did you correctly parse source_type from .manifest.json?
    - Are page counts plausible (not 0 unless vault is empty)?
    - Is the diff symmetric (a−b and b−a are disjoint)?
    - Did you avoid reading full page bodies when not needed?
```

Apply any issues it surfaces before presenting output to the user.

## Step 4: Log

Append to `$OBSIDIAN_VAULT_PATH/log.md`:
```
- [TIMESTAMP] MEMORY-BRIDGE mode=<browse|search|diff|map> tool=<tool> pages_shown=N
```

## Output Conventions

- Always show page counts so the user can calibrate how much knowledge is in each tool's silo.
- Use `[[wikilinks]]` for page references (or standard Markdown links if `OBSIDIAN_LINK_FORMAT=markdown` is set).
- In diff mode, call out the most *surprising* asymmetry explicitly — that's the insight the user came for.
- If `.manifest.json` is empty or missing, say so clearly and suggest running `/wiki-history-ingest` first.
