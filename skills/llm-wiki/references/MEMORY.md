# Memory Surface — the canonical tracking-update procedure

`index.md`, `log.md`, `hot.md`, `_meta/profile.md`, and `_meta/todos.md` are the
vault's memory. **Do not write them by hand.** They are maintained by
`obsidian-wiki memory`, which takes an advisory lock (`.memory.lock`) and
replaces each file atomically.

This exists because the old approach did not survive contact with parallel
agents. Every write skill restated the procedure in its own words and rewrote
the files wholesale with no lock, so two skills running at once silently dropped
one of the two updates, and nothing enforced the documented ~500-word cap on
`hot.md`.

## The one call you usually want

After any write operation, close it out with a single command:

```bash
obsidian-wiki memory sync INGEST source="papers/attention.pdf" pages_created=3 pages_updated=12
```

That appends the log line, reconciles `index.md` against the pages actually on
disk, and regenerates `hot.md` — all under one lock, so another writer cannot
interleave between the three and leave a snapshot describing a vault state that
never existed.

Use `--vault <path>` (or `--vault @name`) when you are not in a directory whose
`.env` resolves to the target vault.

## Verbs

One uppercase verb per operation, matching the skill that ran: `INGEST`,
`CAPTURE`, `WIKI_UPDATE`, `WIKI_NARRATE`, `DEDUP`, `LINT`, `QUERY`,
`DAILY-UPDATE`, `STAGE_COMMIT`, `INIT`, `ARCHIVE`, `REBUILD`. Fields are
free-form `key=value` pairs; values containing spaces are quoted for you.

## What you still write yourself

`## Key Takeaways` in `hot.md` is the one slot that is yours. Everything else in
that file is generated, and hand edits to it are overwritten on the next
rebuild. Pass your prose in:

```bash
obsidian-wiki memory sync INGEST source="…" \
  --takeaways "Fowler's decomposition argument now anchors the microservices cluster."
```

`--takeaways -` reads it from stdin, which is easier for multi-line prose. When
you omit the flag the existing takeaways carry across unchanged, so a mechanical
rebuild never erases what a previous session concluded.

Write the *conceptual* change, not a file list. "Ingested Fowler's microservices
article — 3 new concept pages on service decomposition, API gateway, bounded
contexts" is useful. "Created 3 files" is not.

## Individual commands

| Command | Use it when |
|---|---|
| `memory log VERB k=v` | You only need the log line (read-only skills) |
| `memory index` | You moved, renamed, or deleted pages outside a normal write |
| `memory hot --takeaways "…"` | You want to update the narrative without an ingest |
| `memory status` | Checking whether the surface is current before or after work |
| `memory now` | You need the `created:` / `updated:` stamp for a page you are writing (`--date` for a bare date) |
| `memory recap` | You need the injectable profile + threads + activity block |

`--check` reports drift and exits 2 without writing. `--json` is available on
all of them.

`memory now` honors `timezone:` in the root `index.md` frontmatter (an IANA name
such as `America/Detroit`) and prints UTC in the `Z` spelling without it. The
same clock stamps the log, `hot.md`, and the tables. Write what it prints;
never `date -u`.

## Owner profile and todos

Durable facts about the person you are working with, and threads carried between
sessions:

```bash
obsidian-wiki memory profile set stack "Python, FastAPI, Postgres" --confidence 0.85
obsidian-wiki memory todo add "Persist the retrieval index" --origin projects/obsidian-wiki.md
obsidian-wiki memory todo done t1
```

Rules that matter:

- **Only record what the user actually told you**, directly or by clear
  demonstration. Never infer a durable fact about a person from a document you
  ingested — that is the document's content, and it belongs on a page.
- **Confidence is your own calibration**, not a measurement. Something stated
  outright is ~0.9; something inferred from one session's behaviour is ~0.5.
- **Staleness is reported, never enforced.** An open thread untouched for 30
  days is flagged. Do not close it on the user's behalf.
- Re-adding an open thread with the same text touches it rather than
  duplicating it, so calling `todo add` again is safe.

## What the index preserves

`memory index` reconciles rather than overwrites. One section per category is
regenerated from disk; the preamble and any section whose heading is not a
category are preserved verbatim. A hand-written "Reading queue" section
survives. A stale entry for a deleted page does not.

With `index_folder_hubs: true` in the root `index.md` frontmatter, a folder that
has its own `index.md` is listed once, as a link to that index, instead of page
by page. Read that sub-index when you need the pages inside it.

## Read-only skills

If your skill only reads the vault, the *only* write you may perform is the log
line:

```bash
obsidian-wiki memory log QUERY query="how do transformers work" result_pages=4
```

Do not touch `index.md`, `hot.md`, `_insights.md`, or `.manifest.json`.

## Manifest

`.manifest.json` is separate and has its own lock. Record sources with
`obsidian-wiki cache-update` rather than hand-editing it, for the same reason.

## Durable takeaways: fail-closed update contract

**Breaking safety changes:** generated activity/threads/contradictions may be trimmed; durable Key Takeaways never is. If it cannot fit the chosen cap (500 words by default), hot/sync raises takeaways_overflow BEFORE writing log/index/hot. Move detail to a knowledge page and supply a reviewed summary, or explicitly choose a larger --max-words. The framework never silently raises the cap or archives prose.

Ordinary mechanical sync omits --takeaways and carries the current section forward under the existing official lock. No revision is needed. Explicit replacement of existing non-placeholder prose requires --expect-takeaways-sha256 (Python: expected_takeaways_sha256). First read the full current section and reconcile all still-valid conclusions; obtain hot.takeaways_sha256 from memory status --json for that reviewed snapshot. If it changes, review again rather than blindly retrying.

~~~bash
obsidian-wiki memory status --json --vault "$OBSIDIAN_VAULT_PATH"
# Save hot.takeaways_sha256 as TAKEAWAYS_REVISION after reviewing its section.
obsidian-wiki memory sync INGEST source="papers/attention.pdf" --takeaways "<reviewed replacement>" --expect-takeaways-sha256 "$TAKEAWAYS_REVISION" --operation-id "<stable-operation-id>" --vault "$OBSIDIAN_VAULT_PATH"
~~~

The revision is the SHA-256 of the UTF-8 canonical section body (surrounding whitespace stripped by the existing section parser), not the whole cache. Generated activity alone causes no narrative conflict. Missing revisions raise takeaways_revision_required with migration instructions; stale revisions raise takeaways_conflict under the lock. Initial empty/placeholder seeding remains compatible. Clearing/repeating existing prose still requires a revision.

Python writes use rebuild_hot(..., expected_takeaways_sha256=revision) or sync_memory(vault, verb, fields, takeaways=..., expected_takeaways_sha256=revision, operation_id=...). build_hot is render-only; lock=False callers must hold memory_lock themselves.

Optional --operation-id is sync-only. An identical request/ID returns already_applied: true without writes, even if its previous response was lost. Different content/options under the same ID raises memory_operation_conflict. Without an ID, every successful sync appends a new operation as before. Deduplication depends on retaining operation log history. No new manifest/idempotency database is added.

## Interrupted memory sync and recovery

All outputs are rendered/validated under the official lock BEFORE mutation. A durable vault-local .memory-transaction.json stores before/after bytes. Caught interruptions roll back uncommitted updates. After process death, the next official lock-owning writer recovers uncommitted bytes or completes committed cleanup before proceeding; the existing advisory lock's crash/staleness timeout still applies. Do not delete the journal or bypass a live lock.

Recovery checks ALL targets first: unknown external edits raise memory_recovery_conflict while preserving the edits and journal. memory status --json reports transaction_pending without silently repairing. This is recoverable atomicity for cooperating lock users, NOT instantaneous multi-file snapshot isolation for unlocked readers/Obsidian: hard termination can leave a transient mixed on-disk view until recovery. Treat a pending journal as incomplete. Per-file replacement remains atomic. Filesystem corruption, lock-bypassing writers, and durability beyond filesystem fsync/rename guarantees are outside this contract. The private journal contains memory text and must not be publicly exported.

Unmigrated curated vaults retain legacy log-only acceptance with a warning when no narrative replacement is requested; do not claim full synchronization for that mode. Explicit replacement on an unmigrated surface rejects before writing anything. No automatic migration or production repair is implied.

New memory files and journals use private 0600 permissions; existing memory output mode bits are retained. hot --check and sync --check do not recover a pending transaction: they reject with memory_recovery_required without changing target files.

The status JSON hot.takeaways body and hot.takeaways_sha256 are derived from the same file read: review that paired snapshot rather than reading a body and a later hash independently. A revision is content-based (not a monotonic history counter). Do not act on status while transaction_pending is true.
