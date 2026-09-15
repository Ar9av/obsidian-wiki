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

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md`. This gives `OBSIDIAN_VAULT_PATH` and `WIKI_STAGED_WRITES`.
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

The CLI owns the inventory — don't glob `_staging/` yourself:

```bash
obsidian-wiki staging list --json
```

Each entry carries:

| Field | Meaning |
|---|---|
| `staged_path` | vault-relative path of the staged file |
| `live_path` | where it will land (a `.patch.md` targets the page it is named after) |
| `kind` | `new`, `update`, or `patch` |
| `staged_revision` | content hash of the staged file, as you are seeing it now |
| `live_revision` | content hash of the live page, or `null` if there is none yet |
| `staged_mtime` | when it was staged |

**Keep `staged_revision` and `live_revision` for every file you show the user.** They are what makes Step 3 refuse to overwrite an agent's concurrent write instead of silently clobbering it.

Report the inventory:

```
Staged files: 4 new pages, 2 updates

New pages:
  _staging/concepts/attention-mechanism.md        (staged 2026-09-08)
  _staging/entities/andrej-karpathy.md            (staged 2026-09-08)

Updates:
  _staging/concepts/transformer-architecture.md   (target: concepts/transformer-architecture.md)

Patches:
  _staging/skills/prompt-engineering.patch.md     (target: skills/prompt-engineering.md)
```

If the list is empty, report: "Nothing staged. All writes have been committed or no staged writes have been produced yet."

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

⚠️  Conflict check: live_revision no longer matches what was staged against. Review carefully.

Accept [a], Reject [r], Skip [s], Preview full diff [p]?
```

If `--all` flag is set, skip prompting and accept every file.
If `--reject-all` flag is set, skip prompting and reject every file.
If `--list` flag is set, stop after printing the inventory (Step 1).

## Step 3: Apply Decisions

The moves are mechanical and the CLI does them atomically. Pass the revisions from Step 1 so a decision made on stale information fails loudly.

### Accepting a new page

```bash
obsidian-wiki staging promote <staged_path> \
  --expect-staged <staged_revision> --expect-new
```

`--expect-new` refuses if a live page has appeared since you listed — someone else got there first.

### Accepting an update

```bash
obsidian-wiki staging promote <staged_path> \
  --expect-staged <staged_revision> --expect-live <live_revision>
```

### Rejecting a file

```bash
obsidian-wiki staging discard <staged_path>
```

It lands in `_raw/rejected-<category>-<page>.md` for manual editing. An earlier rejection of the same page is never overwritten — the second becomes `-2`.

### Accepting a patch

`promote` refuses `.patch.md` files, because merging a human-readable diff into a page whose surrounding text may have moved is judgment, not a rename. Do it yourself:

1. Read the target page and the patch.
2. Apply the `+` additions and `-` deletions **as a merge** — never overwrite the page wholesale.
3. Bump the target's `updated` frontmatter.
4. `obsidian-wiki staging discard <patch staged_path>` to clear the patch from the queue.

### When the CLI reports a conflict

Exit code **9** with `conflict: ...` on stderr means the staged or live file changed after you listed it. Nothing was moved. Do not retry with fresh revisions blindly — re-run `staging list`, show the user what changed, and ask again. The whole point of the check is that the content they approved is no longer the content that would land.

`index.md` is updated by the ingest that staged the page, so promotion does not touch it. `log.md` gets one `STAGE_COMMIT` line per invocation, written by the CLI.

## Step 4: Update Tracking Files

The CLI appends the `STAGE_COMMIT` line to `log.md` itself. After processing all staged files, update **`hot.md`** — Recent Activity: "Committed N staged pages; rejected M."

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
- Patch files use a human-readable diff format: lines starting with `+` are additions, lines starting with `-` are deletions. `staging promote` refuses them — merge them yourself (Step 3)
- `index.md` and `log.md` are always updated immediately on ingest (they are low-risk tracking files) — only category pages go through staging
- The moves live in `obsidian_wiki/staging.py`; this skill supplies the judgment, not the file handling
- The `_staging/` directory is not tracked by Obsidian's graph view — pages only appear in the wiki after promotion
