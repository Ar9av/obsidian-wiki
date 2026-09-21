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
obsidian-wiki memory sync --verb INGEST \
  --field source="papers/attention.pdf" \
  --field pages_created=3 \
  --field pages_updated=12
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
obsidian-wiki memory sync --verb INGEST --field source="…" \
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
| `memory log VERB --field k=v` | You only need the log line (read-only skills) |
| `memory index` | You moved, renamed, or deleted pages outside a normal write |
| `memory hot --takeaways "…"` | You want to update the narrative without an ingest |
| `memory status` | Checking whether the surface is current before or after work |
| `memory recap` | You need the injectable profile + threads + activity block |

`--check` reports drift and exits 2 without writing. `--json` is available on
all of them.

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

## Read-only skills

If your skill only reads the vault, the *only* write you may perform is the log
line:

```bash
obsidian-wiki memory log QUERY --field query="how do transformers work" --field result_pages=4
```

Do not touch `index.md`, `hot.md`, `_insights.md`, or `.manifest.json`.

## Manifest

`.manifest.json` is separate and has its own lock. Record sources with
`obsidian-wiki cache-update` rather than hand-editing it, for the same reason.
