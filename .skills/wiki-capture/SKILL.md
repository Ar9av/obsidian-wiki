---
name: wiki-capture
description: >
  Save the current conversation as a permanent, structured wiki note. Use this skill when the user
  says "save this", "/wiki-capture", "capture this", "file this conversation", "preserve this",
  "add this to my wiki", or wants to turn what was just discussed into lasting knowledge. The skill
  classifies the content, rewrites it as declarative knowledge (not a chat transcript), and places
  it in the correct vault category. Also supports a fast QUICK MODE (`/wiki-capture --quick`, "quick
  capture", "capture this finding", "save this bug fix", "save this gotcha", "drop this to raw", "quick
  save to wiki") that drops findings to the `_raw/` staging area in under 60 seconds with no manifest
  or index writes — used by the session-end Stop hook to auto-preserve findings.
---

# Wiki Capture — Conversation to Wiki Note

You are preserving knowledge from the current conversation as a permanent wiki note. The goal is to extract the *substance* — the knowledge itself — not a summary of what was said.

This skill has two modes:

- **Full mode (default)** — classify the content and write a finished, cross-linked wiki page directly into the right category. This is the rest of this document (Steps 1–7).
- **Quick mode (`--quick`)** — zero-friction staging: drop findings to `_raw/` in under 60 seconds with no manifest/index/log/QMD writes. Used for mid-session capture and by the session-end Stop hook. See below, then stop — do **not** run the full-mode steps.

## Quick Mode (`--quick`)

Trigger when invoked as `/wiki-capture --quick`, by "quick capture" / "capture this finding" / "save this bug fix" / "save this gotcha" / "drop this to raw" / "quick save to wiki", or automatically by the session-end Stop hook.

**Speed contract:** Inline only. No subagents. No QMD. No manifest/`index.md`/`log.md`/`hot.md` writes. Target: <60 seconds. Promotion to full wiki pages happens later via `/wiki-ingest`.

1. **Resolve config** (Config Resolution Protocol in `llm-wiki/SKILL.md`): get `OBSIDIAN_VAULT_PATH` and `OBSIDIAN_RAW_DIR` (default: `$OBSIDIAN_VAULT_PATH/_raw`). Ensure `$OBSIDIAN_RAW_DIR` exists; create it if not.

2. **Gate — KEEP or SKIP?** Before extracting, judge whether this session has capture value. This keeps the skill safe to call automatically without spamming `_raw/`.
   - **SKIP** (exit with "Nothing worth capturing in this session.") if ALL are true: the conversation is purely conversational (planning/Q&A/explanation) with no implementation; no errors, debugging, or problem-solving visible; nothing surprising or undocumented; every finding is already obvious from the docs.
   - **KEEP** (proceed) if ANY are true: a fix or workaround was found through investigation; non-obvious library/API/framework behavior was confirmed (edge case, undocumented constraint, time-costing gotcha); a debugging session reached a concrete conclusion; a reusable pattern emerged.
   - When invoked **via the Stop hook, err toward SKIP** — only KEEP on clear evidence. When invoked **manually, err toward KEEP** — the user called it for a reason.

3. **Scan for reusable findings** — non-obvious bugs and root causes, framework/library gotchas, surprising API behavior, investigated workarounds, environment/toolchain quirks, patterns from debugging. Skip PM updates, config already in CLAUDE.md, inconclusive back-and-forth, anything obvious from the docs, and pleasantries. If nothing material emerged, say so and stop.

4. **Cluster by topic** — one `_raw/` file per topic cluster, not per finding. Name each as a kebab-case slug (e.g. `swift-actor-reentrancy`, `nextjs-hydration-mismatch`).

5. **Infer project context** from repo names, file paths, framework mentions, error messages. Use the most specific name you can reliably infer; else `null`.

6. **Write raw files** — for each cluster, write `$OBSIDIAN_RAW_DIR/<ISO-date>-<slug>.md`. Read `references/RAW-FORMAT.md` for the full frontmatter spec, finding-block body structure, and provenance/confidence calibration. Per-cluster fields that vary: `title`, `tags` (2–4 from taxonomy), `summary` (≤200 chars), `project` (inferred or `null`), `base_confidence` (0.6 discussed → 0.75 fix applied → 0.9 test confirmed), `provenance.extracted`/`provenance.inferred` (sum to 1.0), `lifecycle_changed` (today), `sources` (`"<project> session (<YYYY-MM-DD>)"`).

7. **Confirm** — list staged files and tell the user to run `/wiki-ingest` to promote them:
   ```
   Staged to _raw/:
     _raw/2026-05-27-swift-actor-reentrancy.md   — "Actor reentrancy causes deadlock in async forEach"
   Run /wiki-ingest to promote these to full wiki pages.
   ```
   Quick mode deliberately does **not** write the manifest, `index.md`, `log.md`, `hot.md`, or refresh QMD — promotion via `/wiki-ingest` handles all of that. **Stop here; do not run the full-mode steps below.**

---

## Full Mode

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH` and `OBSIDIAN_LINK_FORMAT` (default: `wikilink`).
2. Read `$OBSIDIAN_VAULT_PATH/index.md` to understand existing wiki content (avoid duplicates)
3. Read `$OBSIDIAN_VAULT_PATH/hot.md` if it exists — it gives context on recent activity

When writing internal links in Step 5, apply the link format from `llm-wiki/SKILL.md` (Link Format section) using the `OBSIDIAN_LINK_FORMAT` value.

## Step 1: Identify What's Worth Preserving

Scan the conversation. Ask: what knowledge emerged here that would be valuable in 3 months with no memory of this chat?

Worth preserving:
- Decisions made and *why* they were made
- Analysis, frameworks, mental models developed
- Technical findings, patterns, or procedures
- Synthesized understanding of a topic
- Clear explanations of a concept that took effort to arrive at
- Key facts from an external source discussed in the conversation

Skip:
- Logistics, scheduling, pleasantries
- Exploratory back-and-forth where no conclusion was reached
- Content that's already in the wiki

If nothing material emerged, tell the user and stop.

## Step 2: Classify the Content Type

Assign one of five types — this determines the target folder and tone:

| Type | Description | Target folder |
|---|---|---|
| `synthesis` | Multi-step analysis or an answer to a specific question that required reasoning | `synthesis/` |
| `concept` | A definition, framework, or mental model (what a thing *is*) | `concepts/` |
| `source` | Summary of an external document, article, or resource discussed | `references/` |
| `decision` | A strategic, architectural, or design choice and its rationale | `synthesis/` |
| `session` | A complete discussion summary when the conversation spans multiple topics | `journal/` |

If the content clearly belongs to a specific project (detected from context or user mention), place it under `projects/<project-name>/<category>/` instead.

## Step 3: Rewrite as Declarative Knowledge

Do **not** write a summary of the conversation. Write the knowledge itself, in declarative present tense:

- Not: "The user asked about X and Claude explained that..."
- Yes: "X works by..."
- Not: "We decided to use Y because..."
- Yes: "Y is preferred over Z because [reason]. [^[inferred] if the rationale was implied, not stated explicitly]"

Apply provenance markers per `llm-wiki`:
- *Extracted* — explicitly stated in the conversation (no marker)
- *Inferred* — generalized or synthesized from the conversation → `^[inferred]`
- *Ambiguous* — disputed, uncertain, or contradictory → `^[ambiguous]`

## Step 4: Generate a Slug and Title

Derive a clear, descriptive title from the content. Slugify it:
- Lowercase, words separated by hyphens
- Max 50 characters
- Avoid dates in the slug (the frontmatter has `created`)

## Step 5: Write the Wiki Note

Create the file at the target path with required frontmatter:

```yaml
---
title: >-
  <Title>
category: <synthesis|concepts|references|journal|skills>
tags: [<2-5 domain tags from taxonomy>]
sources:
  - conversation:<ISO-date>
created: <ISO-8601 timestamp>
updated: <ISO-8601 timestamp>
summary: >-
  <1-2 sentences, ≤200 chars, answering "what knowledge does this page hold?">
provenance:
  extracted: 0.X
  inferred: 0.X
  ambiguous: 0.X
base_confidence: 0.42
lifecycle: draft
lifecycle_changed: <ISO date today>
---
```

Body structure by type:

**synthesis / decision:**
```markdown
# Title

## Context
<What prompted this — the problem or question being addressed>

## Finding / Decision
<The core knowledge or conclusion>

## Reasoning
<Why this is the case or why this choice was made>

## Implications
<What follows from this — what to watch for, next steps, trade-offs>

## Related
<[[wikilinks]] to connected pages>
```

**concept:**
```markdown
# Title

<Definition in one clear sentence.>

## What It Is
<Explanation of the concept>

## How It Works
<Mechanism or structure>

## When to Use
<Applicability, conditions, trade-offs>

## Related
<[[wikilinks]]>
```

**source:**
```markdown
# Title

> Source: <title or URL>

## What It Covers
<What the source is about>

## Key Points
<Bulleted claims with provenance markers>

## Open Questions
<What it raises but doesn't answer — omit if none>

## Related
<[[wikilinks]]>
```

**session:**
```markdown
# Title

*Session captured: <date>*

## Topics Covered
<Brief list>

## Key Takeaways
<The 3-5 most important things that emerged>

## Decisions Made
<Any explicit decisions, with rationale>

## Open Questions
<What remains unresolved>

## Related
<[[wikilinks]]>
```

Every note must link to at least 2 existing wiki pages. Search `index.md` before writing. If fewer than 2 related pages exist, create minimal stubs for the most important concepts referenced.

## Step 6: Update Tracking Files

**`index.md`** — Add the new page under its category section.

**`log.md`** — Append:
```
- [TIMESTAMP] CAPTURE type=<type> page="<path>" title="<title>"
```

**`hot.md`** — Update **Recent Activity** with what was just captured. Update **Key Takeaways** if the note introduced something worth flagging. Update `updated` timestamp.

## Step 7: Confirm to User

Report the saved path and title:
```
Saved to: projects/<name>/synthesis/<slug>.md
Title: <Title>
Type: synthesis
```

## Quality Checklist

- [ ] Content rewritten as declarative knowledge (not a chat transcript)
- [ ] Type classified correctly; target path is in the right folder
- [ ] Frontmatter complete with title, category, tags, sources, summary, provenance
- [ ] At least 2 wikilinks to existing pages
- [ ] `index.md`, `log.md`, and `hot.md` updated
- [ ] Confirmed save path to user

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