---
name: session-search
description: >
  Find a past agent session by topic and load its context into the current conversation. Searches
  the session-brain topic graph, ranking by relevance, topic membership, and time decay, then
  loads the winning transcript. Use when the user says "/wiki-sessions <topic>", "which session
  did I do X in", "find the session where I fixed X", "when did I last work on Y", "what was that
  session about Z", "load the session where I set up X", "have I done this before". Read-only —
  never writes to the vault. Requires a graph built by the session-brain skill.
---

# Session Search

Answers "which of my past sessions was about X" and then pulls that session's context in.

## Step 1: Check the graph exists and is fresh

```bash
obsidian-wiki sessions-query "<topic>" --json
```

If this exits 1 with "run sessions-build first", tell the user and offer `/session-brain`. If
`graph.json` is more than ~7 days old, mention it and offer a rebuild — but **do not silently
rebuild**, since that is a multi-second operation the user did not ask for.

## Step 2: Rank

The scoring already combines four signals, so take the ordering as given rather than re-ranking:

- **similarity** — TF-IDF cosine against the session's text
- **cluster lift** — a session inside the best-matching topic scores higher even if its own words
  never matched. This is why a session that never said "telemetry" can still surface for it.
- **bookmark boost** — a human already flagged this session as worth keeping
- **time decay** — 90-day half-life, applied with a floor so an old exact match still outranks a
  fresh weak one

Useful filters: `--project NAME`, `--cluster N`, `--since DATE`, `--top N`.

## Step 3: Present

Show the top ~5 as a compact table — title, project, date, topic, and the `why` string, which
already explains the match. Do not dump the raw JSON at the user.

Two things must be stated honestly rather than glossed over:

- Entries with `loadable: false` are **history-only**: the transcript has been pruned from disk
  and only the prompts survive. They are listed in `unloadable` with a reason. Say the transcript
  is gone; do not imply it can be retrieved.
- If everything relevant is unloadable, answer from the prompt text that *is* there and say that
  is all that remains.

## Step 4: Load — hand off, do not reimplement

`should_load` holds at most 3 session ids worth opening, already filtered to ones with
transcripts.

**Prefer an existing loader skill if the user has one installed:**

- `claude-session-load` — loads a Claude session by id
- `bookmark-load` — use when the hit is bookmarked

⚠️ Those skills live in the user's personal skills directory (`~/.claude/skills/`), **not in this
repo**. They may not exist. Do not assume them and do not error if they are absent — fall back to
reading the transcript directly:

```bash
# the path is in the query result as `transcript`
obsidian-wiki sessions-show <session-id> --pretty
```

The transcript is JSONL and can be tens of MB. **Never read one whole.** Filter to the human turns
first:

```bash
grep -c '' <transcript>   # size check before anything else
python3 -c "
import json,sys
for line in open(sys.argv[1], errors='replace'):
    try: r = json.loads(line)
    except ValueError: continue
    if r.get('type')=='user' and not r.get('isSidechain') and not r.get('isMeta'):
        c = (r.get('message') or {}).get('content')
        if isinstance(c,str) and not c.lstrip().startswith('<'): print('>', c[:400])
" <transcript>
```

## Step 5: Answer

Synthesise from what you loaded and cite the session ids you used. If the answer came from a
history-only session's prompts rather than a real transcript, say so — the user needs to know how
much of the context you actually have.

## Related

- `/session-brain` — build or refresh the graph, survey and name topics
- `wiki-query` — search compiled vault knowledge; this skill searches raw session history instead
- `wiki-agent` — pull a topic out of *another* agent's history and distil it into the vault
