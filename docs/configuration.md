# Configuration

## How config is resolved

Skills resolve the vault path in this order:

0. **Inline vault override (`@name`)** — an `@<name>` token anywhere in a request resolves `<config dir>/config.<name>` directly, overriding everything below, **for that request only**.
1. **Walk up from CWD** — look for a `.env` in the current directory, then each parent, up to `$HOME`. Stop at the first one containing `OBSIDIAN_VAULT_PATH`.
2. **Global config** — `<config dir>/config`.
3. **Prompt setup** — if neither exists, you'll be told to run setup.

### Where the global config lives

The config directory follows the [XDG Base Directory spec](https://specifications.freedesktop.org/basedir-spec/latest/): `$XDG_CONFIG_HOME/obsidian-wiki`, which defaults to `~/.config/obsidian-wiki`.

Earlier versions used `~/.obsidian-wiki`. That location is still honored: if `~/.obsidian-wiki` exists and the XDG path does not, it is used as-is — upgrading never strands a working config, and no migration is required. New installs use the XDG path. To move an existing install, `mv ~/.obsidian-wiki ~/.config/obsidian-wiki`.

After resolving, skills also read `$OBSIDIAN_VAULT_PATH/AGENTS.md` if it exists. That's where you put owner-specific conventions — domain vocabulary, ingest preferences, writing style, project scoping — which override framework defaults for every skill.

## Global wiki writing profile

Setup creates a global `WRITING.md` profile for preferences that should apply across projects. New installs use `~/.config/obsidian-wiki/WRITING.md`. When the legacy `~/.obsidian-wiki` directory is active, the profile is `~/.obsidian-wiki/WRITING.md` instead.

Start with a small profile and edit it to suit your habits:

```markdown
## Language

Write in English. Keep technical terms in their original form.

## Tone and Voice

Be clear, concise, and practical.

## Avoid

Avoid filler, repetition, and unsupported claims.
```

Writing preferences are applied in this order, from highest to lowest precedence: framework and task requirements, project `AGENTS.md`, vault `AGENTS.md`, then global `WRITING.md`. The global profile guides wiki Markdown prose only. It does not change lint rules or create blocking behavior.

If the profile is missing, empty, or unreadable, skills fall back to the framework defaults and continue without custom global preferences.

Both the global config and `.env` use the same `KEY=value` format. Start from [`.env.example`](../.env.example).

The deterministic `lint`, `trust-record`, and `trust-check` commands use the same vault-scoped resolution: an explicit path uses no unrelated config, `@name` reads only `<config dir>/config.<name>`, otherwise the nearest CWD `.env` wins before global config. Schema settings are read from that same resolved config only, so one vault's lifecycle extensions cannot leak into another vault.

## Core

| Variable | What it does | Default |
|---|---|---|
| `OBSIDIAN_VAULT_PATH` | **Required.** Absolute path to your vault | — |
| `OBSIDIAN_WIKI_REPO` | Where this repo is cloned (set by setup; used for skill/asset lookups) | *auto* |
| `OBSIDIAN_SOURCES_DIR` | Comma-separated source directories to ingest documents from | *(empty)* |
| `OBSIDIAN_CATEGORIES` | Wiki page categories (directories created in the vault) | `concepts,entities,skills,references,synthesis,journal` |
| `OBSIDIAN_MAX_PAGES_PER_INGEST` | Max pages created or updated per ingest | `15` |
| `OBSIDIAN_LINK_FORMAT` | `wikilink` → `[[concepts/foo]]`, or `markdown` → `` [text](path.md) ``. Affects future writes only — existing content is never migrated | `wikilink` |
| `OBSIDIAN_RAW_DIR` | Staging directory inside the vault for unprocessed drafts | `_raw` |
| `LINT_SCHEDULE` | Health-check frequency: `daily` \| `weekly` \| `manual` | `weekly` |

Local git repo clones work in `OBSIDIAN_SOURCES_DIR` (public or private, any host). Clone locally, then add the path. Repo directories are auto-detected via a `.git` folder and enumerated with `git ls-files`, so whatever the repo's own `.gitignore` excludes — `node_modules`, build output, venvs, secrets — is skipped automatically rather than relying on a hardcoded skip-list.

## History ingest

| Variable | What it does | Default |
|---|---|---|
| `CLAUDE_HISTORY_PATH` | Where to find Claude data | *auto-discovers from `~/.claude`* |
| `CODEX_HISTORY_PATH` | Where to find Codex data | `~/.codex` |
| `HERMES_HISTORY_PATH` | Where to find Hermes data | `~/.hermes` |
| `OPENCLAW_HISTORY_PATH` | Where to find OpenClaw data | `~/.openclaw` |
| `COPILOT_HISTORY_PATH` | Where to find Copilot CLI data | `~/.copilot/session-state` |
| `PI_HISTORY_PATH` | Where to find Pi sessions | `~/.pi/agent/sessions` |
| `WIKI_SKIP_PROJECTS` | Comma-separated substrings; project dirs matching any are skipped during scan, delta, and manifest steps. e.g. `archived,scratch,sandbox` | *(empty)* |
| `WIKI_SESSION_BRAIN_DIR` | Where the session-brain sidecar is written | `~/.claude/session-brain` |

## Staged writes & trust

| Variable | What it does | Default |
|---|---|---|
| `WIKI_STAGED_WRITES` | When `true`, LLM-written pages land in `_staging/` for human review instead of the live vault. Promote them with `/wiki-stage-commit` | *(unset — direct writes)* |
| `OBSIDIAN_TRUST_STRICT` | When `1`, `obsidian-wiki lint` treats missing trust fields, ledger errors, stale reviews, and score mismatches as failures rather than warnings. Same as `lint --strict-trust` | *(unset)* |
| `OBSIDIAN_ALLOWED_LIFECYCLES` | Comma-separated lifecycle extensions for this resolved vault | *(framework defaults only)* |
| `OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES` | Comma-separated relationship-type extensions for this resolved vault | *(framework defaults only)* |
| `OBSIDIAN_REQUIRED_TRUST_FIELDS` | Comma-separated effective required trust fields. Allowed values: `base_confidence`, `lifecycle`, `lifecycle_changed`, `updated`; unknown values fail closed | `base_confidence,lifecycle` for lint; also `updated` for standalone trust commands |
| `OBSIDIAN_SCHEMA_SOURCE` | Owner authority locator emitted in machine reports | `config:<resolved-config-path>` when overrides exist |

Schema resolution precedence is CLI flags > resolved environment/config values > framework defaults. Lifecycle and relationship-type extension lists are additive to framework defaults; CLI required-field values replace environment requiredness. CLI-only schema overrides use a `cli:<context>` source label rather than claiming a config-file provenance. If CLI and resolved config both contribute overrides, reports use `cli+config:<resolved-config-path>` unless `--schema-source` or `OBSIDIAN_SCHEMA_SOURCE` supplies the owner authority explicitly.

The four schema variables are `OBSIDIAN_ALLOWED_LIFECYCLES`, `OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES`, `OBSIDIAN_REQUIRED_TRUST_FIELDS`, and `OBSIDIAN_SCHEMA_SOURCE`. When any is present, its value and every comma-separated entry must be non-empty after trimming whitespace. Empty values, repeated commas, and trailing commas fail closed with exit 1; remove the variable entirely to use framework defaults. The distributable `.env.example` documents safe commented examples for all four.

Staged pages aren't visible in Obsidian's graph until promoted. `wiki-status` lists pending staged writes first when this mode is on — the work is done, it just needs your eyes. The `_staging/` directory is created at setup even when the mode is off.

## Vault Skill Factory

`vault-skill-factory` turns mature curated pages into portable Agent Skills. Generated skills land in a **review directory** — never auto-installed, never written into `.skills/`.

| Variable | What it does | Default |
|---|---|---|
| `SKILL_FACTORY_OUTPUT_DIR` | Where generated skills are written | `<vault>/_generated-skills` |
| `SKILL_FACTORY_MATURITY` | Which lifecycle states count as mature enough to harvest (pages with `tier: core` also qualify) | `reviewed,verified` |

## PageIndex (optional, long PDFs)

For long PDFs — books, reports — PageIndex builds a table-of-contents tree (section titles, summaries, page ranges) before ingest, so the agent reads only the relevant sections. Without it, `wiki-ingest` reads PDFs directly.

Install: clone [PageIndex](https://github.com/VectifyAI/PageIndex), create a venv, and put an LLM key in its `.env` (LiteLLM). See `.skills/wiki-ingest/references/pageindex.md`.

| Variable | What it does | Default |
|---|---|---|
| `PAGEINDEX_REPO` | Path to the PageIndex repo — setting this enables the long-PDF branch | *(empty — disabled)* |
| `PAGEINDEX_MODEL` | LiteLLM model id PageIndex uses | `openai/glm-4.6` |
| `PAGEINDEX_MIN_PAGES` | Only preprocess PDFs with at least this many pages | `30` |
| `PAGEINDEX_WORKSPACE` | Cache dir for `*_structure.json` | `<PAGEINDEX_REPO>/results` |

## QMD semantic search (optional)

By default, `wiki-ingest` and `wiki-query` use Grep/Glob — fully functional, no extra setup. If your vault grows large or you want concept-level matches across your sources, plug in [QMD](https://github.com/tobi/qmd), either through MCP or by letting the agent call the local `qmd` CLI.

| Variable | What it does | Default |
|---|---|---|
| `QMD_WIKI_COLLECTION` | Collection indexing your compiled wiki pages — used by `wiki-query` | *(empty — disabled)* |
| `QMD_PAPERS_COLLECTION` | Collection indexing your raw source documents — used by `wiki-ingest` | *(empty — disabled)* |
| `QMD_TRANSPORT` | `mcp` (agent-configured MCP server) or `cli` (local `qmd` binary) | `mcp` |
| `QMD_CLI_SEARCH_MODE` | `quality` (rerank, best relevance), `balanced` (`--no-rerank`), or `fast` (semantic only) | `quality` |
| `QMD_CLI` | Override the `qmd` binary path if it isn't on `PATH` | `qmd` |

**Setup:**

```bash
qmd collection add /path/to/vault --name my-wiki
qmd collection add /path/to/sources --name papers
```

```env
QMD_WIKI_COLLECTION=my-wiki
QMD_PAPERS_COLLECTION=papers
QMD_TRANSPORT=mcp
QMD_CLI_SEARCH_MODE=quality
```

> **The two collections must stay disjoint.** `wiki-query` treats them as separate layers — compiled knowledge vs. raw staging — and cites them separately. Since `OBSIDIAN_VAULT_PATH` contains `_raw/`, a plain `qmd collection add <vault>` merges the two layers and makes superseded drafts retrievable and citable as though they were compiled pages.
>
> QMD has no `--ignore` flag, so scope the collection by editing `~/.config/qmd/index.yml`:
>
> ```yaml
> collections:
>   my-wiki:
>     path: /path/to/vault
>     pattern: "**/*.md"
>     ignore:
>       - "_raw/**"
>       - "log.md"
> ```
>
> Then run `qmd update`.

**What changes when it's on:**

- `wiki-query` runs a semantic pass (lex+vec) against your wiki collection before falling back to Grep — finds conceptually related pages even when the exact terms don't match.
- `wiki-ingest` queries your papers collection before writing a new page — surfaces related sources, spots contradictions, and decides whether to create a new page or merge into an existing one.

Both degrade gracefully: with the collection names unset, they skip the QMD step silently and use Grep.

## Code understanding (optional)

`wiki-update` distills a project's structure before it writes knowledge into the vault. When a supported code graph backend is available, `wiki-update` uses it to rank the project's most important modules, trace callers and callees, and expand changed files into their impact area before distilling. Without one, the built-in `ast-extract` + `rg` fallback is used — no extra dependency.

Missing CodeGraph never breaks normal `wiki-update` or `doctor` runs. The graph index lives in the project's `.codegraph/` sidecar and is never written into the vault.

| Variable | What it does | Default |
|---|---|---|
| `CODE_UNDERSTANDING_BACKEND` | How `wiki-update` understands project structure: `auto` (CodeGraph when available, else the built-in `ast-extract` + `rg`), `builtin` (always the built-in, dependency-free), or `codegraph` (explicitly require CodeGraph; warn/error if unavailable) | `auto` |
| `CODE_UNDERSTANDING_CODEGRAPH_BIN` | Path to the `codegraph` binary if it isn't on `PATH` | *(empty)* |

Both variables resolve like `OBSIDIAN_VAULT_PATH`: a real environment variable wins (empty counts as unset), then the nearest `.env` walking up from the project directory (stopping at the first one that sets a `CODE_UNDERSTANDING` key), then the global config ([where the global config lives](#where-the-global-config-lives)), then the default.

### Setup (optional)

Install the CodeGraph CLI once to enable the enhanced backend:

```bash
npm install -g @colbymchenry/codegraph
```

**MCP configuration is not required for obsidian-wiki; only the CodeGraph CLI is required.**

Verify with `obsidian-wiki doctor --project .` — the `code-understanding.codegraph` check should flip to pass. If the binary isn't on your `PATH`, set `CODE_UNDERSTANDING_CODEGRAPH_BIN` to its location instead.

- The first enhanced `wiki-update` run auto-initializes the project's `.codegraph/` index; later runs sync only what changed.
- Your agent can run the install for you — just ask it to use CodeGraph when running `/wiki-update`.

## `_raw/` staging directory

`_raw/` is a staging area inside your vault for unprocessed captures — rough notes, clipboard pastes, quick voice-memo transcripts. Drop files there and the next `wiki-ingest` run promotes them to proper wiki pages and removes the originals, so nothing is processed twice.

The fastest way to feed it during a live coding session:

```text
/wiki-capture --quick
```

It scans the current conversation, extracts bugs and gotchas, and writes structured draft files in under 60 seconds — no subagents, no manifest writes.

To promote everything waiting there:

```text
/wiki-ingest promote my raw pages
```

The directory is created automatically by `wiki-setup`. The path is configurable via `OBSIDIAN_RAW_DIR`.

### Browser capture extension

This repo includes a zero-build Chrome extension at [`extensions/brain/`](../extensions/brain/) for saving web pages and selected text straight into `_raw/`, and for filling web forms from the vault.

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select `extensions/brain`

To find your configured `_raw` folder from a clone of this repo:

```bash
awk -F= '/^OBSIDIAN_VAULT_PATH=/{print $2 "/_raw"; exit}' "$(git rev-parse --show-toplevel)/.env"
```

## Syncing your vault to GitHub

Your vault is a directory of plain markdown files — push it to a private GitHub repo and you get version history, backup, and cross-device sync for free. `obsidian-wiki setup` and `setup.sh` both offer to configure this during install; they share one implementation (`obsidian_wiki/sync.py`), so pip and source installs get an identical flow.

**What setup does:**

1. `git init` your vault if it isn't already a repo
2. Creates a `.gitignore` excluding Obsidian workspace/cache files
3. Sets the remote you supply — the vault's own `git remote`, not a config file, is the source of truth for whether sync is configured, so it can't drift
4. Optionally adds a `wiki-sync` shell alias
5. Optionally installs an hourly cron job

**Run a sync at any time:**

```bash
wiki-sync            # alias added by setup
obsidian-wiki sync   # or call it directly
```

Each run stages all changes, commits as `sync 2026-07-30 14:00`, and pushes.

**Configure it later, or by hand:**

```bash
obsidian-wiki sync-setup https://github.com/you/my-wiki.git
# or:
cd /path/to/your/vault
git init
git remote add origin https://github.com/you/my-wiki.git
```

**Hourly auto-sync via cron:**

```
0 * * * * obsidian-wiki sync --vault /path/to/your/vault >> ~/.config/obsidian-wiki/sync.log 2>&1
```

> Keep the repo **private** if your vault contains personal notes. Nothing is sent to any third-party service — your vault lives on your machines and in your GitHub account only.

## Visibility tags (optional)

Pages can carry a `visibility/` tag marking their intended reach. This is **entirely optional** — untagged pages behave exactly as they always have. The system stays single-vault, single source of truth.

| Tag | Meaning |
|---|---|
| *(none)* | Same as `visibility/public` — visible in all modes |
| `visibility/public` | Explicitly public |
| `visibility/internal` | Team-only — excluded in filtered mode |
| `visibility/pii` | Sensitive — excluded in filtered mode |

**Filtered mode** is opt-in, triggered by phrases like "public only", "user-facing answer", "no internal content", or "as a user would see it" in a query. Default mode shows everything.

`visibility/` tags are **system tags** — they don't count toward the 5-tag limit and are listed separately from domain/type tags in the taxonomy.

## Memory server (optional)

Only read by `obsidian_wiki/server.py`, the Dockerized HTTP + MCP front end. Irrelevant to local
skill use. Full guide: [Deployment](deployment.md).

| Variable | What it does | Default |
|---|---|---|
| `WIKI_API_KEY` | Bearer token required on every `/v1/*` and `/mcp` request | *(none — the server refuses to start without it)* |
| `WIKI_ALLOW_ANONYMOUS` | `1` disables auth entirely. Local development only | *(unset)* |
| `WIKI_PORT` | Port the server listens on | `8080` |
