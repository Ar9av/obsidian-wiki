<h1 align="center">obsidian-wiki</h1>

<p align="center"><b>A digital brain you grow with your AI agent.</b></p>

<p align="center">
  It remembers what you figure out, connects it to what you already know,<br>
  and answers when you ask.
</p>

<p align="center">
  <a href="https://pypi.org/project/obsidian-wiki/"><img src="https://img.shields.io/pypi/v/obsidian-wiki?color=blue" alt="PyPI" /></a>
  <a href="https://deepwiki.com/Ar9av/obsidian-wiki"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" /></a>
  <a href="https://github.com/ar9av/obsidian-wiki/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome" /></a>
  <a href="https://x.com/_ar9av"><img src="https://img.shields.io/badge/@__ar9av-black?logo=x&logoColor=white" alt="X" /></a>
</p>

<p align="center">
  <img width="768" alt="obsidian-wiki" src="https://github.com/user-attachments/assets/b44cf63b-3197-4fb1-8e18-dbc9a39f27a7" />
</p>

<p align="center">
  English | <a href="https://github.com/Ar9av/obsidian-wiki/blob/main/README_TW.md">繁體中文</a>
</p>

---

You solve a hard problem on a Tuesday. Three months later, in a different repo, you solve it again from scratch — because the answer lived in a chat log you'll never find.

This fixes that. Point it at a folder, tell your agent what to remember, and it compiles what you learn into interconnected markdown you own. The pattern comes from Andrej Karpathy's [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): compile knowledge once and keep it current, instead of asking an LLM the same questions forever or re-running RAG every time.

**Your second brain. Your AI agent is how you grow it.**

Every skill here is a markdown file that any agent — Claude Code, Cursor, Codex, Windsurf, Gemini CLI, and [a dozen more](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/agents.md) — reads and runs. No runtime, no API keys, no vendor.

## 60 seconds

```bash
pip install obsidian-wiki
obsidian-wiki setup --vault ~/brain
```

Then open any project in your agent and say **"set up my wiki"**.

Prefer not to touch a terminal? Give your agent this and it'll do the whole thing:

```text
https://github.com/Ar9av/obsidian-wiki — set up my wiki
```

Other paths — `git clone`, Skills CLI, multiple vaults → **[Installation](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/installation.md)**

## What you actually do

**Feed it.** Anything text-shaped: docs, PDFs, chat exports, meeting transcripts, screenshots, URLs.

```text
/wiki-ingest ~/research
/wiki-update                        # distill the repo you're standing in
/wiki-capture                       # save this conversation
/wiki-history-ingest claude         # mine everything you've ever asked Claude
```

**Ask it.** Answers come back with `[[wikilink]]` citations, not vibes.

```text
/wiki-query what do I know about rate limiting?
/wiki-narrate MCP security          # a cited briefing on a topic
/wiki-digest week                   # what did I learn this week?
```

**Find that session you can't name.**

```bash
obsidian-wiki sessions-build
obsidian-wiki sessions-query "the auth bug with the weird retry loop"
```

**Keep it honest.** The vault gets messy on its own; these clean it.

```text
/wiki-lint            # broken links, orphans, contradictions
/wiki-dedup           # "RSC" and "React Server Components" are one page now
/cross-linker         # weave new pages into the graph
/wiki-status          # what's ingested, what's pending, where the hubs are
```

All 39 skills → **[Skills Reference](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/skills.md)**

## See it

Open the vault in Obsidian and hit the graph view (Cmd/Ctrl+P → "Open graph view"). Say **"color my graph"** and it tints nodes by tag, category, or visibility.

<p align="center">
  <img width="900" alt="obsidian-wiki graph view" src="https://github.com/user-attachments/assets/f2980840-4b5b-438a-8264-5ad1de42f483" />
</p>

Or export the whole graph to `graph.json`, GraphML (Gephi/yEd), Neo4j Cypher, or a self-contained interactive `graph.html`.

## Why this and not a notes folder

- **It compiles, it doesn't accumulate.** New knowledge merges into existing pages. Contradictions get flagged. Nothing gets duplicated.
- **It only reads what changed.** A manifest tracks every source ingested, so the second run processes the delta — not your whole library again.
- **You can tell knowledge from guessing.** Every claim is tagged `extracted`, `^[inferred]`, or `^[ambiguous]`, and lint flags pages drifting into speculation.
- **Queries stay cheap as it grows.** Titles, tags, and summaries get read before page bodies. 20 pages or 2000, roughly the same cost.
- **It's yours.** Plain markdown in a folder. Push it to a private repo, open it in Obsidian, grep it, delete it. No service, no lock-in, nothing leaves your machine.
- **Works where you already work.** One `.skills/` directory, symlinked into every agent you use.

More → **[Architecture](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/architecture.md)**

## Documentation

| | |
|---|---|
| **[Installation](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/installation.md)** | pip, clone, agent-driven setup, multiple vaults |
| **[Skills Reference](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/skills.md)** | All 39 skills and their slash commands |
| **[Agent Compatibility](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/agents.md)** | The full matrix + per-agent manual setup |
| **[CLI Reference](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/cli.md)** | Every `obsidian-wiki` subcommand |
| **[Configuration](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/configuration.md)** | Config vars, QMD semantic search, `_raw/` staging, GitHub sync |
| **[Architecture](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/architecture.md)** | The four ingest stages, vault structure, what we added to Karpathy's pattern |
| **[Session Brain](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/session-brain.md)** | Topic graph over your agent session history |
| **[Contributing](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/contributing.md)** | Adding skills, keeping the READMEs in sync |

## Contributing

This is early. The skills work, but there's room to make the brain smarter — better cross-referencing, sharper deduplication, bigger vaults, new ingest sources. If you have a workflow that could be a skill, [PRs are welcome](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/contributing.md).

## License

[MIT](https://github.com/Ar9av/obsidian-wiki/blob/main/LICENSE)
