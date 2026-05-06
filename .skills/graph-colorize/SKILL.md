---
name: graph-colorize
description: >
  Color-code the Obsidian graph view by rewriting `.obsidian/graph.json` colorGroups.
  Use this skill when the user says "color my graph", "color code obsidian", "colorize
  the graph", "color the graph by tag", "color by category", "highlight visibility
  in graph", "make the graph colorful", "distinguish tags in graph", or wants nodes
  in Obsidian's graph view tinted by tag, folder, or visibility. Generates a
  `colorGroups` array from the vault's actual tags/categories and merges it into the
  existing graph.json without clobbering other graph settings. Always backs up first.
---

# Graph Colorize — Color-code the Obsidian Graph View

You are rewriting `$OBSIDIAN_VAULT_PATH/.obsidian/graph.json` so Obsidian's graph view tints nodes by tag, folder, or visibility.

Obsidian stores graph settings in `<vault>/.obsidian/graph.json`. The `colorGroups` array is a list of `{query, color}` pairs; the first matching query wins per node. Queries use Obsidian's search syntax: `tag:#foo`, `path:"concepts"`, `file:foo`, etc. Color is `{"a": 1, "rgb": <packed-int>}` where the int is `(R << 16) | (G << 8) | B`.

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH`.
2. Confirm `$OBSIDIAN_VAULT_PATH/.obsidian/` exists. If it doesn't, the vault has never been opened in Obsidian — tell the user to open the vault once in Obsidian, then re-run.
3. **Warn the user if Obsidian is likely open**: Obsidian overwrites `graph.json` on close. Tell them to close the vault first, or be ready to reload (Cmd/Ctrl+R) and not touch the graph settings until they reload.

## Step 1: Pick a Mode

Infer the mode from the user's phrasing. If ambiguous, default to **by-tag**.

| User intent | Mode |
|---|---|
| "color by tag", "color my graph", "make it colorful" (default) | `by-tag` |
| "color by folder", "color by category", "color by directory" | `by-category` |
| "highlight visibility", "show internal/pii in graph", "visibility colors" | `by-visibility` |
| User provides explicit mapping (`tag:#foo = red`, or JSON blob) | `custom` |
| "combine tag and visibility" / "both" | `combined` (visibility first, then tag) |

## Step 2: Build the `colorGroups` Array

### Palette (10 distinct, colorblind-friendly colors)

Use in order. If more groups than colors, cycle and add a lightness shift by dividing brightness ~20% via a second pass — or just cap at 10 and tell the user the remaining tags share the "other" color.

| # | Hex | rgb (packed int) | Role |
|---|---|---|---|
| 0 | `#4E79A7` | `5142951` | blue |
| 1 | `#F28E2B` | `15896107` | orange |
| 2 | `#E15759` | `14767961` | red |
| 3 | `#76B7B2` | `7780786` | teal |
| 4 | `#59A14F` | `5873999` | green |
| 5 | `#EDC948` | `15583048` | yellow |
| 6 | `#B07AA1` | `11565217` | purple |
| 7 | `#FF9DA7` | `16751527` | pink |
| 8 | `#9C755F` | `10253663` | brown |
| 9 | `#BAB0AC` | `12234924` | gray |

Every color is wrapped as `{"a": 1, "rgb": <int>}`.

### Mode: `by-tag`

1. Glob `$VAULT_PATH/**/*.md` excluding `_archives/`, `_raw/`, `.obsidian/`, `node_modules/`, `index.md`, `log.md`, `_insights.md`.
2. Parse frontmatter `tags` from each page. Count usage per tag.
3. **Drop `visibility/*` tags** from the frequency list — they are reserved system tags, handled only in `by-visibility` or `combined` mode.
4. Take the top 10 tags by usage. If there are fewer than 10 unique tags, use all of them.
5. For each tag `T` at index `i`: emit `{"query": "tag:#T", "color": palette[i]}`.
6. Optionally, append a final catch-all entry for untagged pages at the end: `{"query": "-[\"tag\":]", "color": palette[9]}` — **skip** if color slot 9 is already taken by a real tag.

### Mode: `by-category`

Use the seven vault top-level folders in this fixed order so colors are stable across runs:

| Folder | Color index |
|---|---|
| `concepts` | 0 (blue) |
| `entities` | 1 (orange) |
| `skills` | 2 (red) |
| `references` | 3 (teal) |
| `synthesis` | 4 (green) |
| `projects` | 5 (yellow) |
| `journal` | 6 (purple) |

Emit one entry per folder that exists AND contains at least one `.md` file. Each entry is:

```json
{"query": "path:\"<folder>\"", "color": {"a": 1, "rgb": <int>}}
```

### Mode: `by-visibility`

Emit exactly three entries, in this order (first-match wins, so most restrictive comes first):

1. `visibility/pii` → `#E15759` (red, rgb 14767961)
2. `visibility/internal` → `#F28E2B` (orange, rgb 15896107)
3. `visibility/public` → `#59A14F` (green, rgb 5873999)

```json
{"query": "tag:#visibility/pii", "color": {"a": 1, "rgb": 14767961}}
```

Pages with no `visibility/` tag remain Obsidian's default color — do not add a catch-all.

### Mode: `combined`

Emit `by-visibility` entries first, then `by-tag` entries. Visibility wins on conflict because it appears first in the list.

### Mode: `custom`

If the user gave explicit mappings, honor them literally. Convert any hex they give (e.g. `#FF00FF`) to packed int using `int(hex_without_hash, 16)`. Wrap each as `{"a": 1, "rgb": <int>}`.

## Step 3: Merge into graph.json (Do Not Clobber)

1. Read the existing `$VAULT_PATH/.obsidian/graph.json`. If it doesn't exist, start from this minimal default:

   ```json
   {
     "collapse-filter": true,
     "search": "",
     "showTags": false,
     "showAttachments": false,
     "hideUnresolved": false,
     "showOrphans": true,
     "collapse-color-groups": false,
     "colorGroups": [],
     "collapse-display": true,
     "showArrow": false,
     "textFadeMultiplier": 0,
     "nodeSizeMultiplier": 1,
     "lineSizeMultiplier": 1,
     "collapse-forces": true,
     "centerStrength": 0.518713248970312,
     "repelStrength": 10,
     "linkStrength": 1,
     "linkDistance": 250,
     "scale": 1,
     "close": true
   }
   ```

2. **Back up first**: copy the existing file to `.obsidian/graph.json.backup-<YYYYMMDD-HHMM>` before writing. If a backup from the same minute exists, reuse it — don't pile up duplicates.

3. Replace **only** the `colorGroups` field with your new array. Leave every other field untouched. This preserves the user's zoom, physics, filter, search, and display preferences.

4. Write the file back with the same JSON style as the original (usually compact single-line or 2-space indent — preserve what's there).

## Step 4: Report and Log

Print a summary like:

```
Graph colorized → .obsidian/graph.json
  Mode:    by-tag
  Groups:  7 color assignments
  Palette: blue, orange, red, teal, green, yellow, purple
  Backup:  .obsidian/graph.json.backup-20260424-1432

Reload Obsidian (Cmd/Ctrl+R) to see the new colors.
If Obsidian is currently open, close it first OR reload immediately — Obsidian
overwrites graph.json on close and can erase these changes.
```

Append to `$VAULT_PATH/log.md`:

```
- [TIMESTAMP] GRAPH_COLORIZE mode=<mode> groups=<N> backup=graph.json.backup-<stamp>
```

## Edge Cases

- **No tags in vault** in `by-tag` mode → fall back to `by-category` and tell the user.
- **User wants to undo** → restore from the latest `graph.json.backup-*` and note that in `log.md`.
- **User wants to clear all color groups** → set `colorGroups: []`, back up, log as `GRAPH_COLORIZE mode=clear`.
- **`.obsidian/` missing** → the vault hasn't been opened in Obsidian yet. Tell the user to open it once, then re-run. Don't create `.obsidian/` yourself — Obsidian populates many files there on first open.
- **Query syntax gotchas**: folder paths with spaces need quoting (`path:"my folder"`); tags with nested slashes work literally (`tag:#visibility/internal`); don't URL-encode.
- **Obsidian open during edit**: surface the risk — Obsidian reads graph.json at startup and **rewrites it on close**. If the user is editing live, tell them to close Obsidian first or run the reload (Cmd/Ctrl+R) immediately and avoid opening graph settings before they do.

## Notes

- This is a pure config edit — no page content changes, no frontmatter writes.
- Re-running is safe: each run creates a new backup, only `colorGroups` is rewritten.
- If the user has manually curated color groups they want to keep, offer `combined` mode or ask before overwriting.
- The palette here matches `wiki-export`'s `graph.html` community colors, so the Obsidian graph and the exported visualization look consistent.
