---
name: wiki-narrate
description: >
  Turn a wiki topic into a cited Markdown briefing, plain-language explanation, or
  progressive lecture. Use this skill for topic-based briefing, explanation, and
  lecture requests that must stay within the evidence compiled in an Obsidian vault.
---

# Wiki Narrate — Cited Narrative Readouts

Use this skill only for a topic-based Markdown readout. Do not add tag or page-list
selection, prior-query input, voice aliases, HTML, PDF, slides, renderer handoffs, or
new compiled knowledge pages.

## Command Contract

`/wiki-narrate <topic> [--voice briefing|plain-language|lecturer] [--save]`

- Require a non-empty `<topic>`.
- The default voice is `briefing`.
- Voice names are canonical and case-sensitive. Unsupported values must return an
  error listing `briefing`, `plain-language`, and `lecturer` without searching or
  writing.
- `--save` is the only persistence switch.
- For a missing topic, malformed option, or unsupported voice, return a short usage
  or validation error and do not search, write, append a log event, or change `hot.md`.

## Retrieval

**Writing profile:** Before drafting or rewriting natural-language Markdown, read and apply the `Writing Profile Resolution` section in `llm-wiki/SKILL.md`. Framework schema, provenance, safety, and operation-specific requirements take precedence.
`WRITING.md` preferences apply only to newly drafted or rewritten natural-language Markdown; preserve source content and structured records.

1. Resolve configuration with the Config Resolution Protocol, including an inline
   `@name` vault override, then read the target vault's `AGENTS.md` when it exists.
   Load `OBSIDIAN_LINK_FORMAT` before drafting citations.
2. Read `hot.md` and `index.md` first. Select candidates by frontmatter and summary
   before reading bodies.
3. When configured, use QMD before `rg`; if QMD is absent, unconfigured, or fails,
   continue with the index and `rg` path. Treat QMD output as candidate guidance, not
   evidence: establish each claim from the allowed vault page itself.
4. Honor filtered-mode phrases such as "public only", "user-facing", "no internal
   content", "as a user would see it", and "exclude internal". Skip pages tagged
   `visibility/internal` or `visibility/pii` in that mode: never read, cite, or expose
   them.
5. Exclude `_readouts/`, `_raw/`, `_archives/`, `_meta/`, `index.md`, `log.md`,
   `hot.md`, and `_insights.md` from candidates.
6. Read matching sections before full pages, and read full pages only when a factual
   claim cannot otherwise be established. Preserve relevant lifecycle and freshness
   annotations; do not upgrade a page's trust.

## Claim Ledger and Citation Audit

Draft a ledger before prose. Each item contains a claim, supporting `[[vault page]]`
links, and one status: supported fact, inferred connection, or ambiguous conflict.
When `OBSIDIAN_LINK_FORMAT=markdown`, render the same supporting page as a standard
Markdown link; otherwise use the vault's `[[wikilink]]` form.

Ensure every factual sentence has adjacent supporting citations. Mark inferred connections `^[inferred]`; mark unresolved conflicts `^[ambiguous]`. Never use web knowledge, model memory, or invented examples to close a gap. Omit unsupported claims and name the gap in Coverage. An inference or ambiguity marker supplements, rather than replaces, adjacent citations.

## Drafting and Output

Read `references/voices.md` and use exactly the requested voice skeleton. The selected
voice may change prose and ordering, but cannot change the ledger's factual boundary.
Return Markdown only, structured as:

1. A title naming the topic and selected voice.
2. The selected voice's sections, in its documented order.
3. Adjacent citations for each factual sentence, rendered with
   `OBSIDIAN_LINK_FORMAT`.
4. A `## Coverage` footer listing cited pages, the count of inferred statements, and
   known evidence gaps.

If evidence is weak or contradictory, produce only the supported portion. Mark each
unresolved conflict `^[ambiguous]` with citations to all conflicting pages, and list
the remaining gaps in `## Coverage`.

## Persistence

Present the result by default. For `--save`, create `_readouts/` if necessary and write
`_readouts/<slug>.md` with `title`, `topic`, `voice`, `sources`, `created`, and
`updated` frontmatter. Use a deterministic, filesystem-safe `<slug>` derived from the
topic. Save the same completed Markdown readout that was returned in conversation.

A readout is derived output: exclude `_readouts/` from retrieval and must not update `index.md` or `.manifest.json`. Do not create `_readouts/` or a readout file without a successful `--save` result.

## Logging and Hot Cache

After a narration attempt that reaches retrieval, append one `WIKI_NARRATE` event to
`log.md`:

```
- [TIMESTAMP] WIKI_NARRATE topic="<topic>" voice=<voice> result_pages=N mode=normal|filtered saved=true|false outcome=success|no_match|write_failed
```

- Without `--save`, append the event with `saved=false` after returning the readout;
  do not create a readout or change `hot.md`.
- After a successful `--save` write, append the event with `saved=true`, then refresh
  `hot.md` with the topic, voice, cited pages, inference count, evidence gaps, and
  saved readout path. `hot.md` changes only after a successful save.
- If the readout write fails after drafting, return the completed readout in
  conversation, report that saving failed, append a `WIKI_NARRATE` event with
  `saved=false outcome=write_failed` when `log.md` remains writable, and do not update
  `hot.md`.
- If appending `log.md` fails, preserve the readout result and report the logging
  failure separately. Never represent a failed log or save as successful.

## Safe Failure Behavior

- **No matching pages:** explain that the vault lacks material for the topic. Create
  no readout file even if `--save` was requested, do not change `hot.md`, and record a
  `WIKI_NARRATE` event with `outcome=no_match` when `log.md` is writable.
- **Weak evidence or source conflict:** do not resolve it with outside knowledge.
  Return only supported claims, label ambiguity where applicable, and make the gap
  explicit in `## Coverage`; saving remains available for that successful partial
  readout.
- **QMD unavailable or unconfigured:** state the fallback briefly in the working
  update and continue safely through `index.md` and `rg`; do not fail the narration
  merely because QMD is unavailable.
- **Write failure:** never leave a partial readout presented as saved, never update
  `hot.md`, and never update `index.md` or `.manifest.json`.
