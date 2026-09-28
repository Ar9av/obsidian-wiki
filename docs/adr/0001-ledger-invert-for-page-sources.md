---
status: accepted
---

# Invert the ingest ledger onto optional `snapshots:`, not `sources:`

Wiki page YAML `sources:` stays the **append-on-ingest** portable-key list skills already write (URLs, `url:`, `projects/<name>`, `agent:claude/…`, bibliography). That membership is also on `.manifest.json` as `pages_produced` / `pages_created`. Lint **inverts** those lists in memory onto frontmatter **`snapshots:`** (archived vault paths). That field is **distill provenance** when a file was read. **`snapshots:` is optional** (not in `REQUIRED_FRONTMATTER`; absence is never `fail`). `/ingest-url` with no file keeps provenance in `sources:` (`url:`). If the **resolved** invert is **non-empty**, missing or disagreeing `snapshots:` is a **warn** only (not `--strict`). Resolved invert empty: no finding. Never rewrite `sources:`. No `citations.json`, no cap, no `projects/` collapse. Default lint is report-only. `/wiki-lint` prefers the CLI. Phase 2 writes **only** `snapshots:` via **[ADR 0003](0003-snapshots-write-cli.md)** (`snapshots set` unions; `snapshots apply --from-json` dry-run then `--apply`; not `lint`). Forward ingest should set `snapshots:` when it archived a file. `cache-update` after archive stores and hashes the archived write key.

## Considered Options

- **Rewrite `sources:` to snapshot wikilinks or drop URLs.** Rejected: breaks contract v2, trust fingerprints, OKF `resource` (first `http(s)` in `sources:`), and human citations. Additive `snapshots:` leaves exporters and CI readers of `sources:` alone.
- **Name the field `raw_sources`.** Rejected: “raw” already means Layer 1 and `_raw/` staging.
- **Persist `citations.json`.** Rejected: second source of truth. Invert after `json.load`; prove with a ~10k-key fixture. Gated in-memory `url:` → clip scan once per lint.
- **Standalone skill script / new backfill skill.** Rejected: `lint_vault()` already walks pages; `/wiki-lint` should consume the CLI report when present.
- **Pair YAML `sources:` strings to filenames.** Rejected: those strings are not ledger keys; `snapshots:` membership is invert only.
- **Put `snapshots:` on the `REQUIRED_FRONTMATTER` fail tuple.** Rejected: optional by design. `/ingest-url` with no file has no snapshot; legacy pages must not fail. When invert is non-empty, **warn** (trust-style), never `missing_frontmatter` fail.

## Compatibility

- **Never mutate `sources:`** in lint or apply for this feature.
- **`snapshots:` is optional distill provenance.** Not in `REQUIRED_FRONTMATTER`. Resolved invert empty → no finding. Resolved invert non-empty and field missing or wrong → **warn** only. Do **not** include this finding in `--strict` until an explicit flag exists. Owner/`strict_snapshots` may fail later if they want.
- Invert unions **`pages_produced` and `pages_created`**. Finding shows expected vs actual `snapshots:`; the write CLI (ADR 0003) is opt-in and does not treat the ledger as license to edit `sources:`.
- **`--consolidate` does not apply this finding.** The write CLI is a separate opt-in (ADR 0003); consolidate never grows that opt-in.
- Unique `url:` → archive and stale `_raw/` → `_raw/_archived/` affect **`snapshots:` only**. Lint **compare** may basename-prefer; **writers** keep nested `_archived` paths that exist (ADR 0003).
- Archive wikilinks: an inner path under `_raw/_archived/` is **never** a wiki slug (ADR 0003). Existing file → not `broken_links`, not a graph edge. Missing file → `broken_links` with the vault-relative posix path (`.md` included), never the last segment. Last-segment slug must not attach `[[_raw/_archived/attention]]` to `concepts/attention.md`.
- Prefer CLI; grep fallback if `obsidian-wiki` is missing.
- `CONTEXT.md` is local glossary.

**Phased freeze:** (1) warn when invert is non-empty and `snapshots:` is missing or wrong, 10k fixture (landed); (2) write path, archive-link exception, ingest CLI, and archived `cache-update` key — **[ADR 0003](0003-snapshots-write-cli.md)**.

## Implementation defaults (no further product questions)

These close the leftover review items without another round:

- **Value shape:** vault-relative portable paths (file keys). `[[…]]` wrappers allowed; lint **unwraps** before compare.
- **Finding id:** `snapshot_mismatch` (expected vs actual path sets). Warn only; not in `--strict`. Invert both manifest shapes (dict and list). Union `pages_produced` and `pages_created`.
- **Trust fingerprint:** `snapshots:` is material evidence (true distill provenance). Opt-in writes that *insert* or replace the field will mark reviewed pages **stale**. Do not add it to volatile fingerprint keys. Document that when ADR 0003 ships.
- **Phase 1** does not change ingest `cache-update` keys, skill templates, body `## Sources`, or `--consolidate`.
- **`strict_snapshots`:** not in the first cut.

## Follow-up

Proposed **[ADR 0002](0002-ingest-url-snapshot-then-ingest.md):** `/ingest-url` should save markdown into `_raw/` and ingest as a file so distill provenance is a snapshot, not a mutable URL. Not part of this freeze.

## Documentation

ADRs are not user-facing. When this ships, update **`docs/`** only as far as the change is observable:

- **`docs/cli.md`** — lint report: finding name, warn (not fail / not `--strict`), `snapshots:` vs invert. Write commands live in ADR 0003 (`snapshots set`; `snapshots apply --from-json` dry-run / `--apply`); lint stays read-only.
- **`docs/architecture.md`** — one mention that `snapshots:` (when present) is the page-local ledger projection; `sources:` is unchanged.
- Skill markdown that already documents frontmatter (`llm-wiki`, `wiki-lint`, ingest) — ingest *may* set `snapshots:`; do not recast `sources:`.

Do not add ADRs to `docs/README.md`. No new conceptual guide.

## Consequences

- Linguistics (and similar) get clickable archive pointers without stripping Wikipedia/Foard/`url:` from `sources:`.
- OKF export `resource` and extension round-trip of `snapshots:` are unchanged/safe.
- Hub-page `snapshots:` lists can be large if the ledger stored per-file keys; `sources:` can stay `projects/<name>`.
- Glossary: `CONTEXT.md`.
