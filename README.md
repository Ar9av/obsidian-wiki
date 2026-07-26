# obsidian-wiki


<p align="center">
  <a href="https://deepwiki.com/Ar9av/obsidian-wiki"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" /></a>
  <a href="https://github.com/ar9av/obsidian-wiki/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome" /></a>
  <a href="https://x.com/_ar9av"><img src="https://img.shields.io/badge/@__ar9av-black?logo=x&logoColor=white" alt="X" /></a>
</p>

<p align="center">
  <img width="768" height="512" alt="obisidan-wiki" src="https://github.com/user-attachments/assets/b44cf63b-3197-4fb1-8e18-dbc9a39f27a7" />
</p>

English | [繁體中文](README_TW.md)

A **digital brain** you grow with your AI agent. It remembers what you figure out, connects it to what you already know, and answers when you ask.

The pattern comes from Andrej Karpathy's [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): compile knowledge once into interconnected markdown files and keep them current, instead of asking an LLM the same questions over and over (or running RAG every time). Obsidian is how you see the brain. Your AI agent is how you grow it.

We built a framework around that idea. Every skill is a markdown file that any AI coding agent (Claude Code, Cursor, Windsurf, Pi, and others) reads and runs. Point it at an Obsidian vault, tell it what to remember, and the vault becomes a second brain you own.

## Quick Start

### Let your agent set it up

The fastest path — no commands required. Give your agent this repo and say:

```
https://github.com/Ar9av/obsidian-wiki — set up my wiki
```

The agent reads [`.skills/wiki-setup/SKILL.md`](.skills/wiki-setup/SKILL.md) from the repo, asks where you want your vault to live, and initializes the full structure: directories, index, log, Obsidian config, and an optional auto-capture hook. That's it — the skill is the setup guide.

This works in any agent that can read files (Claude Code, Cursor, Windsurf, Codex, Gemini CLI, Kiro, and more). After setup, every wiki skill is available immediately.

### Install via pip (recommended)

```bash
pip install obsidian-wiki
obsidian-wiki setup --vault /path/to/your/digital/brain
```

`obsidian-wiki setup` writes the config to `~/.obsidian-wiki/config` and installs every wiki skill into all your AI agents (Claude Code, Cursor, Codex, Gemini, Hermes, Pi, and more). Skills are symlinked to the installed package, so `pip install -U obsidian-wiki` upgrades them everywhere — just re-run `obsidian-wiki setup` to pick up new skills. Then open a project in your agent and say **"set up my wiki"**.

```bash
obsidian-wiki list              # list the bundled skills
obsidian-wiki info              # show install paths, version, and config
obsidian-wiki doctor            # health-check config, vault shape, and installed skills
obsidian-wiki query "rate limiting"  # query the configured vault from the terminal
obsidian-wiki lint              # lint the configured vault for broken links / metadata gaps
obsidian-wiki trust-check --strict  # CI/scheduled gate for approved manual review fingerprints
obsidian-wiki trust-record --all --reviewed-at <ISO-with-timezone> --approved  # record a human-approved full review
obsidian-wiki setup --project . # also drop project-local skills + AGENTS.md into the current repo
obsidian-wiki setup --copy      # copy skill files instead of symlinking
```

`OBSIDIAN_VAULT_PATH` is just any directory where you want your digital brain to live, a new empty folder or an existing Obsidian vault. Omit `--vault` to be prompted (or set it later in `~/.obsidian-wiki/config`).

### Local CLI utilities

The Python package also ships a few local commands for inspection and maintenance:

```bash
obsidian-wiki doctor --json
obsidian-wiki query "what do I know about MCP security?"
obsidian-wiki lint --strict
obsidian-wiki graph-query /path/to/vault "transformer architecture"
obsidian-wiki graph-analyse /path/to/vault --pretty
```

Use `doctor` to catch broken setup, stale installs, or malformed vault state. Use `query` and `lint` when you want fast local answers without going through an agent prompt. The lower-level `graph-query`, `graph-analyse`, `batch-plan`, `cache-*`, and `ast-extract` commands are still available for automation and debugging.

### Multiple Vaults

Keep a default vault active in `~/.obsidian-wiki/config`, or create named configs like `~/.obsidian-wiki/config.work` with `/wiki-switch new work`. From any directory, route one request to a named vault with `@name`, for example `@work update wiki` or `wiki-query @personal what do I know about MCP security`. The `@name` override applies only to that request and never changes your default vault.

All supported agents can use this syntax after `obsidian-wiki setup` or `setup.sh`, because the shared skills and always-on bootstrap files all point back to the same Config Resolution Protocol. The routing token works with write skills (`@work update wiki`, `@research save this`) and read skills (`wiki-query @personal what do I know about X`).

### Install via Skills CLI (deprecated)

```bash
npx skills add Ar9av/obsidian-wiki
```

This only installs the markdown skills into the current agent. It does **not** write `~/.obsidian-wiki/config`, install `~/.obsidian-wiki/sync.sh`, or wire the global multi-agent bootstrap that `obsidian-wiki setup` / `setup.sh` performs.

Use this path only if you intentionally want a partial, agent-local install and are prepared to manage config yourself. For a complete setup, use **Install via pip** or **Install via git clone** instead.

Browse the full skill list at [skills.sh/ar9av/obsidian-wiki](https://skills.sh/ar9av/obsidian-wiki).

### Install via git clone

```bash
git clone https://github.com/Ar9av/obsidian-wiki.git
cd obsidian-wiki
bash setup.sh
```

`setup.sh` asks for your vault (path to your digital brain) path, writes the config to `~/.obsidian-wiki/config`, symlinks skills into all your agents, and installs `wiki-update` globally so you can use it from any project.

Open the project in your agent and say **"set up my wiki"**. That's it.

## Agent Compatibility

Works with **any AI coding agent** that can read files — Claude Code, Cursor, Windsurf, Pi, Codex, Gemini CLI, Kiro, and more. `setup.sh` handles skill discovery for each one automatically.

<details>
<summary><b>Supported agents and manual setup instructions</b></summary>

| Agent | Bootstrap | Skills Directory | Slash Commands |
|---|---|---|---|
| **[Claude Code](https://claude.ai/code)** | `CLAUDE.md` | `.claude/skills/` + `~/.claude/skills/` | ✅ `/wiki-ingest`, `/wiki-status`, etc. |
| **[Cursor](https://cursor.com)** | `.cursor/rules/obsidian-wiki.mdc` | `.cursor/skills/` | ✅ `/wiki-ingest`, `/wiki-status`, etc. |
| **[Windsurf](https://windsurf.com)** | `.windsurf/rules/obsidian-wiki.md` | `.windsurf/skills/` | ✅ via Cascade |
| **[Codex (OpenAI)](https://openai.com/codex)** | `AGENTS.md` | `~/.codex/skills/` | `$wiki-ingest` (Codex uses `$`) |
| **[Gemini CLI](https://github.com/google-gemini/gemini-cli)** | `GEMINI.md` | `~/.gemini/skills/` | ✅ `/wiki-ingest`, `/wiki-query`, etc. |
| **[Google Antigravity](https://antigravity.google)** | `.agent/rules/` + `.agent/workflows/` | `.agents/skills/` | ✅ via workflows registry |
| **[Kiro IDE/CLI](https://kiro.dev)** | `.kiro/steering/obsidian-wiki.md` | `.kiro/skills/` + `~/.kiro/skills/` | ✅ `/wiki-ingest`, `/wiki-status`, etc. |
| **[Hermes](https://hermes-agent.nousresearch.com)** | `.hermes.md` | `~/.hermes/skills/` | ✅ `/wiki-history-ingest hermes`, etc. |
| **[OpenClaw](https://openclaw.ai)** | `AGENTS.md` | `~/.openclaw/skills/` + `~/.agents/skills/` | ✅ `/wiki-ingest`, `/wiki-history-ingest openclaw`, etc. |
| **[OpenCode](https://opencode.ai)** | `AGENTS.md` | `~/.agents/skills/` | ✅ `/wiki-ingest`, `/wiki-query`, etc. |
| **[Aider](https://aider.chat)** | `AGENTS.md` | `~/.agents/skills/` | Describe intent in chat |
| **[Factory Droid](https://factory.ai)** | `AGENTS.md` | `~/.agents/skills/` | ✅ `/wiki-ingest`, `/wiki-query`, etc. |
| **[Trae](https://trae.ai)** / **Trae CN** | `AGENTS.md` | `~/.trae/skills/` / `~/.trae-cn/skills/` | ✅ via Agent tool |
| **GitHub Copilot (VS Code)** | `.github/copilot-instructions.md` | — | Describe intent in chat |
| **GitHub Copilot (CLI)** | — | `~/.copilot/skills/` | ✅ `/wiki-ingest`, `/wiki-query`, etc. |
| **[Kilocode](https://kilo.ai/)** | `AGENTS.md` / `CLAUDE.md` | `.agents/skills/` + `.claude/skills/` | ✅ `/wiki-ingest`, `/wiki-status`, etc. |
| **[Pi](https://pi.dev)** | `AGENTS.md` | `.pi/skills/` + `~/.pi/agent/skills/` | ✅ `/wiki-ingest`, `/wiki-history-ingest pi`, etc. |

> Each agent has its own convention for discovering skills. `setup.sh` symlinks the canonical `.skills/` directory into each agent's expected location. You write skills once, every agent can use them. The same is true for named-vault routing: `@name` is documented in the shared skills and bootstrap context, so Claude Code, Cursor, Windsurf, Codex, Gemini, Kiro, Hermes, OpenClaw, Copilot CLI, Pi, and the generic `AGENTS.md` agents all pick it up from the same instructions.

### Manual setup (if you prefer `setup.sh`)

<details>
<summary>Claude Code</summary>

Skills are auto-discovered from `.claude/skills/`. Either run `setup.sh` or copy `.skills/*` to `.claude/skills/`. The `CLAUDE.md` file at the repo root is automatically loaded as project context.

```bash
cd /path/to/obsidian-wiki && claude "set up my wiki"
```
</details>

<details>
<summary>Cursor</summary>

Skills are auto-discovered from `.cursor/skills/`. The `.cursor/rules/obsidian-wiki.mdc` file provides always-on context. Either run `setup.sh` or copy `.skills/*` to `.cursor/skills/`. Then type `/wiki-setup` in the chat.
</details>

<details>
<summary>Windsurf</summary>

Cascade reads rules from `.windsurf/rules/` and skills from `.windsurf/skills/`. Either run `setup.sh` or copy `.skills/*` to `.windsurf/skills/`. Then tell Cascade: "set up my wiki".
</details>

<details>
<summary>Codex</summary>

Reads `AGENTS.md` for project context. `setup.sh` installs skills globally to `~/.codex/skills/`. Either run `setup.sh` or manually symlink `.skills/*` to `~/.codex/skills/`.

```bash
cd /path/to/obsidian-wiki && codex "set up my wiki"
```
</details>

<details>
<summary>Gemini CLI</summary>

Reads `GEMINI.md` and discovers global skills from `~/.gemini/skills/`. Either run `setup.sh` or manually symlink `.skills/*` to `~/.gemini/skills/`.

```bash
cd /path/to/obsidian-wiki && gemini "set up my wiki"
```
</details>

<details>
<summary>Google Antigravity</summary>

Always-on via `.agent/rules/` + `.agent/workflows/`. `setup.sh` ships both files and symlinks skills into `.agents/skills/`. The legacy `~/.gemini/antigravity/skills/` path is also wired.
</details>

<details>
<summary>Kiro IDE/CLI</summary>

Always-on via `.kiro/steering/*.md` with `inclusion: always`. `setup.sh` symlinks `.skills/*` into both `.kiro/skills/` and `~/.kiro/skills/`. Invoke with `/wiki-ingest`, `/wiki-query`, etc.
</details>

<details>
<summary>OpenCode / Aider / Factory Droid / Trae</summary>

All read `AGENTS.md` at the repo root. `setup.sh` symlinks skills into `~/.agents/skills/` (shared discovery path). Trae also gets `~/.trae/skills/` and `~/.trae-cn/skills/`.
</details>

<details>
<summary>Hermes</summary>

Reads `.hermes.md` first, then falls back to `AGENTS.md`. Skills discovered from `~/.hermes/skills/`. Run `setup.sh` or manually symlink `.skills/*` there.

```bash
cd /path/to/obsidian-wiki && hermes "set up my wiki"
# Mine Hermes history into the wiki:
/wiki-history-ingest hermes
```
</details>

<details>
<summary>OpenClaw</summary>

Reads `AGENTS.md` (priority 10). Discovers skills from `~/.openclaw/skills/` and `~/.agents/skills/`. Skills auto-register as slash commands.

```bash
cd /path/to/obsidian-wiki && openclaw "set up my wiki"
# Mine OpenClaw history:
/wiki-history-ingest openclaw
```
</details>

<details>
<summary>GitHub Copilot</summary>

**VS Code Chat:** reads `.github/copilot-instructions.md`. Say "set up my wiki" in Copilot Chat.

**CLI:** discovers skills from `~/.copilot/skills/`. Run `setup.sh` or manually symlink `.skills/*` there.
</details>

<details>
<summary>Pi</summary>

Reads `AGENTS.md` (walking up from cwd). Discovers skills from `.pi/skills/`, `.agents/skills/`, and `~/.pi/agent/skills/`. Run `setup.sh` or manually symlink `.skills/*` to `~/.pi/agent/skills/`.

```bash
cd /path/to/obsidian-wiki && pi "set up my wiki"
# Mine Pi session history:
/wiki-history-ingest pi
```
</details>

</details>

## How it works

Every time you feed the brain, it runs through four stages:

**1. Ingest** — The agent reads your source material directly. It handles whatever you throw at it: markdown files, PDFs (with page ranges), JSONL conversation exports, plain text logs, chat exports, meeting transcripts, and images (screenshots, whiteboard photos, diagrams — vision-capable model required). No preprocessing step, no pipeline to run. The agent reads the file the same way it reads code.

**2. Pull Information** — From the raw source, the agent pulls out concepts, entities, claims, relationships, and open questions. A conversation about debugging a React hook yields a "stale closure" pattern. A research paper yields the key idea and its caveats. A work log yields decisions and their rationale. Noise gets dropped, signal gets kept. Each page also gets a 1–2 sentence `summary:` in its frontmatter at write time — later queries use this to preview pages without opening them.

**3. Merge** — New knowledge gets merged against what's already in the wiki. If a concept page exists, the agent updates it — merging new information, noting contradictions, strengthening cross-references. If it's genuinely new, a page gets created. Nothing is duplicated. Sources are tracked in frontmatter so every claim stays attributable.

**4. Schema** — The wiki schema isn't fixed upfront. It emerges from your sources and evolves as you add more. The agent maintains coherence: categories stay consistent, wikilinks point to real pages, the index reflects what's actually there. When you add a new domain (a new project, a new field of study), the schema expands to accommodate it without breaking what exists.

A `.manifest.json` tracks every source that's been ingested — path, timestamps, which wiki pages it produced. On the next ingest, the agent computes the delta and only processes what's new or changed.


## Visualization

Through Global Graph View visualize every note and link within your entire vault. 
- **Ribbon Icon**: Click the "Open graph view" icon (looks like a connected network) on the left-side ribbon.
- **Command Palette**: Press Ctrl + P (Windows/Linux) or Cmd + P (Mac), type "Open graph view", and press Enter.

<img width="1632" height="963" alt="obsidian-wiki" src="https://github.com/user-attachments/assets/f2980840-4b5b-438a-8264-5ad1de42f483" />

### Color-coding the graph

Say **"color my graph"**, **"color code by tag"**, **"color by category"**, or **"highlight visibility in graph"** and the `graph-colorize` skill rewrites `<vault>/.obsidian/graph.json` so Obsidian tints nodes by tag, folder, or visibility. It scans your actual vocabulary, picks a colorblind-friendly palette, backs up the existing `graph.json` first, and only touches the `colorGroups` field — your zoom, physics, and filter preferences stay intact. Reload Obsidian (Cmd/Ctrl+R) to see the change.

Modes: `by-tag` (default — top 10 tags), `by-category` (the seven vault folders), `by-visibility` (highlight `visibility/pii` and `visibility/internal`), `combined` (visibility + tags), or `custom` (user-supplied mapping).

## What we added on top of Karpathy's pattern

- **Delta tracking.** A manifest tracks every source file that's been ingested: path, timestamps, which wiki pages it produced. When you come back later, it computes the delta and only processes what's new or changed. You're not re-ingesting your entire document library every time.

- **Project-based organization.** Knowledge gets filed under projects when it's project-specific, globally when it's not. Both are cross-referenced with wikilinks. If you're working on 10 different codebases, each one gets its own space in the vault.

- **Archive and rebuild.** When the wiki drifts too far from your sources, you can archive the whole thing (timestamped snapshot, nothing lost) and rebuild from scratch. Or restore any previous archive.

- **Multi-agent ingest.** Documents, PDFs, Claude Code history (`~/.claude`), Codex sessions (`~/.codex/`), Hermes memories and sessions (`~/.hermes/`), OpenClaw MEMORY.md and sessions (`~/.openclaw/`), Pi sessions (`~/.pi/agent/sessions/`), Windsurf data (`~/.windsurf`), ChatGPT exports, Slack logs, meeting transcripts, raw text. There are dedicated skills for Claude, Codex, Hermes, OpenClaw, and Pi history, plus a catch-all ingest skill for arbitrary text exports.

- **Cross-agent targeted search.** `/wiki-claude`, `/wiki-codex`, `/wiki-hermes`, `/wiki-openclaw`, `/wiki-copilot`, `/wiki-pi` — query-driven ingest from a specific agent's raw history. Say `/wiki-codex "rust ownership"` while in Claude Code and it finds your Codex sessions about that topic, extracts the relevant conversation blobs, distills them into wiki pages, and returns a synthesized answer you can use immediately. Different from bulk ingest: this is topic-first, not session-first. Each agent has its own extraction strategy (Codex rollout events, Claude JSONL turns, OpenClaw's pre-synthesized `MEMORY.md`, Pi tree-structured JSONL sessions, etc.). Pair with `/memory-bridge diff` to see what each tool uniquely contributed to a topic.

- **Audit and lint.** Find orphaned pages, broken wikilinks, stale content, contradictions, missing frontmatter. See a dashboard of what's been ingested vs what's pending.

- **Automated cross-linking.** After ingesting new pages, the cross-linker scans the vault for unlinked mentions and weaves them into the knowledge graph with `[[wikilinks]]`. No more orphan pages.

- **Tag taxonomy.** A controlled vocabulary of canonical tags stored in `_meta/taxonomy.md`, with a skill that audits and normalizes tags across your entire vault.

- **Provenance tracking.** Every claim on a wiki page is tagged: extracted (default), `^[inferred]` (LLM synthesis), or `^[ambiguous]` (sources disagree). A `provenance:` block in the frontmatter summarizes the mix per page, and `wiki-lint` flags pages that drift into mostly speculation. You can always tell what your wiki actually knows from what it guessed.

- **Multimodal sources.** Screenshots, whiteboard photos, slide captures, and diagrams ingest the same way as text — the agent transcribes any visible text verbatim and tags interpreted content as inferred. Requires a vision-capable model.

- **Wiki insights.** Beyond delta tracking, `wiki-status` can analyze the shape of your vault itself: top hubs, bridge pages (nodes whose removal would partition the graph), tag cluster cohesion scores, scored surprising connections, a graph delta since last run, and suggested questions the wiki structure is uniquely positioned to answer. Output goes to `_insights.md`.

- **Graph export.** `wiki-export` turns the vault's wikilink graph into `graph.json` (queryable), `graph.graphml` (Gephi/yEd), `cypher.txt` (Neo4j), and a self-contained `graph.html` interactive browser visualization — no server required.

- **Tiered retrieval.** `wiki-query` reads titles, tags, and page summaries first and only opens page bodies when the cheap pass can't answer. Say "quick answer" or "just scan" to force index-only mode. Keeps query cost roughly flat as your vault grows from 20 pages to 2000.

- **QMD semantic search (optional).** [QMD](https://github.com/tobi/qmd) indexes your wiki and source documents for semantic search. When `QMD_WIKI_COLLECTION` is set in `.env`, `wiki-query` runs a lex+vec pass against the collection before falling back to Grep — enabling concept-level matches that exact-string search misses. When `QMD_PAPERS_COLLECTION` is set, `wiki-ingest` queries your indexed sources before writing a new page, surfacing related work, detecting contradictions, and deciding whether to create or merge. QMD can be used through MCP or the local CLI. Without QMD, both skills fall back to Grep/Glob and remain fully functional.

- **`_raw/` staging directory.** Drop rough notes, clipboard pastes, or quick captures into `_raw/` inside your vault. The next `wiki-ingest` run promotes them to proper wiki pages and removes the originals. Configured via `OBSIDIAN_RAW_DIR` in `.env` (defaults to `_raw`).

## Optional: QMD Semantic Search

By default, `wiki-ingest` and `wiki-query` use `Grep`/`Glob` for search — fully functional, no extra setup. If your vault grows large or you want concept-level matches across your sources, you can plug in [QMD](https://github.com/tobi/qmd), either through MCP or by letting the agent call the local `qmd` CLI.

**Setup:**

1. Install QMD. If you want MCP mode, also add it to your MCP config (see the QMD repo for instructions).
2. Index your wiki and/or source documents:
   ```bash
   qmd index --name wiki /path/to/your/vault
   qmd index --name papers /path/to/your/sources
   ```
3. Set the collection names and transport in your `.env`:
   ```env
   QMD_WIKI_COLLECTION=wiki       # used by wiki-query
   QMD_PAPERS_COLLECTION=papers   # used by wiki-ingest (source discovery)
   QMD_TRANSPORT=mcp              # mcp | cli
   QMD_CLI_SEARCH_MODE=quality    # quality | balanced | fast
   ```

`QMD_TRANSPORT=mcp` preserves the original behavior and uses an agent-configured QMD MCP server. `QMD_TRANSPORT=cli` runs the local `qmd` command directly. CLI mode defaults to `quality`, which uses `qmd query` with reranking for the best relevance. If that is too slow on CPU, set `QMD_CLI_SEARCH_MODE=balanced` to use `qmd query --no-rerank`, or `fast` for a lighter semantic pass.

**What changes with QMD enabled:**

- **`wiki-query`** runs a semantic pass (lex+vec) against your wiki collection before falling back to Grep. Finds conceptually related pages even when the exact terms don't match.
- **`wiki-ingest`** queries your papers collection before writing a new page — surfaces related sources, spots contradictions, and decides whether to create a new page or merge into an existing one.

Both skills degrade gracefully: if `QMD_WIKI_COLLECTION` / `QMD_PAPERS_COLLECTION` are not set, they skip the QMD step silently and use Grep instead.

### `_raw/` Staging Directory

`_raw/` is a staging area inside your vault for unprocessed captures — rough notes, clipboard pastes, quick voice-memo transcripts. Drop files there and the next `wiki-ingest` run will promote them to proper wiki pages and remove the originals.

The fastest way to feed `_raw/` during a live coding session is `/wiki-capture --quick` — it scans the current conversation, extracts bugs and gotchas, and writes structured draft files in under 60 seconds with no subagents or manifest writes.

The directory is created automatically by `wiki-setup`. The path is configurable via `OBSIDIAN_RAW_DIR` in `.env` (defaults to `_raw`).

### Browser Capture Extension

This repo includes a zero-build Chrome extension at `extensions/brain-capture/` for saving web pages and selected text into your vault's `_raw/` folder.

To install it:

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select `extensions/brain-capture`

To find the configured `_raw` folder from this repo:

```bash
awk -F= '/^OBSIDIAN_VAULT_PATH=/{print $2 "/_raw"; exit}' "$(git rev-parse --show-toplevel)/.env"
```

After capturing pages into `_raw/`, ask your agent to process them:

```text
/wiki-ingest promote my raw pages
```

`wiki-ingest` will read each `_raw/` capture, distill it into the right wiki pages, update the manifest/index/log, and remove the promoted raw files so they are not processed twice.

---

## Syncing your vault to GitHub

Your vault is a directory of plain markdown files — push it to a private GitHub repo and you get version history, backup, and cross-device sync for free. `setup.sh` (and `obsidian-wiki setup`) will ask you to configure this during the initial install.

**What setup does:**

1. `git init` your vault if it isn't already a repo
2. Creates a `.gitignore` that excludes Obsidian workspace/cache files
3. Sets the GitHub remote you supply
4. Writes `~/.obsidian-wiki/sync.sh` — a one-shot script that stages all changes, commits with a timestamp, and pushes
5. Optionally adds a `wiki-sync` shell alias
6. Optionally installs an hourly cron job

**Run a sync at any time:**

```bash
wiki-sync                    # alias added by setup
~/.obsidian-wiki/sync.sh     # or call the script directly
```

Each run commits staged changes as `sync 2026-06-08 14:00` and pushes.

**Manual setup (skip the prompt):**

```bash
cd /path/to/your/vault
git init
git remote add origin https://github.com/you/my-wiki.git

# then commit and push manually, or re-run setup.sh to get the sync script
```

**Hourly auto-sync via cron (can be enabled during setup):**

```
0 * * * * ~/.obsidian-wiki/sync.sh >> ~/.obsidian-wiki/sync.log 2>&1
```

> Keep the repo **private** if your vault contains personal notes. Nothing is sent to any third-party service — your vault lives on your machines and your GitHub account only.

---

## Skills

Everything lives in `.skills/`. Each skill is a markdown file the agent reads when triggered:

| Skill                   | What it does                                      | Slash Command            |
| ----------------------- | ------------------------------------------------- | ------------------------ |
| `wiki-setup`            | Initialize vault structure                        | `/wiki-setup`            |
| `wiki-ingest`           | Distill documents into wiki pages, plus chat exports, logs, transcripts, URLs | `/wiki-ingest`           |
| `wiki-history-ingest`   | Unified history router (`claude`, `codex`, `hermes`, `pi`) | `/wiki-history-ingest <claude|codex|hermes|pi>` |
| `claude-history-ingest` | Mine your `~/.claude` conversations and memories from Claude code and desktop  | `/claude-history-ingest` |
| `codex-history-ingest`  | Mine your `~/.codex` sessions and rollout logs    | `/codex-history-ingest`  |
| `hermes-history-ingest` | Mine your `~/.hermes` memories and sessions       | `/hermes-history-ingest` |
| `openclaw-history-ingest` | Mine your `~/.openclaw` MEMORY.md and sessions  | `/openclaw-history-ingest` |
| `copilot-history-ingest` | Mine your `~/.copilot` CLI session history       | `/copilot-history-ingest` |
| `pi-history-ingest`     | Mine your `~/.pi/agent/sessions` JSONL history    | `/pi-history-ingest` |
| `wiki-status`           | Show what's ingested, what's pending, the delta   | `/wiki-status`           |
| `wiki-rebuild`          | Archive, rebuild from scratch, or restore         | `/wiki-rebuild`          |
| `wiki-query`            | Answer questions from the wiki                    | `/wiki-query`            |
| `wiki-narrate`          | Render a cited narrative from a wiki topic        | `/wiki-narrate <topic>`  |
| `wiki-lint`             | Find broken links, orphans, contradictions        | `/wiki-lint`             |
| `cross-linker`          | Auto-discover and insert missing wikilinks        | `/cross-linker`          |
| `tag-taxonomy`          | Enforce consistent tag vocabulary across pages    | `/tag-taxonomy`          |
| `llm-wiki`              | The core pattern and architecture reference       | `/llm-wiki`              |
| `wiki-update`           | Sync current project's knowledge into the vault   | `/wiki-update`           |
| `wiki-export`           | Export vault graph to JSON, GraphML, Neo4j, HTML  | `/wiki-export`           |
| `wiki-capture`          | Save the current conversation as a wiki note; `--quick` stages findings to `_raw/` | `/wiki-capture`          |
| `wiki-research`         | Autonomous multi-round web research, self-filed   | `/wiki-research [topic]` |
| `wiki-dashboard`        | Create dynamic Obsidian Bases dashboard views     | `/wiki-dashboard`        |
| `wiki-synthesize`       | Discover and fill synthesis gaps across concepts  | `/wiki-synthesize`       |
| `wiki-agent`            | Query-driven ingest from a specific agent's history | `/wiki-claude [topic]`, `/wiki-codex [topic]`, etc. |
| `memory-bridge`         | Browse and diff knowledge by which AI tool wrote it | `/memory-bridge`         |
| `daily-update`          | Daily maintenance cycle — freshness, index, hot cache | `/daily-update`        |
| `impl-validator`        | Validate an implementation against its stated goal | `/impl-validator`       |
| `graph-colorize`        | Color-code the Obsidian graph by tag/category/visibility | `/graph-colorize`   |
| `skill-creator`         | Create new skills                                 | `/skill-creator`         |

> **Note:** Slash commands (`/skill-name`) work in Claude Code, Cursor, and Windsurf. In other agents, just describe what you want and the agent will find the right skill.

### Recommended: Obsidian Skills by Kepano

We handle the knowledge management workflow — ingest, query, lint, rebuild. For Obsidian format mastery, we recommend installing [**kepano/obsidian-skills**](https://github.com/kepano/obsidian-skills) alongside this framework. These are optional but improve the quality of wiki output:

| Skill | What it adds |
|---|---|
| `obsidian-markdown` | Teaches the agent correct Obsidian-flavored syntax — wikilinks, callouts, embeds, properties |
| `obsidian-bases` | Create and edit `.base` files (database-like views of notes) |
| `json-canvas` | Create and edit `.canvas` files (visual mind maps, flowcharts) |
| `obsidian-cli` | Interact with a running Obsidian instance via CLI (search, create, manage notes) |
| `defuddle` | Extract clean markdown from web pages — less noise than raw fetch, saves tokens during ingest |

Both projects use the same [Agent Skills spec](https://agentskills.io/specification), so they coexist in the same `.skills/` directory with no conflicts.

**Install:**

```bash
npx skills add kepano/obsidian-skills
```

After installing, your agent will automatically pick up the new skills alongside the existing wiki skills.

## Project Structure

```
obsidian-wiki/
├── .skills/                          # ← Canonical skill definitions (source of truth)
│   ├── wiki-setup/SKILL.md
│   ├── wiki-ingest/SKILL.md
│   ├── wiki-history-ingest/SKILL.md
│   ├── claude-history-ingest/SKILL.md
│   ├── codex-history-ingest/SKILL.md
│   ├── hermes-history-ingest/SKILL.md
│   ├── openclaw-history-ingest/SKILL.md
│   ├── pi-history-ingest/SKILL.md
│   ├── wiki-status/SKILL.md
│   ├── wiki-rebuild/SKILL.md
│   ├── wiki-query/SKILL.md
│   ├── wiki-lint/SKILL.md
│   ├── cross-linker/SKILL.md
│   ├── tag-taxonomy/SKILL.md
│   ├── wiki-update/SKILL.md
│   ├── llm-wiki/SKILL.md
│   ├── wiki-export/SKILL.md
│   └── skill-creator/SKILL.md
│
├── CLAUDE.md                            # Bootstrap → Claude Code / Kilocode (→ AGENTS.md)
├── GEMINI.md                            # Bootstrap → Gemini CLI (→ AGENTS.md)
├── AGENTS.md                            # Bootstrap → Codex, OpenCode, Aider, Droid, Trae, Hermes, OpenClaw, Kilocode
├── .hermes.md                           # Bootstrap → Hermes (symlink → AGENTS.md)
├── .cursor/rules/obsidian-wiki.mdc      # Always-on → Cursor (alwaysApply: true)
├── .windsurf/rules/obsidian-wiki.md     # Always-on → Windsurf
├── .kiro/steering/obsidian-wiki.md      # Always-on → Kiro (inclusion: always)
├── .agent/rules/obsidian-wiki.md        # Always-on → Google Antigravity
├── .agent/workflows/obsidian-wiki.md    # Slash-command registry → Google Antigravity
├── .github/copilot-instructions.md      # Always-on → GitHub Copilot (VS Code Chat)
│
├── .claude/skills/   → symlinks to .skills/*  (created by setup.sh)
├── .cursor/skills/   → symlinks to .skills/*  (created by setup.sh)
├── .windsurf/skills/ → symlinks to .skills/*  (created by setup.sh)
├── .agents/skills/   → symlinks to .skills/*  (created by setup.sh)
├── .pi/skills/       → symlinks to .skills/*  (created by setup.sh)
├── .kiro/skills/     → symlinks to .skills/*  (created by setup.sh)
│
├── ~/.claude/skills/              → portable skills (wiki-update, wiki-query)
├── ~/.gemini/skills/              → global symlinks — Gemini CLI
├── ~/.gemini/antigravity/skills/  → global symlinks — Antigravity (legacy path)
├── ~/.codex/skills/               → global symlinks — Codex
├── ~/.hermes/skills/              → global symlinks — Hermes
├── ~/.openclaw/skills/            → global symlinks — OpenClaw (managed)
├── ~/.copilot/skills/             → global symlinks — GitHub Copilot CLI
├── ~/.trae/skills/                → global symlinks — Trae
├── ~/.trae-cn/skills/             → global symlinks — Trae CN
├── ~/.kiro/skills/                → global symlinks — Kiro CLI
├── ~/.pi/agent/skills/            → global symlinks — Pi
├── ~/.agents/skills/              → global symlinks — OpenCode, Aider, Droid, generic
│
├── setup.sh                          # One-command agent setup
├── .env.example                      # Configuration template
├── README.md                         # You are here
└── SETUP.md                          # Detailed setup guide
```

## Using from other projects

Your brain should grow as you work across codebases, not only when you open the obsidian-wiki repo. So `setup.sh` installs two global skills that reach the vault from any project: `wiki-update` and `wiki-query`.

When you run `bash setup.sh`, it does the following:

1. Writes a config to `~/.obsidian-wiki/config` with your vault path and the repo location. This is how the skills know where to read and write.
2. Symlinks `wiki-update` and `wiki-query` into `~/.claude/skills/` so they're available everywhere in Claude Code.
3. Symlinks all skills into every agent's global discovery path:
   - `~/.gemini/skills/` — Gemini CLI (canonical)
   - `~/.gemini/antigravity/skills/` — Google Antigravity (legacy)
   - `~/.codex/skills/` — Codex
   - `~/.hermes/skills/` — Hermes
   - `~/.openclaw/skills/` — OpenClaw (managed)
   - `~/.copilot/skills/` — GitHub Copilot CLI
   - `~/.trae/skills/` + `~/.trae-cn/skills/` — Trae / Trae CN
   - `~/.kiro/skills/` — Kiro CLI
   - `~/.pi/agent/skills/` — Pi
   - `~/.agents/skills/` — OpenCode, Aider, Factory Droid, and other AGENTS.md-aware agents

After that, you're in some project, say `~/projects/my-cool-app`, working with Claude or Pi. Two commands:

```bash
# You're working on some project
cd ~/projects/my-cool-app
claude

# Write to the wiki: distill what you've learned
> /wiki-update

# Read from the wiki: pull context about anything you've captured before
> /wiki-query what do I know about rate limiting?
```

`/wiki-update` reads your project, figures out what's worth keeping, and writes it into the brain. Architecture decisions, patterns you discovered, key concepts, trade-offs you evaluated. It skips code and file listings and saves the stuff you'd forget in 3 months. Run it again from the same project and it checks what changed since last sync (via git log) and processes only the delta.

`/wiki-query` goes the other direction. You're mid-task and you want to know what the brain already holds on a topic. Maybe you solved the same problem 2 months ago in a different project and the answer is already there. The agent searches the vault, reads the relevant pages, and gives you a synthesized answer with citations.

Both skills follow the same Karpathy pattern as everything else. If a concept page already exists in the vault, it merges into it. Everything gets cross-linked with `[[wikilinks]]`, tracked in `.manifest.json`, and logged.

## Contributing

This is early. The skills work, but there's room to make the brain smarter: better cross-referencing, sharper deduplication, bigger vaults, new ingest sources. If you've been chewing on this problem or have a workflow that could be a skill, PRs are welcome.

### Keeping both READMEs in sync

`README.md` is the English documentation and `README_TW.md` is its Traditional Chinese translation; together they are one documentation surface. Keep headings, examples, links, and user-facing behavior structurally and semantically aligned. Syncing is advisory, not a merge gate: the `readme-translation-drift` CI job only reports when the translation falls behind. To catch up, run `python tools/check_readme_sync.py` — it lists the commits that changed `README.md` without a later `README_TW.md` update plus the pending English diff — then translate and backfill those changes into `README_TW.md`. Reviewers assess translation quality.

### Adding a new skill

1. Create a folder in `.skills/your-skill-name/`
2. Add a `SKILL.md` with YAML frontmatter (`name`, `description`) and markdown instructions
3. Run `bash setup.sh` to symlink into all agent directories
4. Test with your agent by saying something that matches the description

See `.skills/skill-creator/SKILL.md` for the full guide on writing effective skills.
