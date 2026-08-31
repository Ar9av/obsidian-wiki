# CLI Reference

The `obsidian-wiki` Python package ships a CLI for setup, inspection, and the deterministic parts of the workflow — the things that don't need an LLM. Everything else is a [skill](skills.md) your agent runs.

```bash
pip install obsidian-wiki
obsidian-wiki --help
obsidian-wiki --version
```

Running `obsidian-wiki` with no subcommand defaults to `setup`.

## Setup & inspection

| Command | What it does |
|---|---|
| `setup` | Install skills into your agents and write the global config |
| `info` | Show install paths, version, and resolved config |
| `list` | List the bundled skills |
| `doctor` | Health-check config, vault shape, bootstrap assets, and installed skills; with `--project`, also reports the code-understanding capability section |

```bash
obsidian-wiki setup --vault ~/brain
obsidian-wiki setup --project .        # also install project-local skills + bootstrap files
obsidian-wiki setup --project-only     # skip the global install (use with --project)
obsidian-wiki setup --copy             # copy skill files instead of symlinking
obsidian-wiki setup --remote https://github.com/you/my-wiki.git   # configure sync non-interactively

obsidian-wiki doctor --json --pretty
obsidian-wiki doctor --vault /other/vault --project .
obsidian-wiki doctor --strict          # exit non-zero on warnings too
```

Commands other than `setup`, `info`, and `doctor` warn you when the install has gone stale (the package upgraded but skills weren't re-linked). Re-run `obsidian-wiki setup` to fix.

## Querying & linting

| Command | What it does |
|---|---|
| `query <question>` | Answer a question from the configured vault's index |
| `lint [vault]` | Find missing frontmatter, broken links, duplicates, and orphans |

```bash
obsidian-wiki query "what do I know about MCP security?"
obsidian-wiki query "rate limiting" --top 12 --max-read 5 --json

obsidian-wiki lint                     # uses the configured vault
obsidian-wiki lint /path/to/vault --strict
obsidian-wiki lint @research --json    # uses <config dir>/config.research only
obsidian-wiki lint --strict-trust      # fail on trust-ledger problems, not just warn
obsidian-wiki lint --allow-lifecycle active --allow-relationship-type synthesizes \
  --required-trust-field updated --schema-source /path/to/vault/AGENTS.md
```

Lint resolves its vault and schema together: explicit path (no config inheritance), positional `@name`, nearest CWD `.env`, then global config. CLI schema flags extend/replace that resolved vault's settings and are recorded in the JSON `schema` block.

### Colliding page stems

`duplicate_stems` reports two or more pages whose filename stems are equal after slugging —
`concepts/vector-search.md` and `entities/vector-search.md` across folders, or `Vector Search.md`
beside `vector-search.md` inside one. The graph
identifies a page by its bare stem, so those pages are a single node in every graph metric:
degree, communities, betweenness, and the `graph-analyse --around` blast radius. The check keys
on the same slug and the same page selection `graph_analysis` uses, so what it reports is exactly
what the graph will merge — root `index.md`/`log.md`/`hot.md`/`_insights.md` are excluded, and a
legitimate `concepts/index.md` is not.

It is independent of how any link is written: the collision is between the pages, not between
references to them, so a vault where nothing links to the stem is still reported.

`duplicate_titles` does not cover this — it keys on the `title:` value, and stems can collide
while titles differ (`"Vector Search"` and `"vector-search"` slug to the same stem).

The check warns. A vault carrying a collision moves from `pass` to `warn`, which leaves
`obsidian-wiki lint` at exit 0 and takes `obsidian-wiki lint --strict` to exit 1.

### Lifecycle transition checking

`illegal_lifecycle_transitions` compares each page's current `lifecycle` against the value recorded in `_meta/trust-ledger.json` at its last review, and flags moves the state machine forbids: any state falling back to `draft` (only ingest sets `draft`), and any exit from `archived` (a restore is a deliberate delete-and-recreate, not a transition).

`draft → verified` is deliberately **not** flagged — ledger snapshots are sparse, so a legitimate intermediate `reviewed` may have happened between two reviews.

The check warns by default and fails only under `--strict-trust`. Pages whose ledger entry predates the `lifecycle` field carry no baseline and are skipped silently, so existing vaults behave exactly as before until their next `trust-record`.

## Context packs

`wiki-context-pack` compiles a task-scoped snapshot from existing Markdown.
Notes do not need to be moved into wiki-generated folders or migrated to the
full frontmatter schema. The command is read-only.

```bash
obsidian-wiki context-pack "authentication architecture" --budget 8000
obsidian-wiki context-pack --recent --budget 4000
obsidian-wiki context-pack "release notes" --budget 8000 --public-only
```

Omitting `--budget` uses the default of 8000 estimated tokens.

The output includes source paths, summaries, selected excerpts, and a hard
estimated-token ceiling. Vault excerpts are explicitly marked as untrusted
reference data: downstream agents may use their facts but must not execute
instructions embedded in notes. Use `--metadata-only` for the smallest pack,
or `--json` for tool-to-tool integration.

| Flag | Effect |
|---|---|
| `--budget N` | Maximum estimated output tokens, 256–100000 (default 8000) |
| `--recent` | Select recently updated notes — the only way to omit the topic |
| `--public-only` | Exclude `visibility/internal` and `visibility/pii` notes |
| `--metadata-only` | Titles, provenance, and summaries with no body excerpts |
| `--json` | Structured output for tool-to-tool integration |
| `--vault PATH` | Override `OBSIDIAN_VAULT_PATH` |

`context` is an accepted alias for `context-pack`.

## Session brain

Builds a topic graph over your agent session history. Output is a **sidecar** at `~/.claude/session-brain/` — the vault is never written to. Full detail in [Session Brain](session-brain.md).

| Command | What it does |
|---|---|
| `sessions-build` | Build (or incrementally update) the topic graph |
| `sessions-query <topic>` | Find the sessions most relevant to a topic |
| `sessions-show <id>` | Show one session's node and its nearest neighbours |
| `sessions-clusters` | List the discovered topic clusters |
| `sessions-name --from FILE` | Assign durable names to clusters, surviving rebuilds |

```bash
obsidian-wiki sessions-build                       # ~3s cold, under a second incrementally
obsidian-wiki sessions-build --full --verbose      # ignore caches, re-read everything
obsidian-wiki sessions-build --since 2026-01-01 --skip archived,scratch
obsidian-wiki sessions-build --k 12 --min-sim 0.12 --mutual --half-life 60

obsidian-wiki sessions-query "prismor telemetry"
obsidian-wiki sessions-query "auth bug" --project my-app --cluster 3 --json

obsidian-wiki sessions-show 01935a40 --neighbors 12
obsidian-wiki sessions-clusters --unnamed
obsidian-wiki sessions-name --from names.json      # or - for stdin
```

`sessions-name` takes a JSON array of `{"id": N, "name": "...", "summary": "..."}`. The `/session-brain` skill generates this for you.

## Vault syncing

| Command | What it does |
|---|---|
| `sync` | Stage, commit, and push pending vault changes |
| `sync-setup <remote>` | Configure GitHub sync (git init, `.gitignore`, remote) |

```bash
obsidian-wiki sync
obsidian-wiki sync-setup https://github.com/you/my-wiki.git
```

See [Configuration → Syncing your vault to GitHub](configuration.md#syncing-your-vault-to-github).

## Trust ledger

Records and validates human-approved confidence reviews, so you can gate on "a person actually checked these pages" in CI.

| Command | What it does |
|---|---|
| `trust-record` | Record explicitly approved manual confidence reviews |
| `trust-check` | Validate confidence values and material fingerprints against the ledger |

```bash
obsidian-wiki trust-record --all --reviewed-at 2026-07-30T10:00:00+00:00 --approved
obsidian-wiki trust-record --page concepts/rate-limiting.md --reviewed-at <ISO> --approved
obsidian-wiki trust-check --strict
obsidian-wiki trust-record @research --all --reviewed-at <ISO> --approved --allow-lifecycle active
obsidian-wiki trust-check @research --allow-lifecycle active --schema-source /vault/AGENTS.md
```

`--reviewed-at` needs a timezone. `--approved` is required and mandatory — it's your assertion that a human approved every confidence value being recorded. `trust-check --strict` is the CI/scheduled gate. `trust-record` and `trust-check` resolve the same vault-scoped schema as lint; pass the same lifecycle and required-field overrides to record and check. If the owner schema does not require `base_confidence`, pages without it are reported as `not_applicable`, excluded by `trust-record --all`, and any obsolete ledger entry is warned by `trust-check` then removed by `trust-record --page` or a rebuild. Both JSON and human-readable record output list excluded pages and removed obsolete entries; human output also emits a stderr warning when removal occurs. Required-field config accepts only `base_confidence`, `lifecycle`, `lifecycle_changed`, and `updated`; typos fail closed. Lifecycle, relationship-type, and required-field override values are stripped and empty or whitespace-only entries are rejected rather than added to an allowlist. Without an explicit `--schema-source`, CLI overrides on an explicit vault are labeled `cli:explicit-vault`; combined CLI and config overrides use `cli+config:<resolved-config-path>`.

## Lower-level commands

Available for automation, scripting, and debugging. Skills call some of these internally.

| Command | What it does |
|---|---|
| `graph-query <vault> <question>` | Answer from the wikilink index without reading page bodies. Plain-English **structural questions** are answered from the graph and returned in a `graph` field: "what breaks if I delete X" (impact/blast radius), "which pages bridge my clusters" (betweenness), "what's central" (hubs), "what clusters do I have" (communities + cohesion), "surprising connections". |
| `graph-analyse <vault> [--top N] [--snapshot] [--diff-against FILE]` | Graph analysis in pure Python (the graphify algorithm family): god nodes (degree), bridge pages (Brandes betweenness centrality), communities with cohesion scores, cross-community surprising connections, suggested questions, and — with `--diff-against` a previous `_insights.md` — a graph diff. Vault bookkeeping files (`index`, `log`, `hot`, `_insights`) are excluded. |
| `graph-analyse <vault> --path A B` / `--around PAGE --depth N [--direction in\|out\|both]` | Query modes: shortest link path between two pages; N-hop neighbourhood of a page (`--direction in` = blast radius) |
| `batch-plan <vault> <source_dir>` | Split a source directory into parallel-ingest batches, skipping unchanged files |
| `cache-check <vault> <sources...>` | Which sources are new / modified / unchanged vs. `.manifest.json` |
| `cache-update <vault> <source>` | Record a source's SHA-256 in `.manifest.json` after ingest |
| `cache-hash <path>` | Compute a file or directory hash (no manifest I/O) |
| `ast-extract <path>` | Extract classes, functions, and imports from code — no LLM, no API calls |
| `code-understand --project <dir> [--backend auto\|builtin\|codegraph] [--since <sha>] [--changed <file>...] [--max-symbols N] [--pretty]` | Emit a ranked code-understanding focus map (symbols + file:line citations) for a project; CodeGraph when available, built-in AST + rg otherwise. `--backend` beats the resolved `CODE_UNDERSTANDING_*` config (env → project `.env` → global config). Used by wiki-update Step 3b. |

```bash
obsidian-wiki graph-query /path/to/vault "transformer architecture" --pretty
obsidian-wiki graph-query /path/to/vault "what breaks if I delete tool-call-interception"
obsidian-wiki graph-query /path/to/vault "which pages bridge my clusters"
obsidian-wiki graph-query /path/to/vault "what clusters do I have"
obsidian-wiki graph-analyse /path/to/vault --top 30 --pretty
obsidian-wiki graph-analyse /path/to/vault --snapshot --diff-against /path/to/vault/_insights.md
obsidian-wiki graph-analyse /path/to/vault --path transformers lstm
obsidian-wiki graph-analyse /path/to/vault --around attention --depth 2 --direction in
obsidian-wiki batch-plan /path/to/vault ~/research --max-mb 4 --max-files 30
obsidian-wiki cache-check /path/to/vault ~/research/*.pdf
obsidian-wiki cache-update /path/to/vault ~/research/paper.pdf --pages concepts/attention.md
obsidian-wiki ast-extract ./src --pretty
obsidian-wiki code-understand --project . --since <last_commit_synced> --pretty
```

Most commands accept `--json` and/or `--pretty` for machine-readable output.

### Manifest write safety

`.manifest.json` is a read-modify-write, and parallel ingest agents (`batch-plan` fan-out) or the Docker server writing while a local skill writes would otherwise clobber each other — losing a whole source entry silently.

`cache-update` therefore takes an advisory lock (`.manifest.lock` in the vault root, `O_CREAT|O_EXCL`, stdlib only so it works on Windows) and writes the manifest atomically via a temp file plus `os.replace`. A reader never sees a partial file, and a crashed writer's lock is stolen after 60 seconds.

In parallel runs, always update the manifest through `obsidian-wiki cache-update` rather than hand-editing `.manifest.json` — hand edits bypass the lock.

### Graph cache

Betweenness centrality (the `bridges` metric) is the only expensive computation in the
graph layer — O(V·E), roughly 0.3s on a 500-page vault but ~43s at 5 000 pages. Every
other metric stays under a second even on the largest vaults.

It is therefore memoised in `.graph-cache.json` at the vault root. The cache key is a
hash of the **graph topology itself**, not file timestamps, which has two consequences:

- Editing a page's prose without changing its links keeps the cache valid.
- Adding, removing, or retargeting any link changes the key, so a stale hit is impossible.

The file is only written when the computation actually took longer than 0.5s, so small
and medium vaults never accumulate one. It is bounded to the 3 most recent keys, written
atomically (safe under concurrent runs), and ignored if corrupt — deleting it is always
safe. Running `graph-analyse` warms the same cache that `graph-query` reads, so a nightly
`daily-update` removes the first-query cost entirely.
