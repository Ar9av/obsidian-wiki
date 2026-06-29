---
name: wiki-dashboard
description: >
  Create dynamic, queryable dashboard views of the Obsidian vault using Obsidian Bases or Dataview.
  Use this skill when the user says "create a dashboard", "vault dashboard", "show all X as a table",
  "dynamic view", "query my vault", "build a content index", "show me all concepts/entities/projects",
  or wants a structured, auto-updating view of their wiki content.
  Bases is native to Obsidian 1.8+ (no plugin needed). Dataview requires the community plugin.
---

# Wiki Dashboard — Dynamic Vault Views

Two tools available: **Obsidian Bases** (native, GUI-driven, no plugin) and **Dataview** (community plugin, SQL-like, more powerful). Check which the user has and prefer Bases unless they ask for Dataview or need GROUP BY / computed columns.

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (inline `@name` override → walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH`.
2. Read `$OBSIDIAN_VAULT_PATH/index.md` to understand what categories and pages exist.
3. Ask the user what they want to view if not specified — folder, tag, category, date range?
4. Ask if they have Dataview installed if you're unsure which tool to use.

---

## Option A — Obsidian Bases (`.base` files)

Bases are YAML files that define live views over vault notes. Native to Obsidian 1.8+, no plugin needed.

### Official canonical schema

Top-level keys:

```yaml
filters:      # Global filter applied to all views (expression strings under and/or/not)
formulas:     # Named computed properties — referenced as formula.<name>
properties:   # Display config per property — sets displayName for column headers
summaries:    # Aggregation formulas (e.g. mean, sum)
views:        # Array of view definitions (required)
```

Each item in `views:`:

```yaml
views:
  - type: table          # table | list | cards | map
    name: "View Name"    # display label
    limit: 50            # optional max rows
    order:               # column display order (list of property/formula names)
      - file.name
      - note.updated
    groupBy:             # grouping — goes INSIDE the view, NOT at top level
      property: note.tags
      direction: ASC     # ASC | DESC
    filters:             # view-specific filter (merges with global filters)
      and:
        - 'note.status != "done"'
    summaries:
      formula.myFormula: Average
```

### Filter syntax — CRITICAL

**Filters use expression strings, not typed objects.** Always wrap in `and:`, `or:`, or `not:` — a bare list causes a "may only have one of and/or/not keys" parse error.

```yaml
# CORRECT
filters:
  and:
    - file.inFolder("concepts")

# WRONG — typed objects (parse error)
filters:
  - type: folder
    folder: concepts
```

Filters support nesting:
```yaml
filters:
  or:
    - file.hasTag("book")
    - and:
        - file.inFolder("concepts")
        - file.hasTag("research")
    - not:
        - file.hasTag("archived")
```

### Property name conventions

Different contexts use different naming — confirmed from Obsidian's auto-reformat behaviour:

| Context | Frontmatter field `tags` | File name | Formula |
|---|---|---|---|
| `properties:` keys | `note.tags` | `file.name` | `formula.<name>` |
| `order:` values | `tags` (bare) | `file.name` | `formula.<name>` |
| `groupBy.property:` | `tags` (bare) | `file.name` | — |
| `filters:` expressions | `file.hasTag(...)` / `note.tags` | `file.name` | `formula.<name>` |
| `formulas:` expressions | `note.tags`, `note.updated` | `file.name` | — |

### Basic table — folder filter

```yaml
filters:
  and:
    - file.inFolder("concepts")
properties:
  file.name:
    displayName: Page
  note.tags:
    displayName: Tags
  note.summary:
    displayName: Summary
  note.updated:
    displayName: Updated
views:
  - type: table
    name: Table
    order:
      - file.name
      - tags
      - summary
      - updated
```

### Cards view — folder filter

```yaml
filters:
  and:
    - file.inFolder("entities")
properties:
  file.name:
    displayName: Entity
  note.title:
    displayName: Full Name
  note.tags:
    displayName: Tags
  note.summary:
    displayName: Summary
views:
  - type: cards
    name: Cards
    order:
      - file.name
      - title
      - tags
      - summary
```

### Group by property — groupBy goes INSIDE the view

When `groupBy` is set, **omit that property from `order:`** — it becomes the group header row and adding it as a column too causes duplication.

```yaml
filters:
  and:
    - file.inFolder("concepts")
properties:
  file.name:
    displayName: Concept
  note.summary:
    displayName: Summary
  note.updated:
    displayName: Updated
views:
  - type: table
    name: By Domain
    groupBy:
      property: tags        # bare property name, no note. prefix
      direction: ASC
    order:
      - file.name           # do NOT include tags here — already the group header
      - summary
      - updated
```

### Tag filter

```yaml
filters:
  and:
    - file.hasTag("machine-learning")
properties:
  file.name:
    displayName: Page
  note.category:
    displayName: Category
  note.summary:
    displayName: Summary
views:
  - type: table
    name: Table
    order:
      - file.name
      - category
      - summary
```

### Multi-filter (folder AND tag)

```yaml
filters:
  and:
    - file.inFolder("projects")
    - file.hasTag("active")
properties:
  file.name:
    displayName: Project
  note.summary:
    displayName: Summary
  note.updated:
    displayName: Last Updated
views:
  - type: cards
    name: Cards
    order:
      - file.name
      - summary
      - updated
```

### OR filter (two folders)

```yaml
filters:
  or:
    - file.inFolder("concepts")
    - file.inFolder("entities")
properties:
  file.name:
    displayName: Page
  note.category:
    displayName: Category
  note.updated:
    displayName: Updated
views:
  - type: table
    name: Table
    order:
      - file.name
      - category
      - updated
```

### Computed column via formulas

```yaml
filters:
  and:
    - file.inFolder("concepts")
formulas:
  days_stale: "floor((now() - note.updated) / 86400000)"
properties:
  file.name:
    displayName: Page
  note.updated:
    displayName: Updated
  formula.days_stale:
    displayName: Days Stale
views:
  - type: table
    name: Stale
    order:
      - file.name
      - updated
      - formula.days_stale
```

### Filter expression reference

| Expression | What it does |
|---|---|
| `file.inFolder("path")` | Pages in that folder |
| `file.hasTag("tag")` | Pages with that tag (no `#` prefix) |
| `file.hasLink("Note Name")` | Pages linking to a note |
| `file.name == "note-name"` | Exact filename match |
| `file.ext == "md"` | Filter by extension |
| `note.propertyName` | Any frontmatter property |
| `formula.formulaName` | A named formula result |
| `now()` | Current timestamp in ms |

> **On Obsidian UI-generated format:** When Obsidian's GUI writes or reformats a `.base` file it may output a simplified shorthand with top-level `columns:`, `sort:`, and `view:` keys instead of the canonical schema. That format also works — Obsidian accepts both. Manually authored files should use the canonical schema above.

---

## Option B — Dataview (community plugin)

Dataview uses a SQL-like query language inside ` ```dataview ``` ` code blocks in any note. More powerful than Bases for computed columns, GROUP BY, and cross-folder queries.

### Basic table — folder

````markdown
```dataview
TABLE
  tags AS "Tags",
  summary AS "Summary",
  file.mtime AS "Last Modified"
FROM "concepts"
SORT file.mtime DESC
```
````

### Table with clickable links (TABLE WITHOUT ID)

````markdown
```dataview
TABLE WITHOUT ID
  file.link AS "Entity",
  tags AS "Tags",
  summary AS "Summary"
FROM "entities"
SORT file.name ASC
```
````

### GROUP BY — use `rows.` prefix after grouping

After `GROUP BY`, individual file properties must be prefixed with `rows.` — otherwise the column is empty or errors.

````markdown
```dataview
TABLE WITHOUT ID
  rows.file.link AS "Concept",
  rows.summary AS "Summary"
FROM "concepts"
GROUP BY tags[0] AS "Domain"
```
````

### Stale pages — use `file.mtime` for date math

Avoid `choice(updated, date(updated), file.mtime)` — mixed date formats in `updated` frontmatter cause arithmetic errors. `file.mtime` is always a valid DateTime.

````markdown
```dataview
TABLE WITHOUT ID
  file.link AS "Page",
  category AS "Type",
  file.mtime AS "Last Modified",
  (date(today) - file.mtime).days + " days" AS "Age"
FROM "concepts" OR "entities" OR "projects"
WHERE file.name != file.folder
WHERE (date(today) - file.mtime).days > 30
SORT (date(today) - file.mtime).days DESC
```
````

### Multi-folder query

````markdown
```dataview
TABLE
  summary AS "Summary",
  file.mtime AS "Last Modified"
FROM "projects"
WHERE file.name != file.folder
SORT file.mtime DESC
```
````

### Dataview reference

| Clause | Usage |
|---|---|
| `FROM "folder"` | All notes in folder |
| `FROM #tag` | All notes with tag |
| `FROM "a" OR "b"` | Union of two folders |
| `WHERE file.name != file.folder` | Exclude folder index pages |
| `GROUP BY field AS "Label"` | Group rows — use `rows.` for properties after this |
| `SORT field DESC` | Sort direction |
| `file.link` | Clickable wikilink |
| `file.mtime` | Last modified time (always valid DateTime) |
| `(date(today) - file.mtime).days` | Days since last modification |

---

## Step 3: Write the File

**Bases:** Target path `$OBSIDIAN_VAULT_PATH/_meta/<dashboard-name>.base`

**Dataview:** Write queries directly into any `.md` note. A dedicated dashboard note at `$OBSIDIAN_VAULT_PATH/_meta/dashboard.md` works well for multi-section views.

Slug examples:
- "All concepts" → `_meta/concepts-index.base`
- "Recent ingests" → `_meta/recent-ingests.base`
- "Project overview" → `_meta/projects-overview.base`
- "Stale pages" → `_meta/stale-pages.base`
- "Full dashboard" → `_meta/dashboard.md`

Create `_meta/` if it doesn't exist yet.

## Step 4: Embed Bases (optional)

To embed a `.base` inside a note:

```markdown
## Entities
![[_meta/entities-tracker.base]]
```

Ask before modifying an existing note.

## Step 5: Update Tracking

Append to `$OBSIDIAN_VAULT_PATH/log.md`:
```
- [TIMESTAMP] WIKI_DASHBOARD name="<slug>" tool=bases|dataview view=<type> filter="<description>"
```

No manifest or index update needed — dashboards are live queries, not static pages.

## Common Dashboard Recipes

| Dashboard | Best tool | What it shows |
|---|---|---|
| **Content index** | Bases or Dataview | All pages grouped by category, sorted by updated |
| **Entity tracker** | Bases (cards) | Entity pages as a visual card gallery |
| **Concepts by domain** | Dataview | Concepts grouped by first tag using GROUP BY |
| **Ingestion log** | Either | Pages sorted by `created` date |
| **Stale content** | Dataview | Pages not touched in 30+ days with day count |
| **Project overview** | Either | Project pages with last-sync date |
| **Research tracker** | Dataview | Synthesis pages tagged `research` |

## Quality Checklist

- [ ] Bases: filters use expression strings under `and:`/`or:`/`not:`, never typed objects
- [ ] Bases: `groupBy` goes inside the view definition — not as a top-level key
- [ ] Bases: column headers set via `properties: <name>: displayName: "..."`, not `columns: [{title}]`
- [ ] Bases: `formulas:` used for computed columns, referenced as `formula.<name>` in order/properties
- [ ] Dataview: GROUP BY queries use `rows.property` not bare `property`
- [ ] Dataview: date arithmetic uses `file.mtime`, not `choice(updated, ...)`
- [ ] File written to `_meta/` with a descriptive slug
- [ ] `log.md` updated
- [ ] User told how to embed Bases (`![[_meta/<name>.base]]`) or open the dashboard note

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
