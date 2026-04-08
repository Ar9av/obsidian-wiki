# obsidian-wiki

A knowledge mgmt system inspired by [gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) published by Andrej Karpathy about maintaining a personal knowledge base with LLMs : the "LLM Wiki" pattern.

Instead of asking an LLM the same questions over over (or doing RAG every time), you compile knowledge once into interconnected markdown files and keep them current. In this case Obsidian is the viewer and the LLM is the maintainer.

We took that and built a framework around it. The whole thing is a set of markdown skill files that any AI coding agent (Claude Code, Cursor, Windsurf, whatever you use) can read and execute. You point it at your Obsidian vault and tell it what to do.

## Quick Start

```bash
git clone https://github.com/Ar9av/obsidian-wiki.git
cd obsidian-wiki
bash setup.sh
```

`setup.sh` asks for your vault path, writes the config to `~/.obsidian-wiki/config`, symlinks skills into all your agents, and installs `wiki-update` globally so you can use it from any project.

`OBSIDIAN_VAULT_PATH` is just any directory where you want your wiki documents to live. It can be a new empty folder or an existing Obsidian vault. Obsidian will read from it directly.

Open the project in your agent and say **"set up my wiki"**. That's it.

## Agent Compatibility

This framework works with **any AI coding agent** that can read files. The `setup.sh` script automatically configures skill discovery for each one:

| Agent                                                     | Bootstrap File                     | Skills Directory                | Slash Commands                          |
| --------------------------------------------------------- | ---------------------------------- | ------------------------------- | --------------------------------------- |
| **[Claude Code](https://claude.ai/code)**                 | `CLAUDE.md`                        | `.claude/skills/`               | ✅ `/wiki-ingest`, `/wiki-status`, etc. |
| **[Cursor](https://cursor.com)**                          | `.cursor/rules/obsidian-wiki.mdc`  | `.cursor/skills/`               | ✅ `/wiki-ingest`, `/wiki-status`, etc. |
| **[Windsurf](https://windsurf.com)**                      | `.windsurf/rules/obsidian-wiki.md` | `.windsurf/skills/`             | ✅ via Cascade                          |
| **[Codex (OpenAI)](https://openai.com/codex)**            | `AGENTS.md`                        | `~/.codex/skills/`              | `/wiki...                               |
| **[Antigravity (Google)](https://aistudio.google.com)**   | `GEMINI.md`                        | `~/.gemini/antigravity/skills/` | `update wiki`                           |
| **[OpenClaw](https://openclaw.ai)**                       | `AGENTS.md`                        | `.agents/skills/` + `~/.agents/skills/` | — (trigger by phrase)           |
| **[GitHub Copilot](https://github.com/features/copilot)** | `.github/copilot-instructions.md`  | —                               | —                                       |

> **How it works:** Each agent has its own convention for discovering skills. `setup.sh` symlinks the canonical `.skills/` directory into each agent's expected location, and creates the bootstrap file that tells the agent about the project. You write skills once, every agent can use them.

### Manual setup (if you prefer)

If you don't want to run `setup.sh`, you can configure your agent manually:

<details>
<summary><b>Claude Code</b></summary>

Skills are auto-discovered from `.claude/skills/`. Either:

- Run `setup.sh` to create symlinks, OR
- Copy `.skills/*` to `.claude/skills/`

The `CLAUDE.md` file at the repo root is automatically loaded as project context.

```bash
cd /path/to/obsidian-wiki && claude "set up my wiki"
```

</details>

<details>
<summary><b>Cursor</b></summary>

Skills are auto-discovered from `.cursor/skills/`. The `.cursor/rules/obsidian-wiki.mdc` file provides always-on context. Either:

- Run `setup.sh` to create symlinks, OR
- Copy `.skills/*` to `.cursor/skills/`

Open the project in Cursor and type `/wiki-setup` in the chat.

</details>

<details>
<summary><b>Windsurf</b></summary>

Cascade reads rules from `.windsurf/rules/` and skills from `.windsurf/skills/`. Either:

- Run `setup.sh` to create symlinks, OR
- Copy `.skills/*` to `.windsurf/skills/`

Open in Windsurf and tell Cascade: "set up my wiki".

</details>

<details>
<summary><b>Codex (OpenAI)</b></summary>

Codex reads the `AGENTS.md` file at the repo root for project context. `setup.sh` installs skills globally to `~/.codex/skills/`, making them available from any project. Either:

- Run `setup.sh` to create symlinks globally, OR
- Manually symlink `.skills/*` to `~/.codex/skills/`

```bash
cd /path/to/obsidian-wiki && codex "set up my wiki"
```

</details>

<details>
<summary><b>Antigravity / Gemini</b></summary>

Gemini agents read `GEMINI.md` at the repo root. `setup.sh` installs skills globally to `~/.gemini/antigravity/skills/`, making them available from any project. Either:

- Run `setup.sh` to create symlinks globally, OR
- Manually symlink `.skills/*` to `~/.gemini/antigravity/skills/`

Open in AI Studio and say "set up my wiki".

</details>

<details>
<summary><b>OpenClaw</b></summary>

OpenClaw is a local agent daemon that exposes itself through chat channels (Telegram, Slack, Discord, etc.) and discovers skills from `<workspace>/.agents/skills/` and `~/.agents/skills/`. It also reads `AGENTS.md` in the project root for always-on instructions. Either:

- Run `setup.sh` to create both symlinks (workspace + global), OR
- Manually symlink `.skills/*` into `.agents/skills/` and `~/.agents/skills/`

OpenClaw doesn't have slash commands the way Claude Code does — just describe what you want and the agent will pick the right skill via `AGENTS.md` and the skill descriptions.

```bash
cd /path/to/obsidian-wiki && openclaw "set up my wiki"
```

</details>

<details>
<summary><b>GitHub Copilot</b></summary>

Copilot reads `.github/copilot-instructions.md` for project context. Skills are referenced by path — Copilot will follow the instructions to read the relevant SKILL.md files.

Use Copilot Chat in VS Code and say "set up my wiki".

</details>

## How it works

Every ingest runs through four stages:

**1. Ingest** — The agent reads your source material directly. It handles whatever you throw at it: markdown files, PDFs (with page ranges), JSONL conversation exports, plain text logs, chat exports, meeting transcripts, and images (screenshots, whiteboard photos, diagrams — vision-capable model required). No preprocessing step, no pipeline to run. The agent reads the file the same way it reads code.

**2. Extract** — From the raw source, the agent pulls out concepts, entities, claims, relationships, and open questions. A conversation about debugging a React hook yields a "stale closure" pattern. A research paper yields the key idea and its caveats. A work log yields decisions and their rationale. Noise gets dropped, signal gets kept. Each page also gets a 1–2 sentence `summary:` in its frontmatter at write time — later queries use this to preview pages without opening them.

**3. Resolve** — New knowledge gets merged against what's already in the wiki. If a concept page exists, the agent updates it — merging new information, noting contradictions, strengthening cross-references. If it's genuinely new, a page gets created. Nothing is duplicated. Sources are tracked in frontmatter so every claim stays attributable.

**4. Schema** — The wiki schema isn't fixed upfront. It emerges from your sources and evolves as you add more. The agent maintains coherence: categories stay consistent, wikilinks point to real pages, the index reflects what's actually there. When you add a new domain (a new project, a new field of study), the schema expands to accommodate it without breaking what exists.

A `.manifest.json` tracks every source that's been ingested — path, timestamps, which wiki pages it produced. On the next ingest, the agent computes the delta and only processes what's new or changed.

## What we added on top of Karpathy's pattern

- **Delta tracking.** A manifest tracks every source file that's been ingested: path, timestamps, which wiki pages it produced. When you come back later, it computes the delta and only processes what's new or changed. You're not re-ingesting your entire document library every time.

- **Project-based organization.** Knowledge gets filed under projects when it's project-specific, globally when it's not. Both are cross-referenced with wikilinks. If you're working on 10 different codebases, each one gets its own space in the vault.

- **Archive and rebuild.** When the wiki drifts too far from your sources, you can archive the whole thing (timestamped snapshot, nothing lost) and rebuild from scratch. Or restore any previous archive.

- **Multi-agent ingest.** Documents, PDFs, Claude Code history (`~/.claude`), Codex sessions (`~/.codex/`), Windsurf data (`~/.windsurf`), ChatGPT exports, Slack logs, meeting transcripts, raw text. There's a specific skill for Claude history that understands the JSONL format and memory files, and a catch-all skill that figures out whatever format you throw at it.

- **Audit and lint.** Find orphaned pages, broken wikilinks, stale content, contradictions, missing frontmatter. See a dashboard of what's been ingested vs what's pending.

- **Automated cross-linking.** After ingesting new pages, the cross-linker scans the vault for unlinked mentions and weaves them into the knowledge graph with `[[wikilinks]]`. No more orphan pages.

- **Tag taxonomy.** A controlled vocabulary of canonical tags stored in `_meta/taxonomy.md`, with a skill that audits and normalizes tags across your entire vault.

- **Provenance tracking.** Every claim on a wiki page is tagged: extracted (default), `^[inferred]` (LLM synthesis), or `^[ambiguous]` (sources disagree). A `provenance:` block in the frontmatter summarizes the mix per page, and `wiki-lint` flags pages that drift into mostly speculation. You can always tell what your wiki actually knows from what it guessed.

- **Multimodal sources.** Screenshots, whiteboard photos, slide captures, and diagrams ingest the same way as text — the agent transcribes any visible text verbatim and tags interpreted content as inferred. Requires a vision-capable model.

- **Wiki insights.** Beyond delta tracking, `wiki-status` can analyze the shape of your vault itself: top hubs (anchor pages), 2-hop paths between unrelated topics (cross-domain bridges), and dead-end pages near anchor pages that should be cross-linked. Output goes to `_insights.md` at the vault root.

- **Tiered retrieval.** `wiki-query` reads titles, tags, and page summaries first and only opens page bodies when the cheap pass can't answer. Say "quick answer" or "just scan" to force index-only mode. Keeps query cost roughly flat as your vault grows from 20 pages to 2000.

## Skills

Everything lives in `.skills/`. Each skill is a markdown file the agent reads when triggered:

| Skill                   | What it does                                      | Slash Command            |
| ----------------------- | ------------------------------------------------- | ------------------------ |
| `wiki-setup`            | Initialize vault structure                        | `/wiki-setup`            |
| `wiki-ingest`           | Distill documents into wiki pages                 | `/wiki-ingest`           |
| `claude-history-ingest` | Mine your `~/.claude` conversations and memories  | `/claude-history-ingest` |
| `data-ingest`           | Ingest any text — chat exports, logs, transcripts | `/data-ingest`           |
| `wiki-status`           | Show what's ingested, what's pending, the delta   | `/wiki-status`           |
| `wiki-rebuild`          | Archive, rebuild from scratch, or restore         | `/wiki-rebuild`          |
| `wiki-query`            | Answer questions from the wiki                    | `/wiki-query`            |
| `wiki-lint`             | Find broken links, orphans, contradictions        | `/wiki-lint`             |
| `cross-linker`          | Auto-discover and insert missing wikilinks        | `/cross-linker`          |
| `tag-taxonomy`          | Enforce consistent tag vocabulary across pages    | `/tag-taxonomy`          |
| `llm-wiki`              | The core pattern and architecture reference       | `/llm-wiki`              |
| `wiki-update`           | Sync current project's knowledge into the vault   | `/wiki-update`           |
| `skill-creator`         | Create new skills                                 | `/skill-creator`         |

> **Note:** Slash commands (`/skill-name`) work in Claude Code, Cursor, and Windsurf. In other agents, just describe what you want and the agent will find the right skill.

## Project Structure

```
obsidian-wiki/
├── .skills/                          # ← Canonical skill definitions (source of truth)
│   ├── wiki-setup/SKILL.md
│   ├── wiki-ingest/SKILL.md
│   ├── claude-history-ingest/SKILL.md
│   ├── data-ingest/SKILL.md
│   ├── wiki-status/SKILL.md
│   ├── wiki-rebuild/SKILL.md
│   ├── wiki-query/SKILL.md
│   ├── wiki-lint/SKILL.md
│   ├── cross-linker/SKILL.md
│   ├── tag-taxonomy/SKILL.md
│   ├── wiki-update/SKILL.md
│   ├── llm-wiki/SKILL.md
│   └── skill-creator/SKILL.md
│
├── CLAUDE.md                         # Bootstrap → Claude Code
├── GEMINI.md                         # Bootstrap → Gemini / Antigravity
├── AGENTS.md                         # Bootstrap → Codex / OpenAI
├── .cursor/rules/obsidian-wiki.mdc   # Bootstrap → Cursor
├── .windsurf/rules/obsidian-wiki.md  # Bootstrap → Windsurf
├── .github/copilot-instructions.md   # Bootstrap → GitHub Copilot
│
├── .claude/skills/   → symlinks to .skills/*  (created by setup.sh)
├── .cursor/skills/   → symlinks to .skills/*  (created by setup.sh)
├── .windsurf/skills/ → symlinks to .skills/*  (created by setup.sh)
├── .agents/skills/   → symlinks to .skills/*  (created by setup.sh)
│
├── ~/.gemini/antigravity/skills/  → global symlinks (created by setup.sh)
├── ~/.codex/skills/               → global symlinks (created by setup.sh)
├── ~/.agents/skills/              → global symlinks (OpenClaw + AGENTS.md-aware agents)
│
├── setup.sh                          # One-command agent setup
├── .env.example                      # Configuration template
├── README.md                         # You are here
└── SETUP.md                          # Detailed setup guide
```

## Using from other projects

The whole point is that your wiki should stay up to date as you work across different codebases. You don't want to come back to the obsidian-wiki repo every time. So `setup.sh` installs two global skills that work from any project: `wiki-update` and `wiki-query`.

When you run `bash setup.sh`, two things happen:

1. It writes a config to `~/.obsidian-wiki/config` with your vault path and the repo location. This is how the skills know where to read and write.
2. It symlinks `wiki-update` and `wiki-query` into `~/.claude/skills/` so they're available everywhere.
3. It symlinks all skills into `~/.gemini/antigravity/skills/` for global Gemini/Antigravity access.
4. It symlinks all skills into `~/.codex/skills/` for global Codex access.
5. It symlinks all skills into `~/.agents/skills/` — the discovery path used by OpenClaw and other AGENTS.md-aware agents.

After that, you're in some project, say `~/projects/my-cool-app`, working with Claude. Two commands:

```bash
# You're working on some project
cd ~/projects/my-cool-app
claude

# Write to the wiki: distill what you've learned
> /wiki-update

# Read from the wiki: pull context about anything you've captured before
> /wiki-query what do I know about rate limiting?
```

`/wiki-update` reads your project, figures out what's worth keeping, and distills it into your Obsidian vault. Architecture decisions, patterns you discovered, key concepts, trade-offs you evaluated. It doesn't copy code or dump file listings. It distills the stuff you'd forget in 3 months. Next time you run it from the same project, it checks what changed since last sync (via git log) and only processes the delta.

`/wiki-query` goes the other direction. You're working on something and you want to know what your wiki says about a topic. Maybe you solved a similar problem 2 months ago in a different project and the answer is already in your vault. The agent searches the wiki, reads the relevant pages, and gives you a synthesized answer with citations.

Both skills follow the same Karpathy pattern as everything else. If a concept page already exists in the vault, it merges into it. Everything gets cross-linked with `[[wikilinks]]`, tracked in `.manifest.json`, and logged.

## Contributing

This is early. The skills work but there's a lot of room to make them smarter — better cross-referencing, smarter deduplication, handling larger vaults, new ingest sources. If you've been thinking about this problem or have a workflow that could be a skill, PRs are welcome.

### Adding a new skill

1. Create a folder in `.skills/your-skill-name/`
2. Add a `SKILL.md` with YAML frontmatter (`name`, `description`) and markdown instructions
3. Run `bash setup.sh` to symlink into all agent directories
4. Test with your agent by saying something that matches the description

See `.skills/skill-creator/SKILL.md` for the full guide on writing effective skills.
