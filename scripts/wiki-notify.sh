#!/usr/bin/env bash
# Source this from ~/.zshrc — prints a wiki freshness reminder on terminal open.
# Add to ~/.zshrc:  source /path/to/obsidian-wiki/scripts/wiki-notify.sh

_WIKI_STATE_DIR="$HOME/.obsidian-wiki"
_WIKI_LAST_FILE="$_WIKI_STATE_DIR/.last_update"
_WIKI_DELTA_FILE="$_WIKI_STATE_DIR/.pending_delta"

_wiki_notify() {
  local now last age_s age_h stale

  # Skip if state files don't exist yet (wiki not set up)
  [[ -f "$_WIKI_LAST_FILE" ]] || return

  now=$(date +%s)
  last=$(cat "$_WIKI_LAST_FILE" 2>/dev/null || echo 0)
  age_s=$(( now - last ))
  age_h=$(( age_s / 3600 ))
  stale=$(cat "$_WIKI_DELTA_FILE" 2>/dev/null || echo 0)

  # Only show if last update was >20 hours ago
  if (( age_s > 72000 )); then
    echo "┌─ wiki: last synced ${age_h}h ago$([ "$stale" -gt 0 ] && echo " · ${stale} source(s) have new content" || echo " · no new sources detected")"
    echo "│  /wiki-history-ingest claude   sync Claude sessions"
    echo "│  /wiki-status                  see full delta"
    echo "└─ /memory-bridge diff           compare tool memories"
  fi
}

_wiki_notify
