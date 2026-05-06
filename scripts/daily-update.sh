#!/usr/bin/env bash
set -euo pipefail

# Daily wiki index update — called by launchd or directly.
# Checks if any history sources are stale and writes vault-scoped state files
# that the shell prompt reads on terminal open.
#
# Config resolution order (mirrors llm-wiki/SKILL.md protocol):
#   1. Walk up from CWD looking for .env with OBSIDIAN_VAULT_PATH
#   2. Fall back to ~/.obsidian-wiki/config
#   3. Exit with error if neither found

_find_config() {
  local dir="$PWD"
  while [[ "$dir" != "$HOME" && "$dir" != "/" ]]; do
    if [[ -f "$dir/.env" ]] && grep -q "OBSIDIAN_VAULT_PATH" "$dir/.env" 2>/dev/null; then
      echo "$dir/.env"
      return
    fi
    dir="$(dirname "$dir")"
  done
  if [[ -f "$HOME/.obsidian-wiki/config" ]]; then
    echo "$HOME/.obsidian-wiki/config"
    return
  fi
  echo ""
}

CONFIG_FILE="$(_find_config)"

if [[ -z "$CONFIG_FILE" ]]; then
  echo "[wiki-daily] No config found. Run wiki-setup to initialize your wiki." >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG_FILE"

if [[ -z "${OBSIDIAN_VAULT_PATH:-}" ]]; then
  echo "[wiki-daily] OBSIDIAN_VAULT_PATH not set in $CONFIG_FILE — skipping" >&2
  exit 1
fi

# Vault-scoped state dir (supports multiple vaults independently)
VAULT_ID=$(echo "$OBSIDIAN_VAULT_PATH" | md5sum 2>/dev/null | cut -c1-8 || \
           md5 -q - <<< "$OBSIDIAN_VAULT_PATH" 2>/dev/null | cut -c1-8 || \
           echo "default")
STATE_DIR="$HOME/.obsidian-wiki/state/$VAULT_ID"
mkdir -p "$STATE_DIR"

# Write vault path so wiki-notify.sh can find this state dir
echo "$OBSIDIAN_VAULT_PATH" > "$STATE_DIR/.vault_path"

MANIFEST="$OBSIDIAN_VAULT_PATH/.manifest.json"

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

# Write vault-scoped state
NOW=$(date +%s)
echo "$NOW" > "$STATE_DIR/.last_update"
echo "$stale_count" > "$STATE_DIR/.pending_delta"

if [[ "$stale_count" -gt 0 ]]; then
  echo "[wiki-daily] $stale_count source(s) have new content since last ingest. State: $STATE_DIR"
else
  echo "[wiki-daily] Wiki is up to date. State: $STATE_DIR"
fi
