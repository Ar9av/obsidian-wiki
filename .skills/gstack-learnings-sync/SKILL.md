---
name: gstack-learnings-sync
description: >
  Sync new gstack learnings into the Obsidian wiki. Reads ~/.gstack/projects/*/learnings.jsonl,
  finds entries added since the last sync, and appends them to matching wiki project pages
  (or creates new pages for unknown projects). Use when the user says "sync gstack learnings",
  "update wiki from gstack", "pull in new learnings", "what did gstack learn recently",
  or after any gstack review session that produced new learnings. Also invoke automatically
  if the vault has a .gstack-sync-pending marker file.
---

# gstack Learnings Sync

Syncs new entries from gstack's `learnings.jsonl` files into your Obsidian wiki. Each entry
was written by a gstack review skill and captures a concrete pitfall, pattern, or
architectural insight from real project work.

## Before You Start

1. Read `~/.obsidian-wiki/config` → get `OBSIDIAN_VAULT_PATH`
2. Read `$VAULT/.manifest.json` → find `gstack_learnings_last_sync` (ISO timestamp, may be absent on first run)
3. Read `$VAULT/index.md` → know which project pages exist

## Step 1: Collect New Learnings

For each directory under `~/.gstack/projects/`:

```bash
find ~/.gstack/projects -name "learnings.jsonl" | sort
```

Read each `learnings.jsonl` file. Each line is a JSON object:

```json
{
  "skill": "plan-eng-review",
  "type": "pitfall",
  "key": "<short-stable-id>",
  "insight": "...",
  "confidence": 10,
  "source": "observed",
  "files": ["path/to/file.ext"],
  "ts": "<ISO timestamp>"
}
```

Keep only entries where `ts` is newer than `gstack_learnings_last_sync`. On first run, process all entries.

## Step 2: Group by Project

Group new entries by their parent directory name (the gstack project slug):

```
~/.gstack/projects/<slug>/learnings.jsonl  →  slug: <slug>
```

## Step 3: Map gstack Slug → Wiki Project Page

gstack slugs are derived from directory names and don't always match wiki project names exactly.
Use this matching order (stop at first match):

1. **Exact slug match** — look for `projects/<slug>/<slug>.md` in the vault
2. **Prefix-stripped match** — strip common org/team prefixes the user has configured (e.g. `<org>-`, `<team>-`) and retry
3. **Normalized match** — lowercase the slug and replace `_` with `-`, retry
4. **Fuzzy match** — compare slug words against existing project page filenames and titles
5. **No match** — create a new project page (Step 4b)

Examples (illustrative — real slugs depend on the user's gstack project layout):
- `<org>-foo-service` → `projects/foo-service/foo-service.md` (prefix stripped)
- `My_Project` → `projects/my-project/my-project.md` (normalized)
- `unknown-project` → no match → create `projects/unknown-project/unknown-project.md`

## Step 4a: Update Existing Project Pages

For each project with new learnings and an existing wiki page:

1. Read the page
2. Find the `## gstack Learnings` section (it may already exist from a previous sync)
3. If the section exists: append new entries inside it, under a `### <YYYY-MM-DD>` sub-heading grouping entries from the same day
4. If the section doesn't exist: add it before `## Related Pages` (or at the end if that section is absent)

Format each learning as:

```markdown
- **[type] `key`:** insight text.^[source]
  Files: `path/to/file.py` (only include if files array is non-empty)
```

Where:
- `type` is one of: `pitfall` | `pattern` | `architecture` | `operational` | `preference`
- `source` annotation maps to: `observed` → `[extracted]`, `inferred` → `[inferred]`, `cross-model` → `[cross-model]`, `user-stated` → `[user-stated]`
- Omit the files line if `files` is empty or absent

Update the page's `updated` frontmatter to today's date and add the learnings source to `sources`.

## Step 4b: Create New Project Pages

If no matching wiki page exists, create `$VAULT/projects/<normalized-slug>/<normalized-slug>.md`:

```markdown
---
title: >-
  <Human-readable project name from slug>
category: project
tags: [<infer from learning types and key terms>]
sources: [~/.gstack/projects/<slug>/learnings.jsonl]
summary: >-
  <1-2 sentence summary inferred from the learnings>
provenance:
  extracted: 0.8
  inferred: 0.2
  ambiguous: 0.0
created: <today>
updated: <today>
---

# <Project Name>

<One paragraph inferred from the learnings — what this project appears to be about.>

## gstack Learnings

<entries formatted as in Step 4a>

## Related Pages

<any obvious connections based on the project name and learning content>
```

## Step 5: Update Tracking

### Update `.manifest.json`

Set `gstack_learnings_last_sync` to the `ts` of the newest entry processed:

```json
{
  "gstack_learnings_last_sync": "2026-04-23T20:30:00.000Z"
}
```

Also remove `.gstack-sync-pending` from the vault root if it exists:
```bash
rm -f "$VAULT/.gstack-sync-pending"
```

### Update `index.md`

Add any newly created project pages under the appropriate section.

### Update `log.md`

```
- [TIMESTAMP] GSTACK_SYNC projects=N entries_new=M pages_updated=X pages_created=Y
```

## Step 6: Report

Tell the user:
- How many projects were scanned
- How many new entries were found
- Which pages were updated vs created
- The date range of the new entries

If zero new entries: "No new gstack learnings since <last sync date>. Wiki is up to date."

## Tips

- If an entry's `insight` is long, keep the wiki entry concise — the key claim, not a restatement of the whole sentence.
- If multiple entries share the same `key` (duplicates from retry runs), deduplicate by `key` per project — keep the entry with the highest confidence or most recent `ts`.
- `trusted: false` on an entry is gstack's internal flag meaning the entry hasn't been reviewed by the user. Include it in the wiki but you can note `(unverified)` if the user prefers — don't filter it out.
