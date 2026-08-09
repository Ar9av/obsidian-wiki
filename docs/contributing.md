# Contributing

This is early. The skills work, but there's room to make the brain smarter: better cross-referencing, sharper deduplication, bigger vaults, new ingest sources. If you've been chewing on this problem or have a workflow that could be a skill, PRs are welcome.

## Adding a new skill

1. Create a folder in `.skills/your-skill-name/`
2. Add a `SKILL.md` with YAML frontmatter (`name`, `description`) and markdown instructions
3. Run `bash setup.sh` to symlink it into every agent directory
4. Test by saying something to your agent that matches the description

The `description` is load-bearing — it's the only thing an agent sees when deciding whether your skill is relevant. Write it as a list of the phrases a user would actually say, and state what the skill is *not* for when it's easily confused with a neighbour.

See [`.skills/skill-creator/SKILL.md`](../.skills/skill-creator/SKILL.md) for the full guide, or just ask your agent to run `/skill-creator`.

When you add a skill, also add it to the [skills reference](skills.md) and the routing table in `AGENTS.md`.

## Keeping both READMEs in sync

`README.md` (English) and `README_TW.md` (Traditional Chinese) are **one documentation surface**. Keep headings, examples, links, and user-facing behavior structurally and semantically aligned.

Syncing is advisory, not a merge gate — the `readme-translation-drift` CI job only reports when the translation falls behind. To catch up:

```bash
python tools/check_readme_sync.py
```

It lists the commits that changed `README.md` without a later `README_TW.md` update, plus the pending English diff. Translate and backfill those into `README_TW.md`. Reviewers assess translation quality.

The `docs/` pages are English-only for now.

## Repo conventions

- `.skills/` is the source of truth. Everything else — `.claude/skills/`, `~/.codex/skills/`, and so on — is symlinks created by setup. Never edit a symlinked copy.
- `CLAUDE.md`, `GEMINI.md`, and `.hermes.md` are symlinks to `AGENTS.md`. Edit `AGENTS.md`.
- New config variables belong in three places: `.env.example`, [`docs/configuration.md`](configuration.md), and the skill that reads them.
- New CLI subcommands belong in [`docs/cli.md`](cli.md).

## Tests

```bash
pytest
```

Tests live in `tests/`. Skill behavior that can be asserted deterministically (config resolution, manifest handling, graph math, session indexing) has coverage there; the LLM-driven parts don't.
