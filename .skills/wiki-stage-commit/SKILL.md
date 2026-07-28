---
name: wiki-stage-commit
description: >
  Review and promote staged wiki pages to their final locations. Use when WIKI_STAGED_WRITES=true
  and the user says "/wiki-stage-commit", "review staged pages", "commit staged writes",
  "promote staged pages", "approve staged changes", or "what's waiting in staging".
  Shows each staged file, lets the user accept or reject it, and moves accepted files to
  their final wiki locations. Rejected files are moved back to _raw/ for manual editing.
---

# Wiki Stage Commit — Staged Write Promotion

You are reviewing LLM-written pages that are waiting in `_staging/` for human approval before they land in the live wiki. This skill is only useful when `WIKI_STAGED_WRITES=true` in the vault config.

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md`. This gives `OBSIDIAN_VAULT_PATH`, `OBSIDIAN_LINK_FORMAT` (default `wikilink`), and `WIKI_STAGED_WRITES`.
2. If `WIKI_STAGED_WRITES` is not set or is `false`, tell the user: "Staged writes mode is not enabled. Set `WIKI_STAGED_WRITES=true` in your `.env` to use this feature." Then stop.
3. Read the `_staging/` directory inventory.

## Invocation Forms

```
/wiki-stage-commit               # interactive review: show each file and ask accept/reject
/wiki-stage-commit --all         # accept all staged files without per-file review
/wiki-stage-commit --reject-all  # reject all staged files (move to _raw/ for manual editing)
/wiki-stage-commit --list        # list staged files with summary, no changes
```

## Step 1: Inventory Staged Files

Glob `$OBSIDIAN_VAULT_PATH/_staging/**/*.md` — these are the pending pages.

Also glob `$OBSIDIAN_VAULT_PATH/_staging/**/*.patch.md` — these are pending *updates* to existing pages (diff-style files showing proposed additions and deletions).

Report the inventory:

```
Staged files: 4 new pages, 2 updates

New pages:
  _staging/concepts/attention-mechanism.md        (ingested 2 days ago)
  _staging/entities/andrej-karpathy.md            (ingested 2 days ago)
  _staging/skills/fine-tuning-llms.md             (ingested yesterday)
  _staging/references/attention-is-all-you-need.md (ingested 3 hours ago)

Updates (patch files):
  _staging/concepts/transformer-architecture.patch.md  (target: concepts/transformer-architecture.md)
  _staging/skills/prompt-engineering.patch.md          (target: skills/prompt-engineering.md)
```

If `_staging/` is empty, report: "Nothing staged. All writes have been committed or no staged writes have been produced yet."

## Step 2: Per-File Review (interactive mode)

For each staged file (new pages first, then updates):

### For new pages:

Display a summary:

```
--- New page: concepts/attention-mechanism.md ---
Title:    Attention Mechanism
Tags:     #ml #architecture
Summary:  Core building block of transformers — computes weighted sum of values based on query-key similarity.
Tier:     supporting
Confidence: 0.72
Sources:  papers/attention.pdf

[Preview first 20 lines of body]
...

Accept [a], Reject [r], Skip [s], Preview full [p]?
```

### For patch files:

Display a structured diff:

```
--- Update: concepts/transformer-architecture.md ---
Source: _staging/concepts/transformer-architecture.patch.md

Proposed additions (+):
+ Transformers outperform RNNs on tasks requiring long-range dependencies. ^[inferred]
+ New source: papers/survey-2026.pdf

Proposed deletions (-):
- The attention mechanism was first described in [Bahdanau 2015].  (to be replaced by updated claim)

⚠️  Conflict check: target page was modified 3 days after staging. Review carefully.

Accept [a], Reject [r], Skip [s], Preview full diff [p]?
```

If `--all` flag is set, skip prompting and accept every file.
If `--reject-all` flag is set, skip prompting and reject every file.
If `--list` flag is set, stop after printing the inventory (Step 1).

## Step 3: Apply Decisions

### Accepting a new page

1. Move `_staging/<category>/page.md` → `<category>/page.md` (the final location)
2. Remove the staged file

### Accepting a patch/update

1. Read the current page at the target path
2. Apply the proposed additions and deletions (merge, don't just overwrite)
3. Update the `updated` frontmatter timestamp
4. Remove the staged patch file

### Rejecting a file

Move it to `$OBSIDIAN_VAULT_PATH/_raw/` for manual editing:
- `_staging/concepts/page.md` → `_raw/rejected-concepts-page.md`
- `_staging/concepts/page.patch.md` → `_raw/rejected-patch-concepts-page.md`
- Prefix with `rejected-` so the user can identify it

### Conflict detection on patch accept

Before applying a patch, check whether the target page's `updated` frontmatter is newer than the patch file's own `updated` field:
- If the target was modified AFTER the patch was staged, warn: `⚠️ Conflict: target was updated since this patch was staged. Applying may lose recent changes.`
- Give the user a chance to abort: `Apply anyway [y], Skip [s], Reject [r]?`

## Step 4: Update Tracking Files

After processing all staged files:

1. **`index.md`** — If at least one file was accepted, run once after the accepted batch has been written:
   ```bash
   obsidian-wiki index "$OBSIDIAN_VAULT_PATH" --link-format "$OBSIDIAN_LINK_FORMAT"
   ```
   If the `obsidian-wiki` executable is unavailable, manually reconcile `index.md` using the format in `llm-wiki/SKILL.md`.
   If the executable exists but the command fails, report the failure and stop before claiming bookkeeping is complete. Skip the refresh when all files were rejected or skipped.
2. **`hot.md`** — update the Recent Activity section: "Committed N staged pages; rejected M."
3. **`log.md`** — append:
   ```
   - [TIMESTAMP] STAGE_COMMIT accepted=N rejected=M skipped=K
   ```

## Step 5: Report

```
Stage commit complete.

✅  Accepted (N):
  concepts/attention-mechanism.md     → now live
  entities/andrej-karpathy.md         → now live
  concepts/transformer-architecture.md → updated (patch applied)

❌  Rejected (M):
  skills/fine-tuning-llms.md          → moved to _raw/rejected-skills-fine-tuning-llms.md

⏭️  Skipped (K):
  references/attention-is-all-you-need.md → still in _staging/

Staging queue: K files remaining
```

## Notes

- Staged files use the same page template as live pages — they are ready to land, just awaiting approval
- Patch files use a human-readable diff format: lines starting with `+` are additions, lines starting with `-` are deletions
- `index.md` and `log.md` are always updated immediately on ingest (they are low-risk tracking files) — only category pages go through staging
- The `_staging/` directory is not tracked by Obsidian's graph view — pages only appear in the wiki after promotion
