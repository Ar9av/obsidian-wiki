---
name: gstack-learnings-watch
description: >
  Set up automatic background watching of gstack learnings so the wiki stays current without
  manual syncing (macOS only — uses launchd; Linux/Windows users can adapt the script with
  cron, systemd, or Task Scheduler). Installs an agent that checks for new learnings.jsonl
  entries on a schedule and stages them for the next wiki session. Use when the user says
  "watch gstack learnings", "auto-sync gstack", "set up automatic learning sync", "keep wiki
  updated automatically", or "I don't want to manually sync". Also use to check watch status,
  change the schedule, or remove the watcher.
---

# gstack Learnings Watch

Installs a lightweight macOS launchd agent that periodically checks for new gstack learnings
and stages them for your next wiki session. When new learnings are found, it writes a
`.gstack-sync-pending` marker to your vault. The next time you run `gstack-learnings-sync`
(or check `gstack-learnings-watch` status), the marker tells you new entries are ready.

No external dependencies. No Claude required to run the watch itself.

## Commands

Match the user's intent:

| User says | Action |
|---|---|
| "set up" / "install" / "enable" | → **Install** |
| "status" / "is it running" | → **Check status** |
| "change interval" / "every N hours" | → **Update interval** |
| "stop" / "disable" / "remove" | → **Uninstall** |

---

## Install

### Step 1: Read config

```bash
cat ~/.obsidian-wiki/config
```

Get `OBSIDIAN_VAULT_PATH`. If missing, tell the user to run `bash setup.sh` first.

Ask the user (or default to 2 hours if they don't specify):
> "How often should the watcher check for new learnings? (default: every 2 hours)"

### Step 2: Write the watcher script

Create `~/.obsidian-wiki/gstack-watch.sh`:

```bash
#!/bin/bash
# gstack-learnings-watch — checks for new learnings and stages them
# Installed by obsidian-wiki gstack-learnings-watch skill

set -e

VAULT_PATH="VAULT_PATH_PLACEHOLDER"
GSTACK_DIR="$HOME/.gstack/projects"
MANIFEST="$VAULT_PATH/.manifest.json"
PENDING="$VAULT_PATH/.gstack-sync-pending"
MARKER="$HOME/.obsidian-wiki/.watch-last-run"

# Get last sync timestamp from manifest (or epoch if absent)
if command -v python3 &>/dev/null; then
  LAST_SYNC=$(python3 -c "
import json, sys
try:
  d = json.load(open('$MANIFEST'))
  print(d.get('gstack_learnings_last_sync', '1970-01-01T00:00:00.000Z'))
except:
  print('1970-01-01T00:00:00.000Z')
" 2>/dev/null || echo "1970-01-01T00:00:00.000Z")
else
  LAST_SYNC="1970-01-01T00:00:00.000Z"
fi

# Check each learnings.jsonl for entries newer than LAST_SYNC
NEW_ENTRIES=0
for f in "$GSTACK_DIR"/*/learnings.jsonl; do
  [ -f "$f" ] || continue
  COUNT=$(python3 -c "
import json, sys
last = '$LAST_SYNC'
count = 0
for line in open('$f'):
  line = line.strip()
  if not line: continue
  try:
    entry = json.loads(line)
    if entry.get('ts','') > last:
      count += 1
  except:
    pass
print(count)
" 2>/dev/null || echo "0")
  NEW_ENTRIES=$((NEW_ENTRIES + COUNT))
done

# If new entries exist, write a pending marker
if [ "$NEW_ENTRIES" -gt 0 ]; then
  echo "$NEW_ENTRIES new gstack learnings found at $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$PENDING"
fi

# Update last-run marker
date -u +%Y-%m-%dT%H:%M:%SZ > "$MARKER"
```

Replace `VAULT_PATH_PLACEHOLDER` with the actual vault path from config.

Make it executable:
```bash
chmod +x ~/.obsidian-wiki/gstack-watch.sh
```

### Step 3: Write the launchd plist

Create `~/Library/LaunchAgents/com.obsidian-wiki.gstack-watch.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.obsidian-wiki.gstack-watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>WATCH_SCRIPT_PATH</string>
  </array>
  <key>StartInterval</key>
  <integer>INTERVAL_SECONDS</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>VAULT_PATH/.gstack-watch.log</string>
  <key>StandardErrorPath</key>
  <string>VAULT_PATH/.gstack-watch.log</string>
</dict>
</plist>
```

Replace:
- `WATCH_SCRIPT_PATH` → `~/.obsidian-wiki/gstack-watch.sh` (expanded absolute path)
- `INTERVAL_SECONDS` → user's chosen interval in seconds (e.g., 7200 for 2 hours)
- `VAULT_PATH` → actual vault path from config

### Step 4: Load the agent

```bash
launchctl load ~/Library/LaunchAgents/com.obsidian-wiki.gstack-watch.plist
```

Verify it's running:
```bash
launchctl list | grep gstack-watch
```

### Step 5: Confirm

Tell the user:
- Watch installed, runs every N hours
- Script at `~/.obsidian-wiki/gstack-watch.sh`
- Log at `$VAULT/.gstack-watch.log`
- When new learnings are detected, a `.gstack-sync-pending` marker appears in the vault — run `gstack-learnings-sync` to apply them. (`Check Status` below shows whether the marker is present.)

---

## Check Status

```bash
# Is the launchd agent loaded?
launchctl list | grep gstack-watch

# When did it last run?
cat ~/.obsidian-wiki/.watch-last-run 2>/dev/null || echo "Never run"

# Are there pending learnings?
cat "$VAULT/.gstack-sync-pending" 2>/dev/null || echo "No pending learnings"

# Recent log
tail -20 "$VAULT/.gstack-watch.log" 2>/dev/null || echo "No log yet"
```

Report the results in plain English.

---

## Update Interval

1. Unload the current agent: `launchctl unload ~/Library/LaunchAgents/com.obsidian-wiki.gstack-watch.plist`
2. Edit the plist: update `StartInterval` to the new value in seconds
3. Reload: `launchctl load ~/Library/LaunchAgents/com.obsidian-wiki.gstack-watch.plist`
4. Confirm the new schedule

---

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.obsidian-wiki.gstack-watch.plist
rm ~/Library/LaunchAgents/com.obsidian-wiki.gstack-watch.plist
rm -f ~/.obsidian-wiki/gstack-watch.sh
rm -f ~/.obsidian-wiki/.watch-last-run
```

Tell the user the watcher is removed. The `gstack-learnings-sync` skill still works on demand.

---

## Notes

- The watcher script only writes a marker file — it does NOT run Claude or modify the wiki directly. Actual wiki updates happen inside Claude Code via `gstack-learnings-sync`.
- On battery power, launchd may defer the run. This is expected — the watcher catches up on next trigger.
- If `python3` is not in PATH for the launchd environment, the script falls back to treating all entries as new (safe but slightly wasteful — it will always mark pending until the full sync runs).
