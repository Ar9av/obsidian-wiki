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
#
# Sessions with zero file edits whose shell commands are all read-only
# (grep/log/status style research) are exempt: nudging them only costs a full
# skill invocation that ends in SKIP. The classifier is conservative — any
# command it can't prove read-only counts as mutating, which preserves the
# pre-exemption behavior for that session.

set -euo pipefail

INPUT=$(cat)

# Suppress if already in a stop-hook-triggered turn (prevents infinite loops)
IS_HOOK_TURN=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('1' if d.get('stop_hook_active') else '0')
" 2>/dev/null || echo "0")
[[ "$IS_HOOK_TURN" == "1" ]] && exit 0

# Fire at most once per session — sentinel keyed to session_id prevents
# repeated nudges after the threshold is crossed on the first turn.
#
# The sentinel is a DIRECTORY, claimed with mkdir at the moment we decide to
# nudge (see below). mkdir is atomic on POSIX filesystems, so when several
# invocations run concurrently — which happens whenever the hook is registered
# in both project and user settings.json — exactly one wins and the rest exit
# silently. The check here is only a cheap short-circuit to skip transcript
# parsing; it is NOT the correctness guarantee, since concurrent invocations
# can all pass it before any of them claims.
SESSION_ID=$(printf '%s' "$INPUT" | python3 -c "
import json, sys; print(json.load(sys.stdin).get('session_id', ''))" 2>/dev/null || echo "")
SENTINEL=""
if [[ -n "$SESSION_ID" ]]; then
  SENTINEL="${TMPDIR:-/tmp}/wiki-stop-capture-${SESSION_ID}.done"
  [[ -e "$SENTINEL" ]] && exit 0
fi

TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('transcript_path', ''))
" 2>/dev/null || echo "")

[[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]] && exit 0

# Count meaningful tool uses: Write/Edit = file mutations, Bash = shell work.
# Bash commands are additionally classified read-only vs mutating so that
# edit-free research sessions can be exempted below.
COUNTS=$(python3 - "$TRANSCRIPT_PATH" <<'PYEOF'
import json, re, sys

path = sys.argv[1]
write_edit = 0
bash_count = 0
mutating_bash = 0

# Commands that never mutate state on their own (writes would need a shell
# redirect, which is detected separately). Anything absent from every list
# below counts as mutating — unknown means "assume it changed something".
READONLY_CMDS = {
    "cat", "ls", "head", "tail", "grep", "egrep", "fgrep", "rg", "find", "fd",
    "wc", "echo", "printf", "pwd", "which", "whereis", "type", "file", "stat",
    "du", "df", "ps", "env", "printenv", "id", "whoami", "uname", "date",
    "true", "false", "test", "[", "diff", "cmp", "tree", "basename", "dirname",
    "readlink", "realpath", "sort", "uniq", "cut", "tr", "column", "jq", "awk",
    "md5", "md5sum", "shasum", "sha256sum", "hexdump", "xxd", "strings",
    "less", "more", "nl", "od", "seq", "sleep", "uptime", "dig", "host",
    "nslookup", "sw_vers", "sysctl", "history",
}
GIT_READONLY = {
    "status", "log", "diff", "show", "rev-parse", "describe", "blame",
    "shortlog", "ls-files", "ls-tree", "ls-remote", "grep", "reflog",
    "cat-file", "count-objects",
}
GH_READONLY = {"view", "list", "status", "diff", "checks"}
# Wrappers whose real command is the next token.
WRAPPERS = {"sudo", "command", "nohup", "time", "xargs"}

# Harmless stderr/dev-null redirects, stripped before the generic ">" check.
HARMLESS_REDIRECTS = re.compile(r"\s*(2>&1|&?>{1,2}\s*/dev/null|2>{1,2}\s*/dev/null)")
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*\s+")


def split_segments(cmd):
    """Split on |, ||, &&, ;, newline — but never inside quotes.

    Returns (segment, unquoted_text) pairs; redirects are only meaningful in
    the unquoted portion, so ">" inside a quoted argument doesn't misclassify.
    """
    segs, buf, ubuf = [], [], []
    quote = None
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if quote:
            buf.append(c)
            if c == quote and cmd[i - 1] != "\\":
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            buf.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(cmd[i : i + 2])
            ubuf.append(cmd[i + 1])
            i += 2
            continue
        if cmd[i : i + 2] in ("||", "&&"):
            segs.append(("".join(buf), "".join(ubuf)))
            buf, ubuf = [], []
            i += 2
            continue
        if c in (";", "|", "\n"):
            segs.append(("".join(buf), "".join(ubuf)))
            buf, ubuf = [], []
            i += 1
            continue
        buf.append(c)
        ubuf.append(c)
        i += 1
    segs.append(("".join(buf), "".join(ubuf)))
    return segs


def segment_readonly(seg, unquoted):
    seg = seg.strip().lstrip("(!").strip()
    if not seg:
        return True
    if ">" in HARMLESS_REDIRECTS.sub(" ", unquoted):  # writes a file
        return False
    stripped = seg
    while True:
        replaced = ENV_ASSIGNMENT.sub("", stripped, count=1)
        if replaced == stripped:
            break
        stripped = replaced
    tokens = stripped.split()
    if not tokens:
        return True
    while tokens and tokens[0].rsplit("/", 1)[-1] in WRAPPERS:
        tokens = tokens[1:]
    if tokens and tokens[0].rsplit("/", 1)[-1] == "timeout":
        tokens = tokens[2:]
    if not tokens:
        return True
    cmd = tokens[0].rsplit("/", 1)[-1]
    if cmd in READONLY_CMDS:
        if cmd == "awk" and any(t == "-i" or t.startswith("inplace") for t in tokens[1:]):
            return False
        return True
    if cmd == "sed":
        return not any(t.startswith("-i") or t == "--in-place" for t in tokens[1:])
    if cmd == "git":
        sub = next((t for t in tokens[1:] if not t.startswith("-")), "")
        return sub in GIT_READONLY
    if cmd == "gh":
        rest = [t for t in tokens[1:] if not t.startswith("-")]
        return bool(rest) and (rest[0] in GH_READONLY or (len(rest) > 1 and rest[1] in GH_READONLY))
    if cmd in ("python", "python3"):
        return "-c" in tokens or "-V" in tokens or "--version" in tokens
    if cmd == "curl":
        writes = {"-o", "-O", "--output", "-T", "--upload-file", "-F", "--form"}
        if any(t in writes or t.startswith("-d") or t.startswith("--data") for t in tokens[1:]):
            return False
        if "-X" in tokens:
            method = tokens[tokens.index("-X") + 1] if tokens.index("-X") + 1 < len(tokens) else ""
            return method.upper() in ("GET", "HEAD")
        return True
    return False


def command_readonly(cmd):
    return all(segment_readonly(seg, unquoted) for seg, unquoted in split_segments(cmd))


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
                command = (block.get("input") or {}).get("command", "")
                if not command_readonly(command):
                    mutating_bash += 1

print(write_edit, bash_count, mutating_bash)
PYEOF
) || COUNTS="0 0 0"

WRITE_EDIT=$(echo "$COUNTS" | awk '{print $1}')
BASH_COUNT=$(echo "$COUNTS" | awk '{print $2}')
MUTATING_BASH=$(echo "$COUNTS" | awk '{print $3}')

# Trigger if any file was written/edited, or if there were ≥ 4 shell calls at
# least one of which mutated state (suggesting investigation/debugging worth
# preserving). Edit-free sessions whose shell activity is entirely read-only
# are exempt — see the header note.
if [[ "${WRITE_EDIT:-0}" -ge 1 ]] || { [[ "${BASH_COUNT:-0}" -ge 4 ]] && [[ "${MUTATING_BASH:-0}" -ge 1 ]]; }; then
  # Atomically claim the right to nudge. Losers of the race exit silently so a
  # duplicate registration produces one nudge, not two. Claimed here rather than
  # earlier so that a below-threshold turn doesn't burn the session's one nudge.
  if [[ -n "$SENTINEL" ]]; then
    mkdir "$SENTINEL" 2>/dev/null || exit 0
  fi
  echo "Session ended with ${WRITE_EDIT} file edit(s) and ${BASH_COUNT} shell call(s). Please run /wiki-capture --quick now to preserve any reusable findings before this context closes." >&2
  exit 2
fi

exit 0
