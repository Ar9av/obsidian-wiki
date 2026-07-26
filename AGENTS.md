# Obsidian Wiki — Agent Context

A **skill-based framework** for building and maintaining an Obsidian knowledge base. No scripts or dependencies — everything is markdown instructions that you execute directly.

## README Translation Parity

`README.md` and `README_TW.md` are one documentation surface. Keep headings, examples, links, and user-facing behavior aligned between the two translations. The check is advisory and never blocks a PR: the `readme-translation-drift` CI job only reports drift. Run `python tools/check_readme_sync.py` to list commits that changed `README.md` without a later `README_TW.md` update, along with the pending English diff — then translate and backfill those changes into `README_TW.md`. Reviewers assess translation quality.

## Configuration

Resolve config using the Config Resolution Protocol in `llm-wiki/SKILL.md`:

0. **Inline vault override (`@name`)** — if the request contains an `@<name>` token, resolve `~/.obsidian-wiki/config.<name>` directly, overriding the steps below. See "Targeting a specific vault" right after this list.
1. **Walk up from CWD** — look for a `.env` file in the current directory, then each parent, up to `$HOME`. Stop at the first `.env` that contains `OBSIDIAN_VAULT_PATH`.
2. **Global config** — if no local `.env` is found, read `~/.obsidian-wiki/config`.
3. **Prompt setup** — if neither exists, tell the user to run `wiki-setup`.

The resolved config sets `OBSIDIAN_VAULT_PATH` (where the wiki lives). It may also set `OBSIDIAN_WIKI_REPO` (where this repo is cloned) and other optional variables.

### Targeting a specific vault

You can maintain multiple vaults (each a `~/.obsidian-wiki/config.<name>` file managed by `wiki-switch`) and reach any of them from any directory:

- **`@name` (per-invocation override)** — prefix or mention `@<name>` anywhere in a request to route that one command to that vault, e.g. `@work save this` or `wiki-query @personal what do I know about X`. It overrides the CWD `.env` and the active symlink **for that invocation only** — it does **not** flip your default vault. If `config.<name>` doesn't exist, the skill reports it and lists available vaults; do **not** silently fall back to the default. The `@name` is stripped before the rest of the request is used as content.
- **`/wiki-switch <name>` (persistent default)** — re-points the active symlink so all future requests use that vault. This is your default "brain" vault; use `@name` to dip into the other one without switching.

**After reading config, always read `$OBSIDIAN_VAULT_PATH/AGENTS.md` if it exists.** It contains owner-specific conventions (domain vocabulary, ingest preferences, writing style, project scoping) that override framework defaults for all skills. Apply it for the duration of the session.

## Vault Structure

```
$OBSIDIAN_VAULT_PATH/
├── index.md                # Master index — every page listed, always kept current
├── log.md                  # Chronological activity log (ingests, updates, lints)
├── hot.md                  # Session hot cache — ~500-word semantic snapshot of recent activity
├── .manifest.json          # Tracks every ingested source: path, timestamps, pages produced
├── _meta/
│   ├── taxonomy.md         # Controlled tag vocabulary
│   └── *.base              # Obsidian Bases dashboard definitions (wiki-dashboard skill)
├── _insights.md            # Graph analysis output (hubs, bridges, dead ends)
├── _raw/                   # Staging area — drop rough notes here, next ingest promotes them
├── _readouts/              # Derived narrative readouts saved by wiki-narrate — not knowledge pages
├── concepts/               # Abstract ideas, patterns, mental models
├── entities/               # Concrete things — people, tools, libraries, companies
├── skills/                 # How-to knowledge, techniques, procedures
├── references/             # Factual lookups — specs, APIs, configs
├── synthesis/              # Cross-cutting analysis connecting multiple concepts
├── journal/                # Time-bound entries — daily logs, session notes
└── projects/
    └── <project-name>.md   # One page per project synced via wiki-update
```

Every wiki page has required frontmatter: `title`, `category`, `tags`, `sources`, `created`, `updated`. Pages connect via internal links — `[[wikilinks]]` by default, or standard Markdown links when `OBSIDIAN_LINK_FORMAT=markdown` is set in config.

## Skill Routing

Skills live in `.skills/<name>/SKILL.md`. Match the user's intent to the right skill:

| User says something like… | Skill |
|---|---|
| "set up my wiki" / "initialize" | `wiki-setup` |
| "/wiki-history-ingest claude" / "/wiki-history-ingest codex" / "/wiki-history-ingest hermes" / "/wiki-history-ingest pi" | `wiki-history-ingest` |
| "ingest" / "add this to the wiki" / "process these docs" / "process this export" / "ingest this data" / logs, transcripts / "/ingest-url <url>" / "add this URL" / "ingest this link" / "save this page" | `wiki-ingest` |
| "import my Claude history" / "mine my conversations" | `claude-history-ingest` |
| "import my Codex history" / "mine my Codex sessions" | `codex-history-ingest` |
| "import my Hermes history" / "mine my Hermes memories" / "ingest ~/.hermes" | `hermes-history-ingest` |
| "import my OpenClaw history" / "mine my OpenClaw sessions" / "ingest ~/.openclaw" | `openclaw-history-ingest` |
| "import my Copilot history" / "mine my Copilot sessions" / "ingest ~/.copilot" | `copilot-history-ingest` |
| "import my Pi history" / "mine my Pi sessions" / "ingest ~/.pi" | `pi-history-ingest` |
| "what's the status" / "what's been ingested" / "show the delta" | `wiki-status` |
| "wiki insights" / "hubs" / "wiki structure" | `wiki-status` (insights mode) |
| "what do I know about X" / "find info on Y" / any question | `wiki-query` |
| "narrate" / "briefing" / "explain this topic" / "/wiki-narrate" | `wiki-narrate` |
| "audit" / "lint" / "find broken links" / "wiki health" | `wiki-lint` |
| "dedup my wiki" / "find duplicate pages" / "merge duplicates" / "identity resolution" / "consolidate my wiki" | `wiki-dedup` |
| "rebuild" / "start over" / "archive" / "restore" | `wiki-rebuild` |
| "link my pages" / "cross-reference" / "connect my wiki" | `cross-linker` |
| "fix my tags" / "normalize tags" / "tag audit" | `tag-taxonomy` |
| "update wiki" / "sync to wiki" / "save this to my wiki" | `wiki-update` |
| `@work update wiki` / `wiki-query @personal ...` / `@research save this` | Any matching wiki skill + Config Resolution Protocol `@name` override |
| "export wiki" / "export graph" / "graphml" / "neo4j" / "export to OKF" / "OKF bundle" / "open knowledge format" | `wiki-export` |
| "import wiki" / "import from export" / "load graph.json" / "import vault" / "import OKF bundle" / "/wiki-import" | `wiki-import` |
| "color my graph" / "color code obsidian" / "color by tag/category/visibility" | `graph-colorize` |
| "save this" / "/wiki-capture" / "capture this" / "file this conversation" / "/wiki-capture --quick" / "quick capture" / "capture this finding" / "save this gotcha" / "drop to raw" | `wiki-capture` |
| "/wiki-research [topic]" / "research X" / "find everything about Y" | `wiki-research` |
| "create a dashboard" / "vault dashboard" / "show all X as a table" / "dynamic view" | `wiki-dashboard` |
| "synthesize my wiki" / "find connections" / "what concepts keep coming up together" / "/wiki-synthesize" | `wiki-synthesize` |
| "create a new skill" | `skill-creator` |
| "/vault-skill-factory" / "make a skill from my wiki" / "turn these pages into a skill" / "package my notes on X as a skill" / "build a domain-expert skill from my vault" | `vault-skill-factory` |
| "/wiki-claude [topic]" / "/wiki-codex [topic]" / "/wiki-hermes [topic]" / "/wiki-openclaw [topic]" / "/wiki-copilot [topic]" / "/wiki-pi [topic]" | `wiki-agent` |
| "/memory-bridge" / "browse codex memory" / "what did codex know about X" / "compare tool memories" / "cross-tool memory" | `memory-bridge` |
| "/daily-update" / "morning sync" / "refresh the wiki index" / "set up the daily cron" / "install terminal notification" | `daily-update` |
| "/impl-validator" / "check this implementation" / "validate what you did" / "is this correct?" | `impl-validator` |
| "/wiki-switch NAME" / "switch to my work wiki" / "switch vault" / "change wiki" / "list my wikis" / "show my vaults" / "create a new vault config" | `wiki-switch` |
| "/wiki-digest" / "what did I learn this week" / "weekly digest" / "knowledge summary" / "what's new in my wiki" / "summarize my recent learning" / "monthly review" | `wiki-digest` |
| "/wiki-context-pack" / "make a context pack" / "context slice for X" / "pack the wiki for my agent" / "bounded context for Y" | `wiki-context-pack` |
| "/wiki-stage-commit" / "review staged pages" / "commit staged writes" / "promote staged pages" / "what's waiting in staging" | `wiki-stage-commit` |
| "restyle Obsidian" / "adjust the vault layout" / "CSS snippet" / "tune tabs/sidebars/graph panes" | `obsidian-layout-adjustment` |

## Cross-Project Usage

The main use case: you're working in some other project and want to sync knowledge into your wiki or query it. Two global skills handle this — `wiki-update` and `wiki-query`. They work from any directory.

### wiki-update (write to wiki)

1. Resolve config using the Config Resolution Protocol to get `OBSIDIAN_VAULT_PATH`
2. Scan the current project: README, source structure, git log, package metadata
3. Distill what's worth remembering (architecture decisions, patterns, trade-offs — not code listings)
4. Write to `$VAULT/projects/<project-name>.md`, cross-linking to concept/entity pages as needed
5. Update `.manifest.json`, `index.md`, and `log.md`

On repeat runs, it checks `last_commit_synced` in `.manifest.json` and only processes the delta via `git log <last_commit>..HEAD`.

### wiki-query (read from wiki)

1. Resolve config using the Config Resolution Protocol to get `OBSIDIAN_VAULT_PATH`
2. Scan titles, tags, and `summary:` frontmatter fields first (cheap pass)
3. Only open page bodies when the index pass can't answer
4. Return a synthesized answer with `[[wikilink]]` citations

## Visibility Tags (optional)

Pages can carry a `visibility/` tag to mark their intended reach. **This is entirely optional** — untagged pages behave exactly as they always have (visible everywhere). The system stays single-vault, single source of truth.

| Tag | Meaning |
|---|---|
| *(no tag)* | Same as `visibility/public` — visible in all modes |
| `visibility/public` | Explicitly public — visible in all modes |
| `visibility/internal` | Team-only — excluded when querying in filtered mode |
| `visibility/pii` | Sensitive data — excluded when querying in filtered mode |

**Filtered mode** is opt-in, triggered by phrases like "public only", "user-facing answer", "no internal content", or "as a user would see it" in a query. Default mode shows everything.

`visibility/` tags are **system tags** — they don't count toward the 5-tag limit and are listed separately from domain/type tags in the taxonomy.

See `wiki-query` and `wiki-export` skills for how the filter is applied.

## Core Principles

- **Compile, don't retrieve.** The wiki is pre-compiled knowledge. Update existing pages — don't append or duplicate.
- **Track everything.** Update `.manifest.json` after ingesting, `index.md`, `log.md`, and `hot.md` after any write operation.
- **Connect with `[[wikilinks]]`.** Every page should link to related pages. This is what makes it a knowledge graph, not a folder of files.
- **Frontmatter is required.** Every wiki page needs: `title`, `category`, `tags`, `sources`, `created`, `updated`.
- **Single source of truth.** Visibility tags shape how content is surfaced — they don't duplicate or separate it.
- **Keep context warm.** `hot.md` is a ~500-word semantic snapshot of recent activity. Every write skill updates it so the next session can pick up where the last one left off without crawling the full vault.

## Architecture Reference

For the full pattern (three-layer architecture, page templates, project org), read `.skills/llm-wiki/SKILL.md`.

The vault format is structurally conformant with the [Open Knowledge Format (OKF) v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) — markdown files with YAML frontmatter, category subfolders, reserved `index.md`/`log.md`. `wiki-export` (OKF mode) and `wiki-import` are the bridge: they translate between our native frontmatter (`title`/`category`/`tags`/`sources`/`created`/`updated` + `summary`) and OKF (`type`/`title`/`description`/`resource`/`tags`/`timestamp`), making vaults exchangeable with any OKF tool. The OKF round-trip is lossless; the `graph.json` round-trip is not.
