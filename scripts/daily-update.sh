#!/usr/bin/env bash
set -euo pipefail

# Daily wiki index update — called by launchd or directly.
# Checks if any history sources are stale and writes a status file
# that the shell prompt reads on terminal open.

CONFIG="$HOME/.obsidian-wiki/config"
STATE_DIR="$HOME/.obsidian-wiki"
STATE_FILE="$STATE_DIR/.last_update"
DELTA_FILE="$STATE_DIR/.pending_delta"

# Read vault path from config
if [[ -f "$CONFIG" ]]; then
  # shellcheck source=/dev/null
  source "$CONFIG"
fi

if [[ -z "${OBSIDIAN_VAULT_PATH:-}" ]]; then
  echo "[wiki-daily] OBSIDIAN_VAULT_PATH not set in $CONFIG — skipping" >&2
  exit 1
fi

MANIFEST="$OBSIDIAN_VAULT_PATH/.manifest.json"
mkdir -p "$STATE_DIR"

# Count sources modified after last ingest
stale_count=0
if [[ -f "$MANIFEST" ]]; then
  last_updated=$(python3 -c "
import json, sys
try:
  d = json.load(open('$MANIFEST'))
  print(d.get('last_updated',''))
except:
  print('')
" 2>/dev/null || echo "")

  if [[ -n "$last_updated" ]]; then
    # Check each known source path for modification time > last_updated
    stale_count=$(MANIFEST="$MANIFEST" python3 - <<'PYEOF'
import json, os, sys
from datetime import datetime, timezone

manifest_path = os.environ["MANIFEST"]
try:
    with open(manifest_path) as f:
        manifest = json.load(f)
except Exception:
    print(0)
    sys.exit()

last_updated_str = manifest.get("last_updated", "")
try:
    last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
except Exception:
    print(0)
    sys.exit()

stale = 0
for path, meta in manifest.get("sources", {}).items():
    expanded = os.path.expanduser(path)
    if os.path.exists(expanded):
        mtime = datetime.fromtimestamp(os.path.getmtime(expanded), tz=timezone.utc)
        if mtime > last_updated:
            stale += 1

print(stale)
PYEOF
    )
  fi
fi

# Write state
NOW=$(date +%s)
echo "$NOW" > "$STATE_FILE"
echo "$stale_count" > "$DELTA_FILE"

if [[ "$stale_count" -gt 0 ]]; then
  echo "[wiki-daily] $stale_count source(s) have new content since last ingest."
else
  echo "[wiki-daily] Wiki is up to date."
fi
