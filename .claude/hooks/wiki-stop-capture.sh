#!/usr/bin/env bash
# Fires on Claude Code Stop event.
# Reads the session transcript; if significant work happened (file edits or
# substantial shell activity), asks Claude to run /wiki-capture --quick so
# findings aren't silently lost at session end.
#
# Exit 0 → no-op (nothing worth capturing, or hook suppressed).
# Exit 2 → stderr content is fed back to Claude as a user message, triggering capture.
# Note: Claude Code Stop hooks deliver rewake content via stderr, not stdout.
#
# The stop_hook_active flag in the payload prevents re-entry (this hook won't
# fire again for the follow-up capture turn).

set -euo pipefail

INPUT=$(cat)

# Suppress if already in a stop-hook-triggered turn (prevents infinite loops)
IS_HOOK_TURN=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('1' if d.get('stop_hook_active') else '0')
" 2>/dev/null || echo "0")
[[ "$IS_HOOK_TURN" == "1" ]] && exit 0

TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('transcript_path', ''))
" 2>/dev/null || echo "")

[[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]] && exit 0

# Count meaningful tool uses: Write/Edit = file mutations, Bash = shell work
COUNTS=$(python3 - "$TRANSCRIPT_PATH" <<'PYEOF'
import json, sys

path = sys.argv[1]
write_edit = 0
bash_count = 0

with open(path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = entry.get("message") or {}
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            if name in ("Write", "Edit", "NotebookEdit"):
                write_edit += 1
            elif name == "Bash":
                bash_count += 1

print(write_edit, bash_count)
PYEOF
)

WRITE_EDIT=$(echo "$COUNTS" | awk '{print $1}')
BASH_COUNT=$(echo "$COUNTS" | awk '{print $2}')

# Trigger if any file was written/edited, or if there were ≥ 4 shell calls
# (suggesting investigation/debugging worth preserving).
if [[ "${WRITE_EDIT:-0}" -ge 1 ]] || [[ "${BASH_COUNT:-0}" -ge 4 ]]; then
  echo "Session ended with ${WRITE_EDIT} file edit(s) and ${BASH_COUNT} shell call(s). Please run /wiki-capture --quick now to preserve any reusable findings before this context closes." >&2
  exit 2
fi

exit 0
