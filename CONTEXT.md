# LLM Wiki provenance

Terms for what a wiki page is allowed to cite as the thing it was distilled from.

## Language

**Snapshot**:
The immutable file under `_raw/_archived/` that ingest actually read.
_Avoid_: raw file, clip, original, source document (when those mean the live webpage)

**`snapshots:`**:
Page frontmatter listing archived snapshot paths (vault-relative; quoted wikilinks for Obsidian Properties). Distill provenance when a file was read. **Optional** — not in `REQUIRED_FRONTMATTER`. `/ingest-url` with no file, hand-written pages, and empty **resolved** invert omit it. When resolved invert is non-empty, lint may **warn** if the field is missing or disagrees (not fail). Writers emit a YAML **block list** of `"[[_raw/_archived/…|title]]"` (no `.md` in the target; `title` is the archive basename). `snapshots set` **unions**; `snapshots apply --apply` **replaces** from lint `expected`.
_Avoid_: raw_sources, treating `sources:` URLs as the snapshot; writing `snapshots: [[…]]` as a flow list

**Ledger**:
The vault `.manifest.json` map from source key to the pages ingest recorded as produced from it.
_Avoid_: cache, manifest (as a synonym in conversation — the file is `.manifest.json`; the concept is the ledger)

**Origin URL**:
The webpage a snapshot was clipped from. Metadata on the snapshot, not a distill source once a snapshot exists.
_Avoid_: source URL, canonical URL (when used as if it were `sources:`)

**`sources:`**:
The append-on-ingest portable-key list (path, `url:`, `projects/<name>`, `agent:<agent>/<id>`, bibliography). Contract v2. Origin or citation — including live URLs — not the archived file. Untouched by snapshot lint/apply.
_Avoid_: calling this the snapshot; fake (URLs are real origin metadata; they are not the distill file)

**Union cite**:
The set of ledger keys whose `pages_produced` or `pages_created` lists a given page. Expected `snapshots:` membership after resolving unique `url:` → archive and stale `_raw/<name>` → `_raw/_archived/<name>` (basename prefer is for **lint compare** and stale staging keys, not for flattening nested archives the writer already stored).
_Avoid_: URL pairing, rewriting `sources:`, size threshold

**Reverse index**:
The page-keyed view of the ledger: wiki page path → union cite. The ledger file itself stays source-keyed.
_Avoid_: reindexing the wiki, citations.json

**Index helper**:
The reverse-index pass inside `lint_vault()` (warn finding vs `snapshots:`). It does not edit wiki pages or the ledger.
_Avoid_: a one-off skill script

**Consulted list**:
A research-synthesis body section (`## Sources Consulted`) of wikilinks to wiki `references/` pages. It is a map of those pages, not origin URLs.
_Avoid_: Sources section, source footer

**Write key**:
The ledger key `cache-update` stores. After a raw ingest move, this is the archived snapshot path; the hash is of that archived file (ADR 0003). Not required for `snapshots:` lint.
