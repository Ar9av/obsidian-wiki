---
status: accepted
---

# Write `snapshots:` through `obsidian-wiki snapshots`, not `lint`

[ADR 0001](0001-ledger-invert-for-page-sources.md) Phase 1 is report-only: `lint_vault()` warns `snapshot_mismatch` when the **resolved** invert is non-empty and `snapshots:` is missing or wrong. It **does not write pages**. Phase 2 keeps that contract. Opt-in writes go to a **`snapshots` subcommand**. Skills and `/wiki-lint` call the CLI; they do not import Python. One serializer owns YAML. Never rewrite `sources:`. `--consolidate` does not apply this finding (no later opt-in on consolidate). `strict_snapshots` and [ADR 0002](0002-ingest-url-snapshot-then-ingest.md) stay out.

Unresolved ledger keys (`agent:`, ambiguous `url:`) are not findings and are not written.

## Commands

`PAGE` is a vault-relative wiki path, the same string as `findings.snapshot_mismatch[].page` (e.g. `concepts/foo.md`).

- **`obsidian-wiki snapshots set PAGE --archive PATH…`** — forward ingest. Prefer each `PATH` (keep nested `_archived` if it exists; basename-prefer only for stale `_raw/<name>.md` when the flat archive exists). After prefer, each result **must** be an existing file under `_raw/_archived/` (nested dirs OK). Reject the whole command (no write) if any path is missing, or if prefer would store a live staging path (`_raw/<name>.md` with no archive). **Union** those archives into the page’s current `snapshots:` (do not drop prior archives). Then write the combined set.
- **`obsidian-wiki snapshots apply --from-json FILE|-`** — backfill. Default is **dry-run** (print pages and the `snapshots:` that would be written; exit 0; no files changed). **`--apply`** performs writes. Read **only** `findings.snapshot_mismatch`. For each row, **replace** `snapshots:` with that row’s `expected` set (extras not in invert are dropped so the finding can clear). Lint JSON has no vault field; `--vault` / config is the tree. Each `page` must be an existing file under that tree; otherwise error, no further writes. Empty `expected`: skip that row (do not delete the field). Pages lint does not list are not touched.
- **`obsidian-wiki lint`** — remains read-only. No `--apply-snapshots`. `--strict` still ignores `snapshot_mismatch` alone (0001).

Writer (both commands): vault-relative archive paths, **block list only**, each item a **quoted** wikilink. Obsidian Properties only treats `[[…]]` as internal links ([Properties](https://help.obsidian.md/properties)); Markdown `[title](path)` stays plain text. The wikilink target has **no** `.md`; `|title` is the archive basename so Properties does not show `_raw/_archived/`:

```yaml
snapshots:
  - "[[_raw/_archived/foo|foo]]"
```

Unquoted `[[…]]` is a YAML flow sequence (nested lists). Quotes make a string so Properties can treat the list as links. Lint unwraps `|alias`, legacy `"[[_raw/_archived/foo]]"`, and leftover markdown `[title](path)` items.

Lint unwraps and may append `.md` before compare when the path has no suffix. Never write a scalar/flow `snapshots: [[…]]` — `parse_snapshots_field` treats a first line starting with `[` as a flow list and will not round-trip.

Path prefer (writers and `cache-update` key, **not** a flatten of nested archives): if the operator path already contains `_archived` and that file exists, **keep it**. Basename prefer (`_raw/_archived/<name>`) only when the CLI path is a stale `_raw/<name>.md` and the flat archived file exists.

`cache-update` stays **manifest-only**. Hash **after** prefer (the staging path may be gone). When prefer changes `_raw/<name>.md` → `_raw/_archived/<name>.md`, re-key that entry **without** `--key`, for **both** manifest `sources` shapes (dict keyed by path, and the ingest list of `{path: …}` objects). Do not broadly re-key other portable paths. CLI JSON `"key"` is the **stored** archive key, not `stored_key(staging)`. Skills should pass the archived filesystem path.

## Archive wikilinks are not wiki edges

`_WIKILINK_RE` scans the whole page, including YAML. `_wikilink_page_target` currently keeps the **last path segment**, so `[[_raw/_archived/attention]]` becomes slug `attention` and can attach to `concepts/attention.md`.

Before stem collapse, if the wikilink inner path (alias/`#` stripped, `.md` optional) is **archive-shaped** — vault-relative parts start with `_raw`, `_archived` — it is **never** a wiki slug, whether or not the file exists. Existing archive file: not `broken_links`, not a graph edge. Missing archive file: still not a graph edge; lint `broken_links` target is the posix relpath with `.md` (e.g. `_raw/_archived/ghost.md`), never the last segment. Share one helper; call it from every in-tree `_WIKILINK_RE` that scans full page text (`lint.py`, `graph_analysis.py`, `graphrag.py`, `memory.py`).

## Considered Options

- **`lint --apply-snapshots`.** Rejected: `lint` is report-only.
- **`apply --from-json` writes immediately.** Rejected: same blast radius as a lint write flag. Dry-run default; `--apply` to mutate (same pattern as `memory migrate`).
- **`set` replaces with only `--archive`.** Rejected: a second file ingest would drop the first snapshot. `set` unions; **`apply --apply` still replaces** from invert.
- **Importable helper for skills.** Rejected: skills already use CLI.
- **Fold page YAML into `cache-update`.** Rejected: manifest lock ≠ page I/O.
- **Bare paths in `snapshots:`.** Rejected: clickable archives. Writer emits quoted `"[[path|title]]"`; path-aware skip above.
- **Union extras on `apply`.** Rejected: replace with `expected` so `snapshot_mismatch` clears.
- **Copy lint basename-flatten into writers.** Rejected: nested `_raw/_archived/topic/clip.md` must not become `_raw/_archived/clip.md` when a flat namesake exists.
- **Vault field on lint JSON.** Rejected: no such field. Fail if `page` is not a file under the CLI vault.
- **Unquoted `  - [[path]]` list items.** Rejected: YAML parses `[[…]]` as nested flow sequences; Obsidian Properties shows an unknown type, not links. Writer quotes each item.
- **Quoted `[[_raw/_archived/foo]]` in `snapshots:`.** Properties shows the full archive prefix. Writer emits `"[[_raw/_archived/foo|foo]]"` so the link is native and the label is the basename. Unwrap still reads the unaliased form and leftover markdown `[title](path)`.
- **Markdown `[title](path)` in `snapshots:`.** Rejected: Properties does not render Markdown; values stay unclickable text.
- **Skip archive wikilinks only when the file exists.** Rejected: a missing `[[_raw/_archived/attention]]` would still stem-collapse to `concepts/attention.md`. Archive-shaped inners are never wiki slugs.
- **`set` writing a live `_raw/<name>.md` when the archive is absent.** Rejected: `snapshots:` stores archive paths only. Staging-only paths fail the command.

## Compatibility

- **Never mutate `sources:`** or the page body.
- **`snapshots:` stays optional** and material for trust fingerprints (not volatile). Writes that change bytes **stale** reviewed pages; document on the CLI. Do not auto `trust-record`.
- Unusable JSON (parse error, missing `findings`) → non-zero, **no writes**. After `--apply` starts, **no rollback**: stop on first write error (`OSError` or missing-frontmatter `ValueError`), print pages already written, remaining mismatches stay for the next lint.
- Shared write module (invert stays in `provenance.py`). Both CLIs call it.
- Skill templates (`wiki-ingest` / `llm-wiki`): after a file was archived, `snapshots set` then `cache-update` on the archived path. `/wiki-lint` may dry-run `snapshots apply --from-json` and only pass `--apply` with explicit user confirmation; **`--consolidate` does not**.

## Documentation

When this ships, update observable `docs/` only: `docs/cli.md` (commands, dry-run/`--apply`, trust stale, lint still read-only, `--strict` unchanged); `docs/architecture.md` if the write path needs one sentence; ingest and wiki-lint skill markdown. No ADR list in `docs/README.md`.
