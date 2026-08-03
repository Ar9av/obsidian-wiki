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
# (grep/log/status style research) — and whose other tool calls are provably
# read-only too — are exempt: nudging them only costs a full skill invocation
# that ends in SKIP. The classifier is conservative — any
# command it can't prove read-only counts as mutating, which preserves the
# pre-exemption behavior for that session. In particular, command/process
# substitution ($(…), `…`, <(…)) is treated as mutating without inspecting
# the inner command.

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
#
# The classifier is written to a temp file rather than fed inline through
# $(python3 <<heredoc): bash 3.2 (macOS /bin/bash) scans a $() body naively
# and chokes on backticks or unbalanced quotes inside the heredoc text.
CLASSIFIER="${TMPDIR:-/tmp}/wiki-stop-capture-classify-$$.py"
cat > "$CLASSIFIER" <<'PYEOF'
import json, re, shlex, sys

path = sys.argv[1]
write_edit = 0
bash_count = 0
mutating_bash = 0
suspicious_tools = 0

# Commands that never mutate state on their own (writes would need a shell
# redirect or substitution, both detected separately). Anything absent from
# every list below counts as mutating — unknown means "assume it changed
# something". Commands with a mutating flag form (find -delete, sort -o,
# date -s, …) get an explicit flag check instead of a blanket entry.
READONLY_CMDS = {
    "cat", "ls", "head", "tail", "grep", "egrep", "fgrep", "rg", "fd",
    "wc", "echo", "printf", "pwd", "which", "whereis", "type", "file", "stat",
    "du", "df", "ps", "printenv", "id", "whoami", "uname",
    "true", "false", "test", "[", "diff", "cmp", "tree", "basename", "dirname",
    "readlink", "realpath", "cut", "tr", "column", "jq",
    "md5", "md5sum", "shasum", "sha256sum", "hexdump", "xxd", "strings",
    "less", "more", "nl", "od", "seq", "sleep", "uptime", "dig", "host",
    "nslookup", "sw_vers",
    # Shell-session state only — nothing durable outside the (already
    # finished) shell process, so treating these as read-only keeps common
    # research chains like `cd repo && git log` in the exemption.
    "cd", "pushd", "popd", "export", "unset", "umask", "ulimit", "shopt",
    "set", "local", "declare", "typeset", "read", "wait", ":",
    "man", "whatis", "apropos", "hostname", "arch", "nproc", "getconf",
    "locale", "groups", "tty", "clear",
}
GIT_READONLY = {
    "status", "log", "diff", "show", "rev-parse", "describe", "blame",
    "shortlog", "ls-files", "ls-tree", "ls-remote", "grep", "reflog",
    "cat-file", "count-objects",
}
GH_READONLY = {"view", "list", "status", "diff", "checks"}
# Harness tools that never mutate anything outside the session: file/web
# reading, planning, task bookkeeping. Any other non-Bash tool call —
# notably MCP tools without a clear read verb — makes the session
# ineligible for the read-only exemption, because a real system mutation
# (a CRM update, an SQL INSERT) may hide behind it.
CORE_READONLY_TOOLS = {
    "Read", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "TodoWrite",
    "TodoRead", "NotebookRead", "Task", "Agent", "AskUserQuestion",
    "ToolSearch", "Skill", "SkillSearch", "SlashCommand", "EnterPlanMode",
    "ExitPlanMode", "EnterWorktree", "ExitWorktree", "Explore", "Plan",
    "TaskCreate", "TaskUpdate", "TaskGet", "TaskList", "TaskOutput",
    "TaskStop", "BashOutput", "KillShell", "SendUserFile", "Monitor",
    "ScheduleWakeup", "ListMcpResourcesTool", "ReadMcpResourceTool",
    "ReadMcpResourceDirTool",
}
MCP_READ_VERBS = {
    "get", "list", "search", "read", "query", "fetch", "find", "describe",
    "inspect", "explain", "compare", "view", "check", "status", "whoami",
    "resolve", "analyze", "show", "health", "info", "download", "lookup",
    "browse", "watch", "screenshot",
}
# Write verbs take priority over read verbs for names carrying both
# ("get-or-create-session" creates).
MCP_WRITE_VERBS = {
    "create", "update", "delete", "remove", "write", "insert", "upsert",
    "execute", "run", "send", "post", "put", "patch", "move", "add", "set",
    "complete", "archive", "clone", "push", "upload", "provision", "reset",
    "apply", "schedule", "cancel", "start", "stop", "restart", "deploy",
    "publish", "merge", "commit", "approve", "assign", "register", "enable",
    "disable", "duplicate",
}
# Wrappers whose real command comes later in the token list. env belongs here,
# not in READONLY_CMDS: `env FOO=1 cmd` runs cmd, so it must be unwrapped
# (a bare `env` unwraps to nothing and stays read-only).
WRAPPERS = {"sudo", "command", "nohup", "time", "xargs", "env", "nice", "stdbuf"}
FIND_MUTATING_FLAGS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls"}

# Harmless stderr/dev-null redirects, stripped before the generic ">" check.
HARMLESS_REDIRECTS = re.compile(r"\s*(2>&1|&?>{1,2}\s*/dev/null|2>{1,2}\s*/dev/null)")
ENV_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Write/exec patterns inside an inline python -c payload. Heuristic: parsing
# and printing stay read-only; anything that touches the filesystem, spawns
# processes, or issues writing HTTP verbs counts as mutating.
PY_RISKY = re.compile(
    r"subprocess|shutil\.|socket|http\.client|HTTPConnection"
    r"|\bexec\s*\(|\beval\s*\(|__import__"
    r"|os\.(system|popen|remove|unlink|rename|replace|rmdir|mkdir|makedirs"
    r"|chmod|chown|symlink|link|truncate|environ\[)"
    r"|\.write\w*\(|\.unlink\(|\.touch\(|\.mkdir\(|\.rename\(|\.rmdir\("
    r"|\.save\(|\.to_csv\(|\.to_excel\(|\.commit\("
    r"|open\([^()]*,\s*[\"']?[wax]|open\([^()]*mode\s*=\s*[\"'][wax]"
    r"|urlopen\([^()]*data|Request\([^()]*data|requests\.(post|put|patch|delete)"
    r"|INSERT INTO|DELETE FROM|DROP TABLE|CREATE TABLE|ALTER TABLE"
    r"|smtplib|ftplib|paramiko|os\.kill"
)
# awk writing through its own redirection or shelling out: `print > "file"`,
# `system("…")`, `print | "cmd"`, `"cmd" | getline`. Checked on the raw
# segment because the awk program is quoted.
AWK_RISKY = re.compile(r">>?\s*[\"']|system\s*\(|\|\s*[\"']|[\"']\s*\|")


def split_segments(cmd):
    """Split on |, ||, &&, ;, newline — but never inside quotes.

    Returns (segment, unquoted, expandable) triples. Redirects only count in
    the unquoted portion (">" inside a quoted argument is literal), while
    substitution markers count anywhere the shell expands them — outside
    quotes and inside double quotes, but not inside single quotes.
    """
    segs, buf, ubuf, ebuf = [], [], [], []
    quote = None
    i, n = 0, len(cmd)

    def close():
        segs.append(("".join(buf), "".join(ubuf), "".join(ebuf)))
        buf.clear()
        ubuf.clear()
        ebuf.clear()

    while i < n:
        c = cmd[i]
        if quote:
            buf.append(c)
            if quote == '"':
                ebuf.append(c)
            # A single quote always closes — the shell does not allow
            # escaping inside '…'; only double quotes honor a backslash.
            if c == quote and (quote == "'" or cmd[i - 1] != "\\"):
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
            close()
            i += 2
            continue
        if c in (";", "|", "\n"):
            close()
            i += 1
            continue
        buf.append(c)
        ubuf.append(c)
        ebuf.append(c)
        i += 1
    close()
    return segs


def tokenize(text):
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def segment_readonly(seg, unquoted, expandable):
    seg = seg.strip().lstrip("(!").strip()
    if not seg:
        return True
    if ">" in HARMLESS_REDIRECTS.sub(" ", unquoted):  # writes a file
        return False
    # Command/process substitution runs an arbitrary inner command — treat as
    # mutating rather than trying to classify the payload.
    if "$(" in expandable or "`" in expandable or "<(" in expandable or ">(" in expandable:
        return False
    tokens = tokenize(seg)
    while tokens:
        head = tokens[0].rsplit("/", 1)[-1]
        if head in WRAPPERS or ENV_TOKEN.match(tokens[0]):
            tokens = tokens[1:]
            continue
        if head == "timeout":
            tokens = tokens[2:]
            continue
        break
    if not tokens:
        return True
    cmd = tokens[0].rsplit("/", 1)[-1]
    args = tokens[1:]
    if cmd == "find":
        return not any(t in FIND_MUTATING_FLAGS or t.startswith("-fprint") for t in args)
    if cmd == "fd":
        return not any(t in ("-x", "--exec", "-X", "--exec-batch") for t in args)
    if cmd == "rg":
        return not any(t == "--pre" or t.startswith("--pre=") for t in args)
    if cmd == "tree":
        return not any(t == "-o" for t in args)
    if cmd == "hostname":
        # Bare hostname prints; with a non-flag argument it SETS the hostname.
        return not [t for t in args if not t.startswith("-")]
    if cmd == "xxd":
        # A second positional argument is an output file (xxd -r patch.hex bin).
        return len([t for t in args if not t.startswith("-")]) < 2
    if cmd == "sort":
        return not any(t == "-o" or t.startswith("--output") or (t.startswith("-o") and len(t) > 2) for t in args)
    if cmd == "uniq":
        return len([t for t in args if not t.startswith("-")]) < 2
    if cmd == "date":
        return not any(t == "-s" or t.startswith("--set") for t in args)
    if cmd == "sysctl":
        return not any(t == "-w" or "=" in t for t in args)
    if cmd == "awk":
        if any(t == "-i" or t.startswith("inplace") for t in args):
            return False
        return not AWK_RISKY.search(seg)
    if cmd in READONLY_CMDS:
        return True
    if cmd == "sed":
        if any(t.startswith("-i") or t == "--in-place" for t in args):
            return False
        # The sed `w` script command writes a file without any -i flag:
        # `sed -n 'w out.txt'`, `s/a/b/w out.txt` — scanned on every token
        # so a glued `-e's/a/b/w out'` script is caught too.
        return not any(re.search(r"(^|;)\s*w\s|/w\b", t) for t in args)
    if cmd == "history":
        # history -c/-d clear entries, -w/-a/-r touch the history file.
        return not any(t.startswith("-") and t != "--" for t in args)
    if cmd == "git":
        # `git diff/log --output=file` writes without a shell redirect.
        if any(t.startswith("--output") for t in args):
            return False
        positional = [t for t in args if not t.startswith("-")]
        sub = positional[0] if positional else ""
        if sub == "reflog":
            # `git reflog expire/delete` mutates; bare reflog / reflog show reads.
            return len(positional) < 2 or positional[1] == "show"
        return sub in GIT_READONLY
    if cmd == "gh":
        rest = [t for t in args if not t.startswith("-")]
        return bool(rest) and (rest[0] in GH_READONLY or (len(rest) > 1 and rest[1] in GH_READONLY))
    if cmd in ("python", "python3"):
        if "-V" in args or "--version" in args:
            return True
        return "-c" in args and not PY_RISKY.search(seg)
    if cmd == "curl":
        long_writes = {
            "--output", "--output-dir", "--remote-name", "--upload-file",
            "--form", "--form-string", "--json", "--cookie-jar",
            "--dump-header", "--etag-save",
        }
        for idx, t in enumerate(args):
            if t in long_writes or t.startswith("--data") or t.startswith("--trace"):
                return False
            if t == "--request":
                method = args[idx + 1] if idx + 1 < len(args) else ""
                if method.upper() not in ("GET", "HEAD"):
                    return False
            elif t.startswith("--"):
                continue
            elif t.startswith("-X"):
                method = t[2:] or (args[idx + 1] if idx + 1 < len(args) else "")
                if method.upper() not in ("GET", "HEAD"):
                    return False
            elif re.match(r"^-[A-Za-z]*[dDoOTFXc]", t):
                # Short flags cluster (-sd, -sLo, -sT, -sc): d/D/o/O/T/F/X/c
                # all send data or write files (c = cookie jar), wherever
                # they sit in the cluster.
                return False
        return True
    return False


def command_readonly(cmd):
    return all(segment_readonly(*parts) for parts in split_segments(cmd))


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
            elif name in CORE_READONLY_TOOLS:
                continue
            elif name.startswith("mcp__"):
                words = re.split(r"[-_]", name.rsplit("__", 1)[-1].lower())
                if any(w in MCP_WRITE_VERBS for w in words) or not any(
                    w in MCP_READ_VERBS for w in words
                ):
                    suspicious_tools += 1
            else:
                # Unknown harness tool — assume it mutated something.
                suspicious_tools += 1

print(write_edit, bash_count, mutating_bash, suspicious_tools)
PYEOF

COUNTS=$(python3 "$CLASSIFIER" "$TRANSCRIPT_PATH" 2>/dev/null) || COUNTS="0 0 0"
rm -f "$CLASSIFIER"

WRITE_EDIT=$(echo "$COUNTS" | awk '{print $1}')
BASH_COUNT=$(echo "$COUNTS" | awk '{print $2}')
MUTATING_BASH=$(echo "$COUNTS" | awk '{print $3}')
SUSPICIOUS_TOOLS=$(echo "$COUNTS" | awk '{print $4}')

# Trigger if any file was written/edited, or if there were ≥ 4 shell calls at
# least one of which mutated state (suggesting investigation/debugging worth
# preserving). Edit-free sessions whose shell activity is entirely read-only
# are exempt — but only when no other tool call could have mutated a real
# system (MCP writes, unknown harness tools). Suspicious tool calls never
# trigger on their own — they only disable the exemption, so this hook never
# nudges where the pre-exemption threshold (edits >= 1 or bash >= 4) wouldn't.
if [[ "${WRITE_EDIT:-0}" -ge 1 ]] || { [[ "${BASH_COUNT:-0}" -ge 4 ]] && { [[ "${MUTATING_BASH:-0}" -ge 1 ]] || [[ "${SUSPICIOUS_TOOLS:-0}" -ge 1 ]]; }; }; then
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
