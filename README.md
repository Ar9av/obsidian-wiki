# obsidian-wiki

Andrej Karpathy published a [gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) about maintaining a personal knowledge base with LLMs — the "LLM Wiki" pattern. Instead of asking an LLM the same questions over over (or doing RAG every time), you compile knowledge once into interconnected markdown files and keep them current. Obsidian is the viewer, the LLM is the maintainer.

We took that and built a framework around it. No Python scripts, no API keys, no dependencies. The whole thing is a set of markdown skill files that any AI coding agent (Claude Code, Cursor, Windsurf, whatever you use) can read and execute. You point it at your Obsidian vault and tell it what to do.

## How it works

Every ingest runs through four stages:

**1. Ingest** — The agent reads your source material directly. It handles whatever you throw at it: markdown files, PDFs (with page ranges), JSONL conversation exports, plain text logs, chat exports, meeting transcripts. No preprocessing step, no pipeline to run. The agent reads the file the same way it reads code.

**2. Extract** — From the raw source, the agent pulls out concepts, entities, claims, relationships, and open questions. A conversation about debugging a React hook yields a "stale closure" pattern. A research paper yields the key idea and its caveats. A work log yields decisions and their rationale. Noise gets dropped, signal gets kept.

**3. Resolve** — New knowledge gets merged against what's already in the wiki. If a concept page exists, the agent updates it — merging new information, noting contradictions, strengthening cross-references. If it's genuinely new, a page gets created. Nothing is duplicated. Sources are tracked in frontmatter so every claim stays attributable.

**4. Schema** — The wiki schema isn't fixed upfront. It emerges from your sources and evolves as you add more. The agent maintains coherence: categories stay consistent, wikilinks point to real pages, the index reflects what's actually there. When you add a new domain (a new project, a new field of study), the schema expands to accommodate it without breaking what exists.

A `.manifest.json` tracks every source that's been ingested — path, timestamps, which wiki pages it produced. On the next ingest, the agent computes the delta and only processes what's new or changed.

## What we added on top of Karpathy's pattern

**Delta tracking.** A manifest tracks every source file that's been ingested: path, timestamps, which wiki pages it produced. When you come back later, it computes the delta and only processes what's new or changed. You're not re-ingesting your entire document library every time.

**Project-based organization.** Knowledge gets filed under projects when it's project-specific, globally when it's not. Both are cross-referenced with wikilinks. If you're working on 10 different codebases, each one gets its own space in the vault.

**Archive and rebuild.** When the wiki drifts too far from your sources, you can archive the whole thing (timestamped snapshot, nothing lost) and rebuild from scratch. Or restore any previous archive.

**Ingest anything.** Documents, PDFs, Claude Code conversation history (`~/.claude`), ChatGPT exports, Slack logs, meeting transcripts, raw text. There's a specific skill for Claude history that understands the JSONL format and memory files, and a catch-all skill that figures out whatever format you throw at it.

**Audit and lint.** Find orphaned pages, broken wikilinks, stale content, contradictions, missing frontmatter. See a dashboard of what's been ingested vs what's pending.

## Setup

```bash
git clone https://github.com/Ar9av/obsidian-wiki.git
cd obsidian-wiki
cp .env.example .env
```

Set your vault path in `.env`:

```
OBSIDIAN_VAULT_PATH=/path/to/your/vault
```

That's it. Open the project in your coding agent and say "set up my wiki." See [SETUP.md](SETUP.md) for the full details.

## Skills

Everything lives in `.skills/`. Each skill is a markdown file the agent reads when triggered:

| Skill | What it does |
|---|---|
| `obsidian-setup` | Initialize vault structure |
| `obsidian-ingest` | Distill documents into wiki pages |
| `claude-history-ingest` | Mine your `~/.claude` conversations and memories |
| `data-ingest` | Ingest any text — chat exports, logs, transcripts |
| `wiki-status` | Show what's ingested, what's pending, the delta |
| `wiki-rebuild` | Archive, rebuild from scratch, or restore |
| `obsidian-query` | Answer questions from the wiki |
| `obsidian-lint` | Find broken links, orphans, contradictions |
| `llm-wiki` | The core pattern and architecture reference |
| `skill-creator` | Create new skills |

## Contributing

This is early. The skills work but there's a lot of room to make them smarter — better cross-referencing, smarter deduplication, handling larger vaults, new ingest sources. If you've been thinking about this problem or have a workflow that could be a skill, PRs are welcome.
