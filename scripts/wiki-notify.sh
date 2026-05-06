#!/usr/bin/env bash
# Source this from your shell rc file to get wiki freshness reminders on terminal open.
#
# Setup (shell-specific):
#   zsh/bash:  source /path/to/obsidian-wiki/scripts/wiki-notify.sh
#   fish:      bass source /path/to/obsidian-wiki/scripts/wiki-notify.sh
#              (or copy _wiki_notify logic natively using fish syntax)
#
# State is vault-scoped under ~/.obsidian-wiki/state/<vault-id>/
# Multiple vaults are supported — all stale vaults are shown.

_wiki_notify() {
  local state_base="$HOME/.obsidian-wiki/state"
  [[ -d "$state_base" ]] || return

  local now age_s age_h stale last vault_path shown=0

  now=$(date +%s)

  # Iterate over all vault state dirs
  for state_dir in "$state_base"/*/; do
    [[ -f "$state_dir/.last_update" ]] || continue

    last=$(cat "$state_dir/.last_update" 2>/dev/null || echo 0)
    age_s=$(( now - last ))

    # Only show if >20 hours stale
    (( age_s > 72000 )) || continue

    age_h=$(( age_s / 3600 ))
    stale=$(cat "$state_dir/.pending_delta" 2>/dev/null || echo 0)
    vault_path=$(cat "$state_dir/.vault_path" 2>/dev/null || echo "unknown vault")

    echo "┌─ wiki: last synced ${age_h}h ago · ${vault_path##*/}$([ "$stale" -gt 0 ] && echo " · ${stale} source(s) have new content" || echo "")"
    echo "│  /wiki-history-ingest claude   sync Claude sessions"
    echo "│  /wiki-status                  see full delta"
    echo "└─ /memory-bridge diff           compare tool memories"
    shown=$(( shown + 1 ))
  done
}

_wiki_notify
