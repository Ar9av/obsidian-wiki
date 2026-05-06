---
name: wiki-lint
description: >
  Audit and maintain the health of the Obsidian wiki. Use this skill when the user wants to check their
  wiki for issues, find orphaned pages, detect contradictions, identify stale content, fix broken wikilinks,
  or perform general maintenance on their knowledge base. Also triggers on "clean up the wiki",
  "what needs fixing", "audit my notes", or "wiki health check".
---

# Wiki Lint — Health Audit

You are performing a health check on an Obsidian wiki. Your goal is to find and fix structural issues that degrade the wiki's value over time.

**Before scanning anything:** follow the Retrieval Primitives table in `llm-wiki/SKILL.md`. Prefer frontmatter-scoped greps and section-anchored reads over full-page reads. On a large vault, blindly reading every page to lint it is exactly what this framework is built to avoid.

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH`
2. Read `index.md` for the full page inventory
3. Read `log.md` for recent activity context

## Lint Checks

Run these checks in order. Report findings as you go.

### 1. Orphaned Pages

Find pages with zero incoming wikilinks. These are knowledge islands that nothing connects to.

**How to check:**
- Glob all `.md` files in the vault
- For each page, Grep the rest of the vault for `[[page-name]]` references
- Pages with zero incoming links (except `index.md` and `log.md`) are orphans

**How to fix:**
- Identify which existing pages should link to the orphan
- Add wikilinks in appropriate sections

### 2. Broken Wikilinks

Find `[[wikilinks]]` that point to pages that don't exist.

**How to check:**
- Grep for `\[\[.*?\]\]` across all pages
- Extract the link targets
- Check if a corresponding `.md` file exists

**How to fix:**
- If the target was renamed, update the link
- If the target should exist, create it
- If the link is wrong, remove or correct it

### 3. Missing Frontmatter

Every page should have: title, category, tags, sources, created, updated.

**How to check:**
- Grep frontmatter blocks (scope to `^---` at file heads) instead of reading every page in full
- Flag pages missing required fields

**How to fix:**
- Add missing fields with reasonable defaults

### 3a. Missing Summary (soft warning)

Every page *should* have a `summary:` frontmatter field — 1–2 sentences, ≤200 chars. This is what cheap retrieval (e.g. `wiki-query`'s index-only mode) reads to avoid opening page bodies.

**How to check:**
- Grep frontmatter for `^summary:` across the vault
- Flag pages without it, **but as a soft warning, not an error** — older pages predating this field are fine; the check exists to nudge ingest skills into filling it on new writes.
- Also flag pages whose summary exceeds 200 chars.

**How to fix:**
- Re-ingest the page, or manually write a short summary (1–2 sentences of the page's content).

### 4. Stale Content

Pages whose `updated` timestamp is old relative to their sources.

**How to check:**
- Compare page `updated` timestamps to source file modification times
- Flag pages where sources have been modified after the page was last updated

### 5. Contradictions

Claims that conflict across pages.

**How to check:**
- This requires reading related pages and comparing claims
- Focus on pages that share tags or are heavily cross-referenced
- Look for phrases like "however", "in contrast", "despite" that may signal existing acknowledged contradictions vs. unacknowledged ones

**How to fix:**
- Add an "Open Questions" section noting the contradiction
- Reference both sources and their claims

### 6. Index Consistency

Verify `index.md` matches the actual page inventory.

**How to check:**
- Compare pages listed in `index.md` to actual files on disk
- Check that summaries in `index.md` still match page content

### 7. Provenance Drift

Check whether pages are being honest about how much of their content is inferred vs extracted. See the Provenance Markers section in `llm-wiki` for the convention.

**How to check:**
- For each page with a `provenance:` block or any `^[inferred]`/`^[ambiguous]` markers, count sentences/bullets and how many end with each marker
- Compute rough fractions (`extracted`, `inferred`, `ambiguous`)
- Apply these thresholds:
  - **AMBIGUOUS > 15%**: flag as "speculation-heavy" — even 1-in-7 claims being genuinely uncertain is a signal the page needs tighter sourcing or should be moved to `synthesis/`
  - **INFERRED > 40% with no `sources:` in frontmatter**: flag as "unsourced synthesis" — the page is making connections but has nothing to cite
  - **Hub pages** (top 10 by incoming wikilink count) with INFERRED > 20%: flag as "high-traffic page with questionable provenance" — errors on hub pages propagate to every page that links to them
  - **Drift**: if the page has a `provenance:` frontmatter block, flag it when any field is more than 0.20 off from the recomputed value
- **Skip** pages with no `provenance:` frontmatter and no markers — treated as fully extracted by convention

**How to fix:**
- For ambiguous-heavy: re-ingest from sources, resolve the uncertain claims, or split speculative content into a `synthesis/` page
- For unsourced synthesis: add `sources:` to frontmatter or clearly label the page as synthesis
- For hub pages with INFERRED > 20%: prioritize for re-ingestion — errors here have the widest blast radius
- For drift: update the `provenance:` frontmatter to match the recomputed values

### 8. Fragmented Tag Clusters

Checks whether pages that share a tag are actually linked to each other. Tags imply a topic cluster; if those pages don't reference each other, the cluster is fragmented — knowledge islands that should be woven together.

**How to check:**
- For each tag that appears on ≥ 5 pages:
  - `n` = count of pages with this tag
  - `actual_links` = count of wikilinks between any two pages in this tag group (check both directions)
  - `cohesion = actual_links / (n × (n−1) / 2)`
- Flag any tag group where cohesion < 0.15 and n ≥ 5

**How to fix:**
- Run the `cross-linker` skill targeted at the fragmented tag — it will surface and insert the missing links
- If a tag group is large (n > 15) and still fragmented, consider splitting it into more specific sub-tags

### 9. Visibility Tag Consistency

Checks that `visibility/` tags are applied correctly and aren't silently missing where they matter.

**How to check:**

- **Untagged PII patterns:** Grep page bodies for patterns that commonly indicate sensitive data — lines containing `password`, `api_key`, `secret`, `token`, `ssn`, `email:`, `phone:` followed by an actual value (not a field description). If a page matches and lacks `visibility/pii` or `visibility/internal`, flag it as a likely mis-classification.
- **`visibility/pii` without `sources:`:** A page tagged `visibility/pii` should always have a `sources:` frontmatter field — if there's no provenance, there's no way to verify the classification. Flag any `visibility/pii` page missing `sources:`.
- **Visibility tags in taxonomy:** `visibility/` tags are system tags and must **not** appear in `_meta/taxonomy.md`. If found there, flag as misconfigured — they'd be counted toward the 5-tag limit on pages that include them.

**How to fix:**
- For untagged PII patterns: add `visibility/pii` (or `visibility/internal` if it's team-context rather than personal data) to the page's frontmatter tags
- For missing `sources:`: add provenance or escalate to the user — don't auto-fill
- For taxonomy contamination: remove the `visibility/` entries from `_meta/taxonomy.md`

### 10. Misc Promotion Candidates

Find pages in `misc/` that have accumulated enough project affinity to be promoted.

**How to check:**
- Glob `$OBSIDIAN_VAULT_PATH/misc/*.md`
- For each page, read the `affinity` frontmatter field
- Flag pages where any single project's score ≥ 3

**How to fix:**
- Run the `cross-linker` skill first if affinity scores look stale (e.g., `affinity: {}` on a page with many wikilinks)
- To promote: move the page to `projects/<project-name>/references/` (or another appropriate category), update its `category` frontmatter, remove `promotion_status`, and grep the vault for backlinks to update them

### 12. Confidence and Lifecycle Schema

Enforces the confidence + lifecycle frontmatter schema (see `llm-wiki/SKILL.md`, Confidence and Lifecycle section).

Two modes:
- **`--check`** (default, read-only) — reports errors and warnings
- **`--fix`** — may rewrite `base_confidence` only when drift is detected (Rule 12e); never rewrites `lifecycle`

#### Rule 12a — `lifecycle` enum validation

**How to check:** Grep frontmatter for `^lifecycle:` across all pages. Flag any value not in `{draft, reviewed, verified, disputed, archived}`.

**How to fix:** n/a (only a human should set lifecycle state)

#### Rule 12b — `base_confidence` range

**How to check:** Grep frontmatter for `^base_confidence:` across all pages. Flag any value outside `[0.0, 1.0]` or any page missing the field entirely.

**How to fix:** n/a (wrong value means the skill computed it wrong — surface for manual correction)

#### Rule 12c — Stale page report (computed overlay)

Staleness is never stored — it is computed at read time: `is_stale = (today − updated) > 90 days`.

**How to check:** For each page, read `updated:` from frontmatter and compute `is_stale`. If stale, also check `lifecycle:`. Report:
- Stale pages with `lifecycle: verified` with a louder annotation (these are the most dangerous — high-trust pages that may be wrong)
- All other stale pages as a standard warning

**How to fix:** `--fix` does **not** rewrite `lifecycle`. Staleness clears automatically when a re-ingest bumps `updated`.

#### Rule 12d — Supersession integrity

**How to check:** For each page with `superseded_by: "[[target]]"`:
- Verify the target page exists
- Verify the target page is not itself `archived` (no circular or chained supersession)
- Verify there are no cycles (A supersedes B which supersedes A)
- Warn if `lifecycle != archived` while `superseded_by` is set (inconsistent state)

**How to fix:** n/a — flag for human resolution

#### Rule 12e — Confidence drift

**How to check:** For pages that have both `base_confidence:` and `sources:` in frontmatter, recompute `base_confidence` using the formula in `llm-wiki/SKILL.md`. If the stored value differs from the recomputed value by more than 0.05, flag it as drift.

**How to fix (`--fix` only):** Rewrite the `base_confidence` field to the recomputed value. This is the **only rule** that mutates frontmatter automatically.

#### Migration timeline

| Phase | When | Behavior on missing fields |
|---|---|---|
| Phase 1: Soft launch | Initial PR | Warning only — missing `base_confidence` or `lifecycle` on any page |
| Phase 2: New pages enforced | +2 weeks | Error for newly created pages missing the fields; existing pages still warn even if `updated` is bumped during routine maintenance |
| Phase 3: Full enforcement | +6 weeks, gated on a backfill script shipping in a separate PR | Error for all pages |

#### Output additions

Add to the Wiki Health Report:

```markdown
### Confidence/Lifecycle Issues (N found)
- `concepts/foo.md` — missing `lifecycle` field (warning: Phase 1)
- `entities/bar.md` — `lifecycle: stalestate` is not a valid enum value
- `concepts/scaling.md` — `base_confidence: 1.4` is out of range [0.0, 1.0]
- `synthesis/old-analysis.md` — STALE (last updated 2025-10-01, 182 days ago) lifecycle=verified ⚠️ HIGH PRIORITY
- `concepts/outdated.md` — STALE (last updated 2025-11-15, 137 days ago) lifecycle=draft
- `entities/tool-v1.md` — `superseded_by: [[entities/tool-v2]]` but lifecycle=draft (expected archived)
- `concepts/drift-example.md` — base_confidence drift: stored=0.80, recomputed=0.59 (delta=0.21)
```

Append to the `LINT` log entry:
```
- [TIMESTAMP] LINT ... lifecycle_issues=N
```

### 11. Synthesis Gaps

Identify high-value synthesis opportunities the wiki is missing — concept pairs that co-occur across many pages but have no `synthesis/` page connecting them.

**How to check:**
- List all pages in `synthesis/` — collect the concept pairs each one already covers (from its `[[wikilinks]]` or title)
- Pick 10-15 frequently linked concepts from `concepts/` and `entities/`
- For each pair, run a quick grep to count pages that link to both:
  ```bash
  grep -rl "\[\[ConceptA\]\]" "$OBSIDIAN_VAULT_PATH" --include="*.md" > /tmp/a.txt
  grep -rl "\[\[ConceptB\]\]" "$OBSIDIAN_VAULT_PATH" --include="*.md" > /tmp/b.txt
  comm -12 <(sort /tmp/a.txt) <(sort /tmp/b.txt) | wc -l
  ```
- Flag pairs with co-occurrence ≥ 3 that have no existing synthesis page

**How to fix:**
- Run `/wiki-synthesize` to automatically discover and fill the top gaps

## Output Format

Report findings as a structured list:

```markdown
## Wiki Health Report

### Orphaned Pages (N found)
- `concepts/foo.md` — no incoming links

### Broken Wikilinks (N found)
- `entities/bar.md:15` — links to [[nonexistent-page]]

### Missing Frontmatter (N found)
- `skills/baz.md` — missing: tags, sources

### Stale Content (N found)
- `references/paper-x.md` — source modified 2024-03-10, page last updated 2024-01-05

### Contradictions (N found)
- `concepts/scaling.md` claims "X" but `synthesis/efficiency.md` claims "not X"

### Index Issues (N found)
- `concepts/new-page.md` exists on disk but not in index.md

### Missing Summary (N found — soft)
- `concepts/foo.md` — no `summary:` field
- `entities/bar.md` — summary exceeds 200 chars

### Provenance Issues (N found)
- `concepts/scaling.md` — AMBIGUOUS > 15%: 22% of claims are ambiguous (re-source or move to synthesis/)
- `entities/some-tool.md` — drift: frontmatter says inferred=0.10, recomputed=0.45
- `concepts/transformers.md` — hub page (31 incoming links) with INFERRED=28%: errors here propagate widely
- `synthesis/speculation.md` — unsourced synthesis: no `sources:` field, 55% inferred

### Fragmented Tag Clusters (N found)
- **#systems** — 7 pages, cohesion=0.06 ⚠️ — run cross-linker on this tag
- **#databases** — 5 pages, cohesion=0.10 ⚠️

### Visibility Issues (N found)
- `entities/user-records.md` — contains `email:` value pattern but no `visibility/pii` tag
- `concepts/auth-flow.md` — tagged `visibility/pii` but missing `sources:` frontmatter
- `_meta/taxonomy.md` — contains `visibility/internal` entry (system tag must not be in taxonomy)

### Misc Promotion Candidates (N found)
Pages in misc/ that have ≥ 3 connections to a single project and are ready to be promoted:

| Page | Top Project | Affinity Score |
|---|---|---|
| `misc/web-martinfowler-articles-microservices.md` | `obsidian-wiki` | 4 |

### Synthesis Gaps (N found)
Concept pairs that co-occur frequently but have no synthesis page:

| Pair | Co-occurrence | Suggested Action |
|---|---|---|
| [[Caching]] × [[Consistency]] | 5 pages | Run `/wiki-synthesize` |
| [[Testing]] × [[Observability]] | 3 pages | Run `/wiki-synthesize` |
```

## After Linting

Append to `log.md`:
```
- [TIMESTAMP] LINT issues_found=N orphans=X broken_links=Y stale=Z contradictions=W prov_issues=P missing_summary=S fragmented_clusters=F visibility_issues=V promotion_candidates=C synthesis_gaps=G
```

Offer to fix issues automatically or let the user decide which to address.
