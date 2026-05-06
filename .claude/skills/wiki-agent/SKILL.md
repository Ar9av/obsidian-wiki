---
name: wiki-agent
description: >
  Query-driven targeted ingest from a specific AI agent's raw history. Use this skill when the user
  invokes /wiki-claude, /wiki-codex, /wiki-hermes, /wiki-openclaw, /wiki-copilot — with or without a
  search topic. Different from wiki-history-ingest (which bulk-ingests everything new): this skill finds
  sessions about a SPECIFIC TOPIC in a specific agent's history and ingests just those, then returns a
  synthesized answer immediately usable in the current session. Primary use case: you're working in
  agent A and want to pull in how you solved X in agent B's history. Cross-referencing, not archiving.
  Also trigger on: "what did I work on in codex about X", "search my claude sessions for Y",
  "pull in hermes knowledge about Z", "find that conversation where I did X in codex".
---

# Wiki Agent — Targeted Cross-Agent History Search + Ingest

You are doing a **query-driven targeted ingest** from one specific AI agent's raw conversation history. The user is typically working in a *different* agent right now and wants to pull in context from another agent's past sessions.

This is not bulk ingest. You find sessions about a specific topic, extract the relevant blobs, distill them into the wiki, and return a synthesized answer the user can act on immediately.

## Command Routing

Parse the invocation to determine the target agent and optional query:

| Command | Target | Example |
|---|---|---|
| `/wiki-claude [query]` | Claude Code history | `/wiki-claude "how did I set up auth middleware"` |
| `/wiki-codex [query]` | Codex CLI history | `/wiki-codex "rust ownership patterns"` |
| `/wiki-hermes [query]` | Hermes agent history | `/wiki-hermes "memory architecture"` |
| `/wiki-openclaw [query]` | OpenClaw history | `/wiki-openclaw "project planning approach"` |
| `/wiki-copilot [query]` | Copilot chat history | `/wiki-copilot "test strategy for API routes"` |

If no query is given, default to **recent sessions mode**: ingest the last 5 unprocessed sessions from that agent and return a summary of what was found. This is equivalent to a focused `wiki-history-ingest` for that agent only.

## Before You Start

1. Read `~/.obsidian-wiki/config` → get `OBSIDIAN_VAULT_PATH`.
2. Read `$OBSIDIAN_VAULT_PATH/.manifest.json` → know what's already ingested.
3. Read `$OBSIDIAN_VAULT_PATH/hot.md` if it exists → warm context on recent wiki activity.

---

## Step 1: Locate the Agent's History Root

| Agent | Default path | Config override |
|---|---|---|
| `claude` | `~/.claude` + `~/Library/Application Support/Claude/local-agent-mode-sessions/` | `CLAUDE_HISTORY_PATH` in `.env` |
| `codex` | `~/.codex` | `CODEX_HISTORY_PATH` in `.env` |
| `hermes` | `~/.hermes` | `HERMES_HOME` in env or `.env` |
| `openclaw` | `~/.openclaw` | `OPENCLAW_HOME` in `.env` |
| `copilot` | `~/.copilot` | `COPILOT_HISTORY_PATH` in `.env` |

If the history root doesn't exist, stop and tell the user: "No `<agent>` history found at `<path>`. Have you run `<agent>` on this machine? You can set a custom path with `<CONFIG_VAR>` in `.env`."

---

## Step 2: Build Session Inventory

Use the **cheapest index source** for each agent — don't open session files until you know which ones are relevant.

### Claude
```
Primary index:   ~/.claude/projects/  (directories = projects, files = sessions)
Session files:   ~/.claude/projects/*/*.jsonl
Desktop index:   find ~/Library/Application Support/Claude/local-agent-mode-sessions -name "local_*.json"
Signal fields:   sessionId, cwd, startedAt, title (in local_*.json)
```
Build a list of sessions: `{path, project_dir, modified_at, already_ingested}`.

### Codex
```
Primary index:   ~/.codex/session_index.jsonl
Session files:   ~/.codex/sessions/**/rollout-*.jsonl
Signal fields:   thread_id, name/title, updated_at (in session_index.jsonl)
```
Read `session_index.jsonl` as the inventory. Each line: `{thread_id, name, updated_at}`. Map thread IDs to rollout files by matching directory names.

### Hermes
```
Primary index:   ~/.hermes/memories/*.md  (fast to scan)
Session files:   ~/.hermes/sessions/**/*.jsonl
Signal fields:   file names, memory titles, first 3 lines of each memory
```
Scan memory filenames first (they're often titled by topic). Fall back to session listing.

### OpenClaw
```
Primary index:   ~/.openclaw/workspace/memory/MEMORY.md  (structured long-term memory)
Daily notes:     ~/.openclaw/workspace/memory/YYYY-MM-DD.md
Session index:   ~/.openclaw/agents/*/sessions/sessions.json
Session files:   ~/.openclaw/agents/*/sessions/*.jsonl
```
Read `MEMORY.md` sections first — it's the pre-compiled summary of everything. Daily notes give recency signal.

### Copilot
```
Primary index:   session filenames / directory listing
Session files:   varies by client (VS Code: ~/.copilot/sessions/*.jsonl or similar)
Signal fields:   session timestamps, file names
```

---

## Step 3: Score Sessions Against the Query

If a query was given, score each session in the inventory without opening full session files:

1. **Name/title match** — does the session name or thread title contain the query terms? Score: +3
2. **CWD/project match** — does the working directory suggest the right project? Score: +2
3. **Recency** — sessions from the last 90 days score higher than older ones. Score: +1 per 30-day recency bracket (max +3)
4. **Already ingested** — if this session was previously ingested and the wiki page already covers the query (check `hot.md` + `index.md`), flag as "covered" but still show in results

Select the **top 3–5 sessions** by score. If no query was given, select the 5 most recent unprocessed sessions.

---

## Step 4: Extract the Relevant Blob

Open each selected session file and extract only the content relevant to the query. **Do not read the full session if it's large — use targeted extraction.**

### Per-Agent Extraction Strategy

**Claude** (JSONL conversation):
- Each line: `{role, content, timestamp, ...}`
- Search with: `grep -i "<query terms>" <session.jsonl>` to find the relevant lines
- Extract: the surrounding conversation window (10 lines before + 20 lines after each hit)
- Special signal: tool calls (Read/Write/Bash/Edit) reveal what was actually done — extract these even without keyword matches if they're in the relevant window

**Codex** (rollout JSONL):
- Each line: `{type: "session_meta|turn_context|event_msg|response_item", ...}`
- Filter to `type: "event_msg"` (user turns) and `type: "response_item"` (model output)
- Search with: `grep -i "<query terms>" <rollout.jsonl>`
- Extract: matching turns + their parent context (the `turn_context` preceding the match)
- Skip: `session_meta` events (operational metadata, not knowledge)

**Hermes** (memory files + session JSONL):
- For memory files: read the full file (they're short — typically <500 words each)
- For session JSONL: `grep -i "<query terms>"` + surrounding window
- Memory files with title matches → read fully; others → grep only

**OpenClaw** (MEMORY.md + daily notes + session JSONL):
- `MEMORY.md`: grep for section headers containing query terms → extract that section
- Daily notes: grep most recent 30 days for query terms → extract matching paragraphs
- Session JSONL: same grep-window approach as Claude
- Prefer MEMORY.md/daily notes over session JSONL (they're pre-synthesized)

**Copilot** (session JSONL):
- Same grep-window approach as Claude
- Look for checkpoint files if available (pre-summarized)

---

## Step 5: Distill Blobs into Wiki Pages

For each extracted blob, determine where it belongs in the wiki:

1. **Check if a wiki page already covers this** — grep `index.md` and page frontmatter for the topic. If yes, update the existing page rather than creating a new one.
2. **Determine category** using standard rules (from `llm-wiki/SKILL.md`):
   - Technique / how-to → `skills/`
   - Abstract concept / pattern → `concepts/`
   - Tool / library / person → `entities/`
   - Cross-cutting insight → `synthesis/`
3. **Write or update the page** with required frontmatter:
   ```yaml
   ---
   title: <topic>
   category: skill|concept|entity|synthesis
   tags: [tag1, tag2]
   sources: [<agent>://<path/to/session>]
   created: <date>
   updated: <date>
   confidence: high|medium|low
   lifecycle: stable|draft
   ---
   ```
   Set `sources` with the agent prefix so `memory-bridge` can find it later.
4. **Add cross-links** to related wiki pages found in `index.md`.

Distillation rules (same as all ingest skills):
- Extract durable knowledge, not operational telemetry
- One wiki page per concept, not one per session
- Merge into existing pages rather than duplicating
- Keep the signal: decisions made, patterns discovered, techniques that worked, bugs explained

---

## Step 6: Return Synthesized Answer

After ingesting, immediately synthesize and return an answer from the newly ingested + existing wiki content:

```
## From <agent> history: "<query>"

**Found in:** <N> sessions (<session names/titles>)

**Key insights:**
<Synthesized answer — 3–5 bullet points of the most useful knowledge>

**Wiki pages updated/created:**
- [[page-name]] — <what was added>
- [[page-name]] — <what was added>

**Sessions ingested:**
| Session | Date | Relevance |
|---------|------|-----------|
| <name>  | <date> | <one-line why it was selected> |

**Gaps:** <What the sessions didn't cover that might be relevant>
```

If a query was given but no relevant sessions were found, say so explicitly: "No sessions about '<query>' found in `<agent>` history. The most recent sessions covered: <list topics from last 3 sessions>."

---

## Step 7: Update Tracking Files

Update `.manifest.json` for each session file processed:
```json
{
  "<path>": {
    "ingested_at": "<now>",
    "source_type": "<agent>_conversation",
    "modified_at": "<file mtime>",
    "pages_created": [...],
    "pages_updated": [...]
  }
}
```

Append to `log.md`:
```
- [TIMESTAMP] WIKI-AGENT agent=<agent> query="<query>" sessions_searched=N sessions_ingested=M pages_created=X pages_updated=Y
```

Update `hot.md` with a one-line summary of what was ingested.

---

## Cross-Agent Use Patterns

These are the primary use cases this skill is designed for:

**"I'm on Codex. What did I figure out about X in Claude?"**
→ `/wiki-claude "X"` — finds Claude sessions about X, ingests them, returns the answer

**"I solved a bug in Hermes last week. I need that context now in Claude Code."**
→ `/wiki-hermes "bug description"` — surfaces and ingests the Hermes session

**"What are all the approaches I've tried for X across all my tools?"**
→ Run `/wiki-claude "X"`, `/wiki-codex "X"`, `/wiki-hermes "X"` in sequence — each ingests its slice, the wiki accumulates the cross-agent picture, then `/memory-bridge diff` shows what each tool uniquely contributed

**No query — just "catch me up on recent Codex work"**
→ `/wiki-codex` — ingests last 5 Codex sessions and returns a summary
