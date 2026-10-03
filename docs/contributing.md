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

## Keeping the READMEs in sync

`README.md` (English) and every `README_<LANG>.md` translation — today `README_TW.md` (Traditional Chinese) — are **one documentation surface**. Keep headings, examples, links, and user-facing behavior structurally and semantically aligned.

Syncing is advisory, not a merge gate — the `readme-translation-drift` CI job only reports when the translation falls behind. To catch up:

```bash
python tools/check_readme_sync.py
```

For each translation, it lists the commits that changed `README.md` without a later update to that translation, plus the pending English diff. Translate and backfill those changes. Reviewers assess translation quality.

The `docs/` pages are English-only for now.

## Adding a README translation

New languages are one of the easiest ways to contribute, and no code changes are needed. The drift checker finds every tracked `README_<LANG>.md` on its own.

1. **Copy** `README.md` to `README_<LANG>.md` at the repo root, with an upper-case code: `README_JA.md`, `README_KO.md`, `README_ES.md`, `README_CN.md` (Simplified Chinese; `README_TW.md` is Traditional).
2. **Translate the prose only.** Leave commands, code blocks, slash commands (`/wiki-ingest`), skill and file names, and URLs exactly as they are. User-facing phrases agents match on, like **"set up my wiki"**, stay in English, with a translation alongside if it helps (see how `README_TW.md` does it).
3. **Keep the structure identical:** the same headings in the same order, the same tables, the same images and links. A reader switching languages should land in the same place.
4. **Add the language to the switcher** near the top of `README.md` and of every existing translation, e.g. `English | <a href="…/README_TW.md">繁體中文</a> | <a href="…/README_JA.md">日本語</a>`. A test checks that every translation is linked from `README.md`.
5. **Run the checks:**

   ```bash
   python tools/check_readme_sync.py
   python -m pytest tests/test_readme_sync.py
   ```

6. **Open a PR.** Say in the description whether you're a native or fluent speaker. A second speaker's review is welcome but not required to merge.

After that, the `readme-translation-drift` job reports when your translation falls behind the English README. Backfilling later is welcome, and drift never blocks a merge.

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
