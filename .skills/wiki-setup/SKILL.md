---
name: wiki-setup
description: >
  Initialize a new Obsidian wiki vault with the correct structure, special files, and configuration.
  Use this skill when the user wants to set up a new wiki from scratch, initialize the vault structure,
  create the .env file, or says things like "set up my wiki", "initialize obsidian", "create a new vault",
  "get started with the wiki". Also use when the user needs to reconfigure their existing vault or
  fix a broken setup.
---

# Obsidian Setup — Vault Initialization

You are setting up a new Obsidian wiki vault (or repairing an existing one).

## Step 1: Create .env

If `.env` doesn't exist, create it from `.env.example`. Ask the user for:

1. **Where should the vault live?** → `OBSIDIAN_VAULT_PATH`
   - Default: `~/Documents/obsidian-wiki-vault`
   - Must be an absolute path (after expansion)

2. **Where are your source documents?** → `OBSIDIAN_SOURCES_DIR`
   - Can be multiple paths, comma-separated
   - Default: `~/Documents`
   - Local git repo clones (public or private, any host) can be listed here too — clone
     the repo locally first, then add its path. See "Ingesting Git Repositories" in
     `wiki-ingest/SKILL.md` for how repo sources are handled.

3. **Want to import Claude history?** → `CLAUDE_HISTORY_PATH`
   - Default: auto-discovers from `~/.claude`
   - Set explicitly if Claude data is elsewhere

4. **Have QMD installed?** → `QMD_WIKI_COLLECTION` / `QMD_PAPERS_COLLECTION` / `QMD_TRANSPORT`
   - Optional. Enables semantic search in `wiki-query` and source discovery in `wiki-ingest`.
   - Default to `QMD_TRANSPORT=mcp` unless the user wants the agent to call the local `qmd` CLI directly.
   - If using CLI mode, set `QMD_CLI_SEARCH_MODE=quality` by default; suggest `balanced` if reranking is too slow.
   - If unsure, skip for now — both skills fall back to `Grep` automatically.
   - Install instructions: see `.env.example` (QMD section).
   - **If `QMD_WIKI_COLLECTION` is set, verify the collection excludes `_raw/`.** The wiki
     collection and papers collection must stay disjoint — `wiki-query` cites them as
     separate layers (compiled knowledge vs. raw staging), and `OBSIDIAN_VAULT_PATH` contains
     `_raw/`, so a plain `qmd collection add <vault>` silently merges the two.
     Read `~/.config/qmd/index.yml`, find the entry for `$QMD_WIKI_COLLECTION`, and check its
     `ignore` list includes `_raw/**` (and ideally `log.md`, which has no semantic value). If
     the collection doesn't exist yet, create it (`qmd collection add "$OBSIDIAN_VAULT_PATH"
     --name <collection-name>`), then add the `ignore` block to `index.yml` by hand — `qmd`
     has no `--ignore` flag and refuses a second `collection add` on a path that already has
     one, so editing the YAML is the only way to scope it. Run `qmd update` after editing.
     If the collection already exists without the `ignore` block, tell the user their
     wiki collection is indexing `_raw/` (including `_raw/_archived/` drafts left behind by
     `wiki-ingest`) and offer to add the `ignore` block and re-run `qmd update`.

5. **Token budget warning threshold?** → `WIKI_TOKEN_WARN_THRESHOLD`
   - Default: `100000` (warn when full-wiki read would cost > 100K tokens)
   - Set to `0` to disable the warning entirely
   - `wiki-status` shows a token footprint table and emits this warning automatically

6. **Enable staged writes?** → `WIKI_STAGED_WRITES`
   - Default: unset / `false` (pages written directly to their final location)
   - Set to `true` for team wikis, high-stakes domains, or any vault where the human wants final say on every LLM-written page
   - When enabled: all new/updated pages land in `_staging/` first; run `/wiki-stage-commit` to review and promote them
   - `wiki-status` shows a "Staged writes pending" count when files are waiting

After resolving config, assign the global config directory with the exact
`obsidian_wiki_config_dir` algorithm from the Config Resolution Protocol in
`.skills/llm-wiki/SKILL.md`. Create the shared writing profile only when it does not
already exist. Preserve an existing `$GLOBAL_CONFIG_DIR/WRITING.md`; never overwrite it
and do not ask additional writing-style questions.

Use `OBSIDIAN_WIKI_REPO` when it was loaded from config. When it is absent, derive the
absolute repository/data root from this loaded skill's absolute path, distinguishing the
packaged `<root>/skills/wiki-setup/SKILL.md` layout from the source
`<root>/.skills/wiki-setup/SKILL.md` layout. Then check both canonical template layouts:

- Packaged install: `<root>/skills/llm-wiki/references/WRITING.md`
- Source checkout: `<root>/.skills/llm-wiki/references/WRITING.md`

```bash
GLOBAL_CONFIG_DIR="$(obsidian_wiki_config_dir)"
mkdir -p "$GLOBAL_CONFIG_DIR"

SKILL_FILE="<absolute path of this loaded wiki-setup/SKILL.md>"
SKILL_DIR="$(cd "$(dirname "$SKILL_FILE")" && pwd)"
if [ -n "${OBSIDIAN_WIKI_REPO:-}" ]; then
  WIKI_ROOT="${OBSIDIAN_WIKI_REPO%/}"
else
  case "$SKILL_DIR" in
    */.skills/wiki-setup) WIKI_ROOT="${SKILL_DIR%/.skills/wiki-setup}" ;;
    */skills/wiki-setup) WIKI_ROOT="${SKILL_DIR%/skills/wiki-setup}" ;;
    *) echo "Cannot derive writing-profile template root from $SKILL_DIR" >&2; exit 1 ;;
  esac
fi

WRITING_TEMPLATE=""
for candidate in \
  "$WIKI_ROOT/skills/llm-wiki/references/WRITING.md" \
  "$WIKI_ROOT/.skills/llm-wiki/references/WRITING.md"
do
  if [ -f "$candidate" ]; then
    WRITING_TEMPLATE="$candidate"
    break
  fi
done
[ -n "$WRITING_TEMPLATE" ] || { echo "Writing profile template not found under $WIKI_ROOT" >&2; exit 1; }

WRITING_PROFILE="$GLOBAL_CONFIG_DIR/WRITING.md"
if [ ! -e "$WRITING_PROFILE" ]; then
  cp "$WRITING_TEMPLATE" "$WRITING_PROFILE"
fi
```

## Step 2: Create Vault Directory Structure

```bash
mkdir -p "$OBSIDIAN_VAULT_PATH"/{concepts,entities,skills,references,synthesis,journal,projects,_archives,_raw,_staging,.obsidian}
```

- `.obsidian/` — Obsidian's own config. Creates vault recognition.
- `projects/` — Per-project knowledge (populated during ingest).
- `_archives/` — Stores wiki snapshots for rebuild/restore operations.
- `_raw/` — Staging area for unprocessed drafts. Drop rough notes here; `wiki-ingest` will promote them to proper wiki pages and move the originals into `_raw/_archived/` (created on first use).
- `_staging/` — Review queue for LLM-written pages when `WIKI_STAGED_WRITES=true`. Pages here are not visible in Obsidian's graph until promoted via `/wiki-stage-commit`.

## Step 3: Create Special Files

### index.md

```markdown
---
title: Wiki Index
---

# Wiki Index

*This index is automatically maintained. Last updated: TIMESTAMP*

## Concepts

*No pages yet. Use `wiki-ingest` to add your first source.*

## Entities

## Skills

## References

## Synthesis

## Journal
```

### log.md

```markdown
---
title: Wiki Log
---

# Wiki Log

- [TIMESTAMP] INIT vault_path="OBSIDIAN_VAULT_PATH" categories=concepts,entities,skills,references,synthesis,journal
```

### hot.md

```markdown
---
title: Hot Cache
updated: TIMESTAMP
---

# Hot Cache

*A ~500-word semantic snapshot of recent activity. Updated after every major write operation.*

## Recent Activity

- [TIMESTAMP] INIT — vault created at OBSIDIAN_VAULT_PATH

## Active Threads

*None yet — start ingesting sources to populate.*

## Key Takeaways

*None yet.*

## Flagged Contradictions

*None yet.*
```

### .manifest.json

Create an empty manifest so ingest skills have a tracking file to append to and
`obsidian-wiki doctor` reports the vault as complete (it treats `.manifest.json`
as a required core file):

```bash
printf '{}\n' > "$OBSIDIAN_VAULT_PATH/.manifest.json"
```

## Step 4: Create .obsidian Configuration

Create minimal Obsidian config for a good out-of-box experience:

### .obsidian/app.json
```json
{
  "strictLineBreaks": false,
  "showFrontmatter": false,
  "defaultViewMode": "preview",
  "livePreview": true
}
```

### .obsidian/appearance.json
```json
{
  "baseFontSize": 16
}
```

## Step 5: Recommend Obsidian Plugins

Tell the user about these recommended community plugins (they install manually):

1. **Dataview** — Query page metadata, create dynamic tables. Essential for a wiki.
2. **Graph Analysis** — Enhanced graph view for exploring connections.
3. **Templater** — If they want to create pages manually using templates.
4. **Obsidian Git** — Auto-backup the vault to a git repo.

## Step 6: Verify Setup

Run a quick sanity check:
- [ ] Vault directory exists with: `concepts/`, `entities/`, `skills/`, `references/`, `synthesis/`, `journal/`, `projects/`, `_archives/`, `_raw/`
- [ ] `index.md` exists at vault root
- [ ] `log.md` exists at vault root
- [ ] `hot.md` exists at vault root
- [ ] `.manifest.json` exists at vault root (empty `{}` is fine)
- [ ] `.env` has `OBSIDIAN_VAULT_PATH` set
- [ ] `.obsidian/` directory exists
- [ ] `_staging/` directory exists (required even when `WIKI_STAGED_WRITES` is not set — created on setup for future use)
- [ ] `WRITING_PROFILE` exists at the resolved global config directory
- [ ] Source directories (if configured) exist and are readable

Report the results, including the resolved absolute `WRITING_PROFILE` path, and tell the user they can now:
1. Open the vault in Obsidian (File → Open Vault → select the directory)
2. Run `wiki-status` to see what's available to ingest
3. Run `wiki-ingest` to add their first sources
4. Run `claude-history-ingest` to mine their Claude conversations
5. Run `codex-history-ingest` to mine their Codex sessions (if they use Codex)
6. Run `wiki-status` again anytime to check the delta

## Optional: Install the Stop Hook (Auto-Capture)

Ask the user: **"Want to auto-capture findings at session end?"**

If yes, install the Stop hook into their global Claude Code settings so that every session
with meaningful work automatically prompts `/wiki-capture --quick` before closing.

**What the hook does:** reads the session transcript on Stop, counts file edits and shell
calls, and if significant work happened, asks Claude to run `/wiki-capture --quick` once.
The `wiki-capture` quick-mode KEEP/SKIP gate prevents noise — routine or
inconclusive sessions are skipped automatically.

**Installation steps:**

1. Find the obsidian-wiki repo path. If `OBSIDIAN_WIKI_REPO` is set in config, use that.
   Otherwise, check common locations: `~/Documents/projects/obsidian-wiki`, `~/obsidian-wiki`,
   or ask the user.

2. Locate the `wiki-stop-capture.sh` script. Its path differs between a pip/uv install and a
   source checkout, so check both layouts under `<REPO_PATH>` and use the first that exists:

   - `<REPO_PATH>/hooks/wiki-stop-capture.sh` — packaged install (`OBSIDIAN_WIKI_REPO`
     points at the bundled `_data/` dir, which ships the hook under `hooks/`).
   - `<REPO_PATH>/.claude/hooks/wiki-stop-capture.sh` — source checkout.

   If neither exists (e.g. an older wheel that predates bundling the hook), fetch the canonical
   copy to a stable location and point at that instead. Use the global config dir from the
   Config Resolution Protocol in `llm-wiki/SKILL.md` (XDG-style `~/.config/obsidian-wiki` by
   default, or the legacy `~/.obsidian-wiki` if that already exists):

   ```bash
   CONFIG_DIR="$( [[ -d "$HOME/.obsidian-wiki" && ! -e "${XDG_CONFIG_HOME:-$HOME/.config}/obsidian-wiki" ]] && echo "$HOME/.obsidian-wiki" || echo "${XDG_CONFIG_HOME:-$HOME/.config}/obsidian-wiki" )"
   mkdir -p "$CONFIG_DIR/hooks"
   curl -fsSL https://raw.githubusercontent.com/Ar9av/obsidian-wiki/main/.claude/hooks/wiki-stop-capture.sh \
     -o "$CONFIG_DIR/hooks/wiki-stop-capture.sh"
   chmod +x "$CONFIG_DIR/hooks/wiki-stop-capture.sh"
   ```

   Use the resolved absolute path as `<HOOK_PATH>` below.

3. Merge the hook entry into `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash <HOOK_PATH>"
          }
        ]
      }
    ]
  }
}
```

   If `~/.claude/settings.json` already exists and has a `hooks.Stop` array, **append** the new
   entry rather than replacing — don't clobber existing hooks.

   > **Note — expect a duplicate nudge inside this repo.** The obsidian-wiki repo ships its own
   > git-tracked `.claude/settings.json` registering the same Stop hook at a relative path. Claude
   > Code *merges* project-level and user-level hook config rather than letting one override the
   > other, so sessions ending inside the repo itself fire both registrations. This is expected and
   > harmless — the hook claims an atomic per-session sentinel, so only one nudge is emitted. Leave
   > both in place: removing the project entry dirties a tracked framework file and disables capture
   > for anyone who clones the repo without doing the global install.

4. Confirm: "Stop hook installed. Claude Code will prompt `/wiki-capture --quick` at the
   end of any session where you write files or run ≥ 4 shell commands."

**To uninstall later:** remove the hook entry from `~/.claude/settings.json` or set
`HIVEMIND_CAPTURE=false` in your shell to skip capture for a single session.

## Optional: Configure GitHub Sync

Ask the user: **"Want to sync your vault to a private GitHub repo?"**

The vault is plain markdown, so pushing it to git gets you version history, backup, and
cross-device sync for free. This is opt-in — skip it if the user declines or has no repo ready.

If yes:

1. Ask for the repo URL (e.g. `https://github.com/you/my-wiki.git`). Recommend it be **private**
   if the vault holds personal notes.
2. Run the CLI, which handles `git init`, a default `.gitignore`, and wiring the `origin` remote —
   this is the same code path `obsidian-wiki setup`'s interactive prompt and `setup.sh` use, so
   there's one implementation to keep correct (see issue #153 for why that matters):
   ```bash
   obsidian-wiki sync-setup "<repo-url>" --vault "$OBSIDIAN_VAULT_PATH"
   ```
   If the `obsidian-wiki` binary isn't on PATH (source checkout without an install), run it from
   the repo instead: `PYTHONPATH="$OBSIDIAN_WIKI_REPO" python3 -m obsidian_wiki.cli sync-setup ...`
   using whichever of `OBSIDIAN_WIKI_REPO` or a local checkout path is available.
3. Tell the user they can run `obsidian-wiki sync` any time afterward to commit and push pending
   vault changes (stages everything, commits with a timestamp, pushes). There's no config file to
   check for sync status — the vault's own `git remote` is the source of truth.

## Optional: Refresh QMD After Setup

If `QMD_WIKI_COLLECTION` is configured and the local QMD CLI is available, run `qmd update` after the initial vault files exist so the fresh vault is immediately queryable. No embedding pass is usually needed at setup time because the vault starts empty, so a plain update is enough unless you have already populated pages. Before running it, confirm the `_raw/` exclusion described in Step 1.4 is in place — otherwise this update indexes the (currently empty) staging directory into the wiki collection too, and every future draft dropped there joins it silently.
