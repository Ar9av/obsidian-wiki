---
name: daily-update
description: >
  Run the daily wiki maintenance cycle: check all source freshness, update the index, and regenerate hot.md.
  Use this skill when the user says "/daily-update", "run the daily update", "update everything", "morning sync",
  "refresh the wiki index", or when triggered by the scheduled 9 AM run (launchd, systemd timer, or cron). Also use to set up or verify the
  cron + terminal notification infrastructure for the first time ("set up the daily cron", "install the
  terminal notification", "how do I get the morning reminder?").
---

# Daily Update — Wiki Maintenance Cycle

You run a lightweight maintenance pass over the wiki: check source freshness, refresh the index, update hot.md, and write the state file that the terminal notification reads.

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (inline `@name` override → walk up CWD for `.env` → global config → prompt setup). This gives `OBSIDIAN_VAULT_PATH` and `OBSIDIAN_WIKI_REPO`.
2. **Derive vault-scoped state dir** — all runtime state is scoped to the resolved vault, not global:
   ```bash
   VAULT_ID=$(echo "$OBSIDIAN_VAULT_PATH" | md5sum 2>/dev/null | cut -c1-8 || md5 -q - <<< "$OBSIDIAN_VAULT_PATH" | cut -c1-8)
   STATE_DIR="$(obsidian_wiki_config_dir)/state/$VAULT_ID"
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

```bash
obsidian-wiki memory index --vault "$OBSIDIAN_VAULT_PATH"
```

This reconciles `index.md` against the pages on disk under the memory lock — missing entries added, entries for deleted pages removed, the owner's own sections left untouched. Note `added`/`removed` from the output for the log line in Step 6. Do not enumerate pages with `find` and edit the index by hand.

**Step 3: hot.md update**

```bash
obsidian-wiki memory hot --vault "$OBSIDIAN_VAULT_PATH"
```

Recent Activity, Active Threads, and Flagged Contradictions are regenerated from the log, the todo index, and page frontmatter; `## Key Takeaways` carries across unchanged. If the takeaways are older than ~48h *and* the vault has changed materially since, refresh them: read the 10 most recently updated pages and pass a fresh ~500-word snapshot with `--takeaways -` on stdin. Otherwise leave them — a rebuild without new takeaways is cheap and correct.

If either command reports the vault is **unmigrated**, stop and tell the user to run `obsidian-wiki memory migrate` (preview) then `--apply`; do not fall back to hand-editing.

**Step 4: Write state**

Write to the vault-scoped `$STATE_DIR` derived in "Before You Start":

```bash
date +%s > "$STATE_DIR/.last_update"
echo "<stale_count>" > "$STATE_DIR/.pending_delta"
echo "$OBSIDIAN_VAULT_PATH" > "$STATE_DIR/.vault_path"
```

**Step 4a: Scheduled health check (wiki-lint)**

`LINT_SCHEDULE` (default `weekly`) controls how often this cycle also runs `wiki-lint`:

- `manual` — never auto-run; skip this step entirely.
- `daily` — run `wiki-lint` every cycle.
- `weekly` — run `wiki-lint` only if `$STATE_DIR/.last_lint` is missing or older than 7 days.

```bash
LINT_SCHEDULE="${LINT_SCHEDULE:-weekly}"
NOW=$(date +%s)
LAST_LINT=$(cat "$STATE_DIR/.last_lint" 2>/dev/null || echo 0)
```

If the schedule says to run, invoke the `wiki-lint` skill, then record the run:

```bash
date +%s > "$STATE_DIR/.last_lint"
```

Fold its summary (broken links, orphans, stale pages found) into Step 7's report as a `Health check:` line; omit the line entirely on a cycle where lint didn't run.

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
obsidian-wiki memory log DAILY-UPDATE fresh=<N> stale=<N> missing=<N> index_added=<N> hot_refreshed=<true|false> lint=<ran|skipped>
```

**Step 7: Report to user**

```
## Daily Wiki Update

- Sources: N fresh · N stale · N missing
- Index: N pages (N added, N removed)
- hot.md: refreshed / up to date
- Health check: N broken links, N orphans, N stale pages (omit this line if lint didn't run this cycle)

Stale sources (run to sync):
  /wiki-history-ingest claude   — N sessions since last ingest
  /wiki-history-ingest codex    — N sessions since last ingest
```

### Setup Mode (triggered by "set up the daily cron" or "install terminal notification")

Walk the user through first-time setup:

**Step 1: Verify script exists**

Check that `$OBSIDIAN_WIKI_REPO/scripts/daily-update.sh` exists and is executable. If not, point the user to it.

**Step 2: Install the scheduler** — pick by platform (`uname -s`).

macOS (`Darwin`) — launchd:

```bash
# Replace placeholder in plist
sed "s|OBSIDIAN_WIKI_REPO|$OBSIDIAN_WIKI_REPO|g" \
  "$OBSIDIAN_WIKI_REPO/scripts/com.obsidian-wiki.daily-update.plist" \
  > "$HOME/Library/LaunchAgents/com.obsidian-wiki.daily-update.plist"

# Load it
launchctl load "$HOME/Library/LaunchAgents/com.obsidian-wiki.daily-update.plist"
```

Linux with systemd (`systemctl --user` works) — a user timer:

```bash
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
sed "s|OBSIDIAN_WIKI_REPO|$OBSIDIAN_WIKI_REPO|g" \
  "$OBSIDIAN_WIKI_REPO/scripts/obsidian-wiki-daily-update.service" \
  > "$UNIT_DIR/obsidian-wiki-daily-update.service"
cp "$OBSIDIAN_WIKI_REPO/scripts/obsidian-wiki-daily-update.timer" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now obsidian-wiki-daily-update.timer
```

On a headless server, user timers only run while the user is logged in unless lingering is on — suggest `sudo loginctl enable-linger "$USER"`.

Anything else (no systemd, containers, WSL without systemd) — crontab. Append this line via `crontab -e`, skipping it if an `obsidian-wiki` daily-update line is already there:

```cron
0 9 * * * /bin/bash "$OBSIDIAN_WIKI_REPO/scripts/daily-update.sh" >> /tmp/obsidian-wiki-daily.log 2>&1
```

Write the literal repo path in place of `$OBSIDIAN_WIKI_REPO` — cron does not load your shell env.

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
- The scheduler runs daily at 9 AM (launchd and the systemd timer catch up on the next login/boot if missed; plain cron does not)
- `wiki-lint` health checks run on the `LINT_SCHEDULE` cadence (default `weekly`) as part of that cycle — set `LINT_SCHEDULE=daily` or `manual` in `.env` to change it
- Terminal notifications appear when the wiki is >20 hours stale
- State is stored in `<global config dir>/state/<vault-id>/` (XDG-style `~/.config/obsidian-wiki` by default, or the legacy `~/.obsidian-wiki` if that already exists) — supports multiple vaults independently
- They can run `/daily-update` anytime to force a sync
- Logs go to `/tmp/obsidian-wiki-daily.log` (launchd, cron) or `journalctl --user -u obsidian-wiki-daily-update` (systemd)

## QMD Refresh After Vault Writes

QMD is a search index, not the source of truth. If `$QMD_WIKI_COLLECTION` is empty or unset, skip this step. Run it only after this skill has written or rewritten vault markdown. If QMD refresh fails, do not roll back the vault changes; report the QMD status separately.

Use `$QMD_CLI` if set; otherwise use `qmd`.

```bash
${QMD_CLI:-qmd} update
```

If the output says vectors are needed or embeddings may be stale, run:

```bash
${QMD_CLI:-qmd} embed
```

Verify the collection with either:

```bash
${QMD_CLI:-qmd} ls "$QMD_WIKI_COLLECTION"
```

or, when a specific page path is known:

```bash
${QMD_CLI:-qmd} get "qmd://$QMD_WIKI_COLLECTION/<page>.md" -l 5
```

Record one of:
- `QMD refreshed: update + embed + verified`
- `QMD refreshed: update only + verified`
- `QMD skipped: QMD_WIKI_COLLECTION unset`
- `QMD skipped: qmd CLI unavailable`
- `QMD failed: <short error summary>`
