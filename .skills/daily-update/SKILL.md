---
name: daily-update
description: >
  Run the daily wiki maintenance cycle: check all source freshness, update the index, and regenerate hot.md.
  Use this skill when the user says "/daily-update", "run the daily update", "update everything", "morning sync",
  "refresh the wiki index", or when triggered by the launchd cron at 9 AM. Also use to set up or verify the
  cron + terminal notification infrastructure for the first time ("set up the daily cron", "install the
  terminal notification", "how do I get the morning reminder?").
---

# Daily Update — Wiki Maintenance Cycle

You run a lightweight maintenance pass over the wiki: check source freshness, refresh the index, update hot.md, and write the state file that the terminal notification reads.

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH` and `OBSIDIAN_WIKI_REPO`.
2. **Derive vault-scoped state dir** — all runtime state is scoped to the resolved vault, not global:
   ```bash
   VAULT_ID=$(echo "$OBSIDIAN_VAULT_PATH" | md5sum 2>/dev/null | cut -c1-8 || md5 -q - <<< "$OBSIDIAN_VAULT_PATH" | cut -c1-8)
   STATE_DIR="$HOME/.obsidian-wiki/state/$VAULT_ID"
   mkdir -p "$STATE_DIR"
   ```
3. Read `$OBSIDIAN_VAULT_PATH/.manifest.json`.

## Modes

### Run Mode (default — triggered by cron or `/daily-update`)

Execute the maintenance cycle:

**Step 1: Source freshness check**

Compare each source in `.manifest.json` against its file's modification time. Classify as:
- **Fresh** — `mtime ≤ ingested_at`
- **Stale** — `mtime > ingested_at` (new content exists, not yet ingested)
- **Missing** — source file no longer exists

**Step 2: Index refresh**

Read `$OBSIDIAN_VAULT_PATH/index.md`. If any pages in the vault are missing from the index (or vice versa), update the index. Use `find $OBSIDIAN_VAULT_PATH -name "*.md" -not -path "*/_*"` to enumerate vault pages, then reconcile against the index.

**Step 3: hot.md update**

Read `hot.md`. If it's >48h old based on its `updated:` frontmatter, regenerate it: read the 10 most recently modified wiki pages and write a fresh ~500-word semantic snapshot of what the wiki covers. This keeps the next session's context warm without a full vault crawl.

**Step 4: Write state**

Write to the vault-scoped `$STATE_DIR` derived in "Before You Start":

```bash
date +%s > "$STATE_DIR/.last_update"
echo "<stale_count>" > "$STATE_DIR/.pending_delta"
echo "$OBSIDIAN_VAULT_PATH" > "$STATE_DIR/.vault_path"
```

**Step 5: Spawn impl-validator**

After the cycle, spawn `impl-validator` as a subagent:

```
impl-validator check:
  goal: "Daily wiki maintenance — index reconciled, hot.md refreshed, state file written"
  artifacts:
    - $OBSIDIAN_VAULT_PATH/index.md
    - $OBSIDIAN_VAULT_PATH/hot.md
    - $STATE_DIR/.last_update
    - $STATE_DIR/.pending_delta
  checks:
    - Does .last_update contain a recent Unix timestamp (within the last 60 seconds)?
    - Does .pending_delta contain a non-negative integer?
    - Does hot.md have an updated: frontmatter field set to today?
    - Does index.md list at least as many pages as exist in the vault?
```

Apply any FAILs before logging.

**Step 6: Log**

Append to `$OBSIDIAN_VAULT_PATH/log.md`:
```
- [TIMESTAMP] DAILY-UPDATE fresh=N stale=N missing=N index_added=N hot_refreshed=true|false
```

**Step 7: Report to user**

```
## Daily Wiki Update

- Sources: N fresh · N stale · N missing
- Index: N pages (N added, N removed)
- hot.md: refreshed / up to date

Stale sources (run to sync):
  /wiki-history-ingest claude   — N sessions since last ingest
  /wiki-history-ingest codex    — N sessions since last ingest
```

### Setup Mode (triggered by "set up the daily cron" or "install terminal notification")

Walk the user through first-time setup:

**Step 1: Verify script exists**

Check that `$OBSIDIAN_WIKI_REPO/scripts/daily-update.sh` exists and is executable. If not, point the user to it.

**Step 2: Install launchd plist**

```bash
# Replace placeholder in plist
sed "s|OBSIDIAN_WIKI_REPO|$OBSIDIAN_WIKI_REPO|g" \
  "$OBSIDIAN_WIKI_REPO/scripts/com.obsidian-wiki.daily-update.plist" \
  > "$HOME/Library/LaunchAgents/com.obsidian-wiki.daily-update.plist"

# Load it
launchctl load "$HOME/Library/LaunchAgents/com.obsidian-wiki.daily-update.plist"
```

**Step 3: Install terminal notification (optional)**

Ask the user: "Do you want a terminal reminder when your wiki is stale? (y/n)" — skip this step if they say no, or if the environment is headless/VPS.

If yes, detect the user's shell and target the right rc file:

```bash
SHELL_NAME=$(basename "$SHELL")   # zsh, bash, fish, etc.
case "$SHELL_NAME" in
  zsh)  RC_FILE="$HOME/.zshrc" ;;
  bash) RC_FILE="$HOME/.bashrc" ;;
  *)    echo "Shell '$SHELL_NAME' not auto-detected. Add the source line manually to your shell rc file." ; return ;;
esac
```

Check if `wiki-notify.sh` is already sourced in that rc file. If not, append:

```bash
echo "" >> "$RC_FILE"
echo "# obsidian-wiki terminal notification" >> "$RC_FILE"
echo "source $OBSIDIAN_WIKI_REPO/scripts/wiki-notify.sh" >> "$RC_FILE"
```

For Fish shell, source syntax is different — provide the manual instruction:
```fish
# Add to ~/.config/fish/config.fish:
bass source $OBSIDIAN_WIKI_REPO/scripts/wiki-notify.sh
# (requires bass plugin, or copy the logic natively)
```

**Step 4: Run the script once**

```bash
bash "$OBSIDIAN_WIKI_REPO/scripts/daily-update.sh"
```

This initializes `$STATE_DIR/.last_update` so the terminal notification works immediately.

**Step 5: Confirm**

Tell the user:
- The cron runs daily at 9 AM (or on next login if missed)
- Terminal notifications appear when the wiki is >20 hours stale
- State is stored in `~/.obsidian-wiki/state/<vault-id>/` — supports multiple vaults independently
- They can run `/daily-update` anytime to force a sync
- Logs go to `/tmp/obsidian-wiki-daily.log`
