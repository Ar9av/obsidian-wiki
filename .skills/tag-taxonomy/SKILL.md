---
name: tag-taxonomy
description: >
  Enforce consistent tagging across the Obsidian wiki using a controlled vocabulary.
  Use this skill when the user says "fix my tags", "normalize tags", "clean up tags",
  "tag audit", "what tags should I use", "tag taxonomy", or whenever you're creating or
  updating wiki pages and need to choose the right tags. Also trigger when the user asks
  about tag conventions, wants to add a new tag to the taxonomy, or says "my tags are a mess".
  Always consult this skill's taxonomy file before assigning tags to any wiki page.
---

# Tag Taxonomy — Controlled Vocabulary for Wiki Tags

You are enforcing consistent tagging across the wiki by normalizing tags to a controlled vocabulary.

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH`
2. Read `$OBSIDIAN_VAULT_PATH/_meta/taxonomy.md` — this is the canonical tag list
3. Read `index.md` to understand the wiki's scope

## The Taxonomy File

The canonical tag vocabulary lives at `$OBSIDIAN_VAULT_PATH/_meta/taxonomy.md`. It defines:

- **Canonical tags** — the tags that should be used
- **Aliases** — common alternatives that should be mapped to the canonical form
- **Rules** — max 5 tags per page, lowercase/hyphenated, prefer broad over narrow
- **Migration guide** — specific renames for known inconsistencies

**Always read this file before tagging.** It's the source of truth.

## Reserved System Tags

`visibility/` is a reserved tag group with special rules. These tags are **not** domain or type tags and are managed separately from the taxonomy vocabulary:

| Tag | Purpose |
|---|---|
| `visibility/public` | Explicitly public — shown in all modes (same as no tag) |
| `visibility/internal` | Team-only — excluded in filtered query/export mode |
| `visibility/pii` | Sensitive data — excluded in filtered query/export mode |

**Rules for `visibility/` tags:**
- They do **not** count toward the 5-tag limit
- Only one `visibility/` tag per page
- Omit entirely when content is clearly public — no tag needed
- Never add `visibility/internal` just because content is technical; use it only for genuinely team-restricted knowledge
- When running a tag audit, report `visibility/` tag usage separately — do not flag them as unknown or non-canonical

When normalizing tags, leave `visibility/` tags untouched — they are not subject to alias mapping.

## Mode 1: Tag Audit

When the user wants to see the current state of tags:

### Step 1: Scan all pages

```
Glob: $VAULT_PATH/**/*.md (excluding _archives/, .obsidian/, _meta/)
Extract: tags field from YAML frontmatter
```

### Step 2: Build a tag frequency table

For each tag found, count how many pages use it. Flag:

- **Unknown tags** — not in the taxonomy's canonical list
- **Alias tags** — using an alias instead of the canonical form (e.g., `nextjs` instead of `react`)
- **Over-tagged pages** — pages with more than 5 tags
- **Untagged pages** — pages with no tags or empty tags field

### Step 3: Report

```markdown
## Tag Audit Report

### Summary

- Total unique tags: 47
- Canonical tags used: 32
- Non-canonical tags found: 15
- Pages over tag limit (5): 3
- Untagged pages: 2

### Non-Canonical Tags Found

| Current Tag | → Canonical | Pages Affected |
| ----------- | ----------- | -------------- |
| `nextjs`    | `react`     | 4              |
| `next-js`   | `react`     | 2              |
| `robotics`  | `ml`        | 1              |
| `windows98` | `retro`     | 3              |

### Unknown Tags (not in taxonomy)

| Tag          | Pages | Recommendation                   |
| ------------ | ----- | -------------------------------- |
| `flutter`    | 1     | Add to taxonomy under Frameworks |
| `kubernetes` | 2     | Add to taxonomy under DevOps     |

### Over-Tagged Pages

| Page                   | Tag Count | Tags                 |
| ---------------------- | --------- | -------------------- |
| `entities/jane-doe.md` | 8         | ai, ml, founder, ... |
```

## Mode 2: Tag Normalization

When the user wants to fix the tags:

### Step 1: Run audit (above)

### Step 2: Apply fixes

For each page with non-canonical tags:

1. Read the page
2. Replace alias tags with their canonical form from the taxonomy
3. If page has > 5 tags, suggest which to drop (keep the most specific/relevant ones)
4. Write the updated frontmatter

**Example:**

```yaml
# Before
tags: [nextjs, ai, ml-engineer, windows98, creative-coding, game, 8-bit, portfolio]

# After
tags: [react, ai, ml, retro, generative-art]
```

### Step 3: Handle unknowns

For tags that aren't in the taxonomy and aren't aliases:

- If the tag is used on 2+ pages, suggest adding it to the taxonomy
- If the tag is used on 1 page, suggest replacing it with the closest canonical tag
- Ask the user before making changes to unknown tags

### Step 4: Update taxonomy

If new canonical tags were agreed upon, append them to `_meta/taxonomy.md` in the correct section.

## Mode 3: Tagging a New Page

When you're creating a wiki page and need to choose tags:

1. Read `_meta/taxonomy.md`
2. Select up to 5 tags that best describe the page:
   - 1-2 **domain tags** (what subject area)
   - 1 **type tag** (what kind of thing)
   - 0-1 **project tags** (if project-specific)
   - 0-1 additional descriptive tags
3. Use only canonical tags — never aliases
4. If no existing tag fits, check if it's worth adding to the taxonomy

## Mode 4: Adding a New Tag

When the user wants to add a tag to the vocabulary:

1. Check if an existing tag already covers the concept (suggest it if so)
2. If genuinely new, determine which section it belongs in (Domain, Type, Project)
3. Add it to `_meta/taxonomy.md` with:
   - The canonical tag name
   - What it's used for
   - Any aliases to redirect

## After Any Tag Operation

Append to `log.md`:

```
- [TIMESTAMP] TAG_AUDIT tags_normalized=N unknown_tags=M pages_modified=P
```

Or for normalization:

```
- [TIMESTAMP] TAG_NORMALIZE tags_renamed=N pages_modified=M new_tags_added=P
```

**`hot.md`** — Read `$OBSIDIAN_VAULT_PATH/hot.md` (create from the template in `wiki-ingest` if missing). Update **Recent Activity** with a one-line summary — e.g. "Tag audit: normalized 14 tags across 28 pages; 2 new canonical tags added." Keep the last 3 operations. Update `updated` timestamp.
