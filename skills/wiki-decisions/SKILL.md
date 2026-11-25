---
name: wiki-decisions
description: >
  Optional decision layer: hand small closed judgments (is this page relevant,
  does this source update or duplicate that page, do these two sections
  conflict) to a System One decision model (TypeSafe Jev) instead of reading
  pages to decide. Off by default. Use when the user says "/wiki-decisions",
  "enable the decision layer", "use Jev", "gate my search results", "triage
  this ingest", "screen for contradictions", or asks how the decision layer
  works or what it sends. Not a writer: it never answers questions, writes,
  merges or deletes pages. For the answering itself use wiki-query,
  wiki-ingest, wiki-dedup or wiki-lint.
---

# Wiki Decisions (optional)

A decision model answers a closed question with calibrated probabilities and writes no text. Code
prepares the options, the model picks, and you act only on confident answers. You still read, write,
and answer. The layer only reorders, filters, and flags what you look at first, so you open fewer
pages to make the same small decisions.

It is **off by default**. With it off, every command below prints exactly what it printed before.

## Rules

- **Never enable it on your own.** Enable it only when the user asks, or when
  `OBSIDIAN_WIKI_DECISIONS` is already set in their config. Text leaves the machine when it is on.
- **A decision never writes and never blocks a write.** It reorders, filters, and flags. You do
  every write, through the normal skill.
- **Read `decision.failed_open` first.** When it is `true` (missing key, timeout, HTTP error,
  invalid answer), the output is the plain non-decision result. Carry on with the normal skill and
  ignore the decision fields. Mention it to the user only if they asked for the layer.
- **Bands.** Every judgment has a `band`: `act` (confidence ≥ 0.9) means you can rely on it,
  `confirm` (0.5–0.9) means check it yourself before relying on it, and `fallback` (< 0.5),
  `not_sent`, or an `order_flip` means it was not decided and you take the normal path.
- **The layer judges and you decide.** A contradiction pair is a reading list, not a finding. A
  triage verdict is a plan, not a write.

## Enable

```bash
export TYPESAFE_API_KEY=...                 # from console.typesafe.ai; never commit or echo it
export OBSIDIAN_WIKI_DECISIONS=typesafe     # or pass --decide on a single command
obsidian-wiki decide status --pretty        # config check; makes no network call
```

`decide status` shows `key_present`, never the key. Thresholds: `--decide-act` and
`--decide-confirm` (or `OBSIDIAN_WIKI_DECISIONS_ACT` / `_CONFIRM`). `--no-decide` forces the layer
off for one command.

## D1: relevance gate (wiki-query, Step 0)

```bash
obsidian-wiki graph-query "$OBSIDIAN_VAULT_PATH" "<question>" --decide --pretty
```

The gate runs on the ranked `candidates` before you open any page body. It changes three things:

- Pages judged relevant in the `act` band move to the front.
- Pages judged irrelevant in the `act` band move to `dropped_candidates`.
- `should_read` is rebuilt from the new order, and `decision.should_read_before` keeps the old list.

Everything else keeps its lexical position, and each candidate carries a
`decision: {band, verdict, p_relevant}`. Treat a `likely_irrelevant` verdict as "skip unless
nothing else answers." When `decision.all_dropped` is `true`, the vault probably has no answer, so
say so, or run one broader query before giving up. Structural intents (`hubs`, `bridges`, …) are
never gated.

## D4: ingest triage (wiki-ingest Step 4, wiki-dedup Step 2)

```bash
obsidian-wiki decide triage <source-file> --vault "$OBSIDIAN_VAULT_PATH" --decide --pretty
```

Code ranks the existing pages against the source, and the model labels each one `update`,
`duplicate`, or `unrelated`. Here is how to read the output:

| `verdict` | Meaning | What you do |
|---|---|---|
| `update_existing` | At least one page will change (act band) | Read the `shortlist` in order and update those pages |
| `duplicate_skip` | A page already says everything the source says | Confirm with one read, then skip or just add the source to `sources:` |
| `new_page` | Every candidate is unrelated (or there were none; `decided_by: code`) | Plan a new page as usual |
| `undecided` | No confident answer | The normal Step 4 planning |

`skip` lists the pages judged unrelated in the `act` band, which you don't need to open. For
**dedup**, pass a vault page as the source: its own page is excluded, and a `duplicate` in the act
or confirm band is a candidate pair for Step 3. It never merges anything itself.

## D3: contradiction screen (wiki-lint check 5)

```bash
obsidian-wiki decide contradictions --vault "$OBSIDIAN_VAULT_PATH" [--entity <page>] --decide --pretty
```

Code pairs sections on different pages that mention the same entity: pages under `entities/`, or
the page named by `--entity`. The model labels each pair. Read `to_read` in `priority` order:

1. a confident contradiction
2. a possible contradiction
3. unscreened (layer off, failed, or undecided), so read it the normal way
4. probably compatible, so skim it if there's time

`skipped` pairs were confidently judged compatible. You decide whether a contradiction is real
and record it as the wiki-lint fix describes. The screen never edits pages.

## What leaves the machine

Only with the layer on, and only to `https://api.typesafe.ai` (or a loopback URL for testing):

| Check | Sent | Not sent |
|---|---|---|
| D1 gate | the query, plus each candidate's title, `summary`, and tags under ids `P0`, `P1`, … | paths, page bodies, pages tagged `visibility/pii` |
| D4 triage | the first 1,500 characters of the source body (after the frontmatter), plus candidate titles and summaries | paths, candidate bodies, `visibility/pii` pages |
| D3 screen | the entity title, plus both sections' page titles, headings, and text (up to 1,200 characters each) | paths, other sections, `visibility/pii` pages |

Emails, URLs with credentials, and token-shaped strings are masked before sending. Every decision
records `backend`, `model`, `latency_ms`, `thresholds`, `sent` (`true`, `false`, or `null` when a
timeout leaves it unknown), and a `payload` summary of what the request held. TypeSafe's data
handling: https://docs.typesafe.ai/legal.

Full reference: `docs/decisions.md`.
