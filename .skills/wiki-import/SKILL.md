---
name: wiki-import
description: >
  Import a wiki knowledge graph into the current vault — either from a graph.json export
  file (stubs) or from an OKF (Open Knowledge Format) markdown bundle (full page bodies).
  Use this skill when the user says "import wiki", "import from export", "load graph.json",
  "import vault", "import OKF bundle", "import OKF", "load OKF", "import markdown bundle",
  "/wiki-import", or wants to transfer pages from one vault to another using the output of wiki-export.
---

# Wiki Import — Reconstruct Pages from an Export

You are importing a vault's knowledge into the current vault from one of two sources produced by `wiki-export`:

- **`graph.json`** — the graph skeleton. Reconstructs page **stubs** (frontmatter, typed relationships, a `## Related` link list — no body). Lossy.
- **OKF bundle** (a `wiki-export/okf/` directory) — the actual markdown files. Reconstructs **full pages** with their real bodies. Lossless. Use this for true vault-to-vault transfer.

Either way, the import writes pages with correct frontmatter and wikilinks, then updates all vault metadata. **Step 2, Step 3 (graph only), and Step 5 are shared; Step 4 forks by source type.**

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (inline `@name` override → walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH`.
2. Read `$OBSIDIAN_VAULT_PATH/AGENTS.md` if it exists — apply any owner-specific conventions.

## Step 1: Locate and Detect Source Type

**Find the import source:**
- If the user provided a path argument, use it directly.
- Otherwise auto-detect, in order: `./wiki-export/okf/` (a directory) → `./wiki-export/graph.json` (a file).
- If neither exists, ask the user for the path.

**Detect the source type:**
- The path is a **file ending in `.json`** → **graph.json import** (validate below, then Step 3 + Step 4-Graph).
- The path is a **directory** containing `.md` files with OKF frontmatter (a `type:` key), and/or a root `index.md` with `okf_version` → **OKF bundle import** (skip Step 3; go to Step 4-OKF).
- Anything else → report what's wrong and stop.

**Validate a graph.json source:**
- Must be valid JSON
- Must have top-level keys: `nodes` (array), `links` (array), `graph` (object)
- Must have at least 1 node

If validation fails, report what's wrong and stop.

**Validate an OKF bundle source:**
- Must contain at least 1 non-reserved `.md` file (i.e. not `index.md`/`log.md`) with parseable YAML frontmatter containing a non-empty `type`.
- A `.md` with no frontmatter or no `type` is skipped (with a count), not fatal — OKF consumers are permissive (OKF §9).

**Show a preview before importing:**

graph.json:
```
Import preview (graph.json — stubs)
  Source: <path>  (exported at <graph.exported_at>)
  Nodes:  N total  (concepts: A, entities: B, skills: C, references: D, ...)
  Links:  M edges  (X typed, Y untyped)
  Target: $OBSIDIAN_VAULT_PATH
```

OKF bundle:
```
Import preview (OKF bundle — full pages)
  Source: <dir>  (okf_version <ver if present>)
  Pages:  N total  (concepts: A, entities: B, skills: C, references: D, ...)
  Target: $OBSIDIAN_VAULT_PATH
```

## Step 2: Determine Conflict Resolution Mode

Read the user's phrasing to determine mode. Default is `merge`.

| Mode | Trigger phrases | Behaviour |
|---|---|---|
| `merge` | (default, no special phrasing) | Existing pages: update frontmatter tags/summary/relationships and add missing wikilinks; new pages: create stub. |
| `skip` | "skip existing", "don't overwrite", "only new pages" | Leave existing pages completely untouched; only create pages that don't exist yet. |
| `overwrite` | "overwrite", "replace existing", "force import" | Replace all matched pages with freshly reconstructed stubs regardless of existing content. |

## Step 3: Build Internal Maps  *(graph.json only — skip for OKF bundles)*

Before writing anything, build two maps from the `links` array:

**Adjacency map** — for each node id, collect all neighbour ids (edges in either direction):
```
adjacency["concepts/transformers"] = ["entities/vaswani", "concepts/lstm", ...]
```

**Typed edge map** — for each node id, collect outgoing typed edges only (`typed: true`):
```
typed_edges["concepts/transformers"] = [
  {target: "concepts/lstm", relation: "contradicts"},
  ...
]
```

## Step 4-Graph: Reconstruct Pages from graph.json  *(graph.json source only)*

Record counts: `created = 0`, `skipped = 0`, `merged = 0`.

For each node in `nodes`:

1. Compute `page_path = $VAULT/<node.id>.md`
2. Ensure the parent directory exists (e.g. `$VAULT/concepts/`)
3. Check if the file already exists:
   - **merge mode (default) + exists** → read existing file, apply merge logic (see below), increment `merged`
   - **merge mode (default) + doesn't exist** → proceed to create stub, increment `created`
   - **skip mode + exists** → increment `skipped`, continue to next node
   - **skip mode + doesn't exist** → proceed to create stub, increment `created`
   - **overwrite mode + exists** → proceed to write fresh stub (overwrite), increment `merged`
   - **overwrite mode + doesn't exist** → proceed to create stub, increment `created`

### Page template (new or overwrite)

```markdown
---
title: <node.label>
category: <node.category>
tags: <node.tags as YAML list>
sources:
  - "imported from <graph.json path>"
<if node.summary exists>
summary: "<node.summary>"
</if>
<if typed_edges[node.id] is non-empty>
relationships:
<for each {target, relation} in typed_edges[node.id]>
  - target: "[[<target>]]"
    type: <relation>
</for>
</if>
lifecycle: draft
lifecycle_changed: <today YYYY-MM-DD>
base_confidence: 0.5
tier: supporting
created: <ISO timestamp>
updated: <ISO timestamp>
---

# <node.label>

<node.summary paragraph if available, else omit>

## Related

<for each neighbour in adjacency[node.id], sorted alphabetically>
<if edge is typed>
- [[<neighbour>]] — <relation>
<else>
- [[<neighbour>]]
</if>
</for>
```

If `adjacency[node.id]` is empty, omit the `## Related` section entirely.

### Merge logic (merge mode, existing page)

1. Read the existing page's frontmatter.
2. **Tags**: union of existing tags and `node.tags` (deduplicated, keep existing order, append new ones).
3. **Summary**: if the existing page has no `summary` field and `node.summary` exists, add it.
4. **Relationships**: union of existing `relationships:` entries and `typed_edges[node.id]` — skip entries where the same `(target, type)` pair already exists.
5. **Updated**: set `updated` to the current ISO timestamp.
6. **Body**: scan for a `## Related` section. If it exists, append any missing wikilinks from `adjacency[node.id]` that aren't already linked anywhere in the body. If no `## Related` section exists, append one with the missing links.
7. Leave the rest of the body untouched.

## Step 4-OKF: Reconstruct Pages from an OKF bundle  *(OKF source only)*

Record counts: `created = 0`, `skipped = 0`, `merged = 0`, `unparseable = 0`.

Walk the bundle directory tree. For each `.md` file that is **not** a reserved file (`index.md`, `log.md`):

1. Parse the YAML frontmatter. If it has no frontmatter or no non-empty `type`, increment `unparseable` and skip the file.
2. Compute the **concept id** = the file's path relative to the bundle root, with `.md` stripped (e.g. `concepts/transformers.md` → `concepts/transformers`). The target page is `$VAULT/<concept-id>.md`.
3. **Reverse-map frontmatter** (the inverse of the canonical mapping table in `wiki-export` Step 3.5):
   - `title` ← `title`.
   - `category` ← the preserved `category` extension key if present; **else** lower-case the directory prefix of the concept id (`concepts/…` → `concepts`); **else** derive from `type` (`Concept`→`concepts`, `Entity`→`entities`, `Skill`→`skills`, `Reference`→`references`, `Synthesis`→`synthesis`, `Project`→`projects`, `Journal`→`journal`).
   - `tags` ← `tags`.
   - `summary` ← `description`.
   - `updated` ← `timestamp` (or now if absent).
   - `created` ← the preserved `created` extension key if present, else now.
   - `sources` ← the preserved `sources` extension key if present; else `["imported from OKF bundle <bundle path>"]`. If a `resource` URL is present and not already in `sources`, add it.
   - Carry through any other preserved extension keys verbatim (`relationships`, `lifecycle`, `tier`, `base_confidence`, …). These make the round-trip lossless.
4. **Reverse-transform body links** — markdown links that point at `.md` paths become wikilinks (this restores both real cross-links and forward-references the exporter preserved per `wiki-export` Step 3.5):
   - `[text](../concepts/transformers.md)` or `[text](/concepts/transformers.md)` → resolve the path (relative to this file's dir, or bundle-root for `/`-absolute) to a concept id → `[[concepts/transformers]]`, or `[[concepts/transformers|text]]` when `text` differs from the target's title. The target's title comes from the bundle page when it exists; otherwise compare against the last path segment.
   - Treat the markdown target as a **file path first**: normalize the `.md` path relative to the current file, then strip the trailing `.md` from the resolved file path to recover the page id. Do not try to infer the id from directory traversal segments before resolving the full file path. This preserves round-trips for folder-note layouts like `projects/social-twitter.md` plus `projects/social-twitter/...`, where `../../social-twitter.md` must restore to `projects/social-twitter`.
   - This applies **even when the target page is not in the bundle** — a path-form link to a not-yet-written page round-trips back to a dangling `[[wikilink]]` (Obsidian supports these; OKF §5.3 expects them). Do not leave it as a markdown link.
   - When `OBSIDIAN_LINK_FORMAT=markdown` is set in config, **keep** markdown links (just rewrite the path to be vault-relative); do not convert to wikilinks.
   - Leave external `http(s)://` links and `# Citations` sections untouched.
5. **Write the page** using the conflict mode from Step 2:
   - **merge + exists** → reverse-map frontmatter and merge it into the existing page (union `tags`; fill `summary`/`sources` only if missing; union `relationships`; refresh `updated`). For the body, OKF carries a real body: replace the existing body with the bundle body **only if the existing page is a stub** (body is just a heading + `## Related`); otherwise keep the existing body and append any bundle `# Citations` / new `##` sections not already present. Increment `merged`.
   - **merge + doesn't exist** → write the full page (frontmatter + full bundle body). Increment `created`.
   - **skip + exists** → increment `skipped`, continue.
   - **skip + doesn't exist** → write the full page. Increment `created`.
   - **overwrite + exists** → write the full page, replacing the existing one. Increment `merged` (label as `Replaced` in the summary).
   - **overwrite + doesn't exist** → write the full page. Increment `created`.
6. Ensure the parent directory (`$VAULT/concepts/`, etc.) exists before writing.

Unlike the graph.json path, **do not** generate a `## Related` stub section — the bundle body already contains the real cross-links.

## Step 5: Update Vault Metadata

### `.manifest.json`

Add a new entry keyed by the canonical path of the graph.json file:

```json
"<absolute path to source>": {
  "ingested_at": "<ISO timestamp>",
  "source_type": "wiki-export",
  "pages_created": ["list/of/created/pages.md"],
  "pages_updated": ["list/of/merged/pages.md"]
}
```

Set `source_type` to `"wiki-export"` for a graph.json import or `"okf-bundle"` for an OKF bundle import. Key the entry by the absolute path of the source (the `graph.json` file or the bundle directory).

Also increment:
- `stats.total_sources_ingested` by 1
- `stats.total_pages` by the count of pages actually created (not skipped/merged)

If `.manifest.json` doesn't exist, create it with the standard structure:
```json
{
  "stats": {
    "total_sources_ingested": 1,
    "total_pages": <created count>
  },
  "<graph.json path>": { ... }
}
```

### `index.md`

For each **created** or **merged** page:
- Add or update the entry under its category section using the format:
  `- [[<id>]] — <summary or title> ( #tag1 #tag2)`
  (Note: space before `(` — `description ( #tag)` not `description(#tag)`)

Keep categories sorted alphabetically. Create the category section if it doesn't exist.

### `log.md`

Append one line:
```
- [<ISO timestamp>] IMPORT source="<graph.json path>" pages_created=<N> pages_skipped=<K> pages_merged=<M>
```

### `hot.md`

Rewrite the **Recent Activity** section to include this import as the latest entry:
```
- [<timestamp>] IMPORT from <graph.json path> — created X, merged Z pages
```
Update the `updated:` frontmatter timestamp. Leave other hot.md sections (Active Threads, Key Takeaways) intact unless they reference pages that were just created — in which case add brief mentions.

## Step 6: Print Summary

```
Wiki import complete → $OBSIDIAN_VAULT_PATH
  Source:  <source path>  (<graph.json | OKF bundle>)
           <graph: exported at <graph.exported_at>, N nodes, M links | okf: N pages, okf_version <ver>>
  Created: <X> pages
  Merged:  <Z> pages  (existing pages updated)
  Skipped: <Y> pages  (only when --skip mode was used)
```

Only show the `Skipped` line if `skip` mode was explicitly requested. If `overwrite` mode was used, label merged pages as `Replaced` instead. For an OKF import, also report `Unparseable: <U> files (no frontmatter/type, skipped)` when `U > 0`.

## Notes

- **Stub vs full pages**: A **graph.json** import produces stubs — structure and wikilinks but no body, a starting point for future ingestion. An **OKF bundle** import produces full pages with real bodies — it is the lossless, content-bearing path and the right choice for vault-to-vault transfer.
- **Re-running is safe**: The default `merge` mode is idempotent — re-running on an unchanged export will update timestamps but won't destroy content. Use `overwrite` only when you want to fully reset pages to stubs.
- **Directory creation**: Always create missing category directories before writing pages.
- **Broken wikilinks**: Since pages are being created together from the same export, most links will resolve. Any node referenced in `links` but absent from `nodes` (broken in the original export) will still appear as a wikilink — it just won't have a corresponding page file, which is valid.
- **Filtered exports**: If the source `graph.json` was produced with visibility filtering (noted in `graph.metadata`), imported pages will only reflect the filtered set. Note this in the summary if `graph.graph` contains a `filtered` key.
