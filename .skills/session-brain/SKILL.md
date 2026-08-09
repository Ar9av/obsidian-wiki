---
name: session-brain
description: >
  Build and maintain a topic graph over your agent session history. Reads every Claude session
  transcript plus the pruned sessions that survive only in history.jsonl, clusters them by topic
  using local TF-IDF (no API calls, no embeddings), and writes an interactive graph you can open
  in a browser. Use when the user says "/session-brain", "build my session map", "cluster my
  claude sessions", "map my session history", "rebuild the session graph", "show me my session
  graph", "what have I been working on lately", "what topics have gone stale". Different from
  wiki-history-ingest, which distils sessions into vault pages: this builds a retrieval index
  over the raw sessions and never writes to the vault.
---

# Session Brain

Builds a searchable topic graph over your agent session history. The output is a **sidecar**
at `~/.claude/session-brain/` — the vault is never touched.

All the heavy lifting is deterministic Python in the `obsidian-wiki` CLI. Your only job is to
name the clusters, which takes exactly one turn and requires reading no transcripts.

## When to use which skill

| Goal | Skill |
|---|---|
| Build or refresh the graph; survey topics | `session-brain` (this one) |
| Find and load a specific past session | `session-search` |
| Distil sessions into permanent vault pages | `wiki-history-ingest` / `claude-history-ingest` |

## Step 1: Build

```bash
obsidian-wiki sessions-build --json
```

Roughly 3 seconds cold on ~1000 sessions, well under a second incrementally — it re-reads only
transcripts whose size or mtime changed. Useful flags:

| Flag | When |
|---|---|
| `--full` | Ignore all caches and re-read everything |
| `--mutual` | Tighter, smaller clusters (mutual-kNN edges only) |
| `--half-life N` | Change the recency half-life (default 90 days) |
| `--min-sim 0.15` | Fewer, stronger edges — use if the graph is too dense to read |
| `--skip name` | Exclude a project. Match is substring-based; pass the bare name, because cache dirs start with `-` and argparse reads that as a flag |

Report the headline numbers: total sessions, how many have transcripts vs. are history-only,
edges, and cluster count.

## Step 2: Name the unnamed clusters

```bash
obsidian-wiki sessions-clusters --unnamed --json
```

Each cluster comes with `top_terms` and `exemplars` (its three highest-degree sessions, whose
titles are already in `graph.json`). **That is all you need.** Do not open transcripts to name a
cluster — the whole design goal is that naming costs one turn regardless of corpus size.

Write a 3–5 word `name` and a one-sentence `summary` per cluster, then:

```bash
obsidian-wiki sessions-name --from - <<'EOF'
[{"id": 3, "name": "warden telemetry pipeline", "summary": "Building and debugging the redacted telemetry chain."}]
EOF
```

Names are stored in `names.json` keyed by the cluster's dominant vocabulary, not its id — so they
survive rebuilds even though cluster ids are positional and shift as the corpus grows. On repeat
runs `--unnamed` is usually empty and this step is free.

If a cluster's terms are genuinely incoherent, name it honestly (`"mixed — short sessions"`)
rather than inventing a theme.

## Step 3: Report the map

Read `clusters.json` and tell the user:

- **Biggest topics** — by `size`
- **What's hot** — highest `momentum` (activity in the last 30 days vs. the 60 before it)
- **What's gone quiet** — `dormant: true` (low recency *and* nothing in 60 days)
- **Where topics meet** — `bridges`, the sessions that connect two otherwise separate topics.
  These are often the most interesting sessions in the graph.

Then offer the visualisation:

```bash
open ~/.claude/session-brain/graph.html
```

Node size is session length, brightness is recency, hollow rings are history-only sessions, and
gold borders are bookmarked ones. The time slider and search box filter together.

## Notes

- **Never write to the vault** from this skill. If the user wants session knowledge in the vault,
  that is `wiki-history-ingest`.
- **History-only sessions are real.** Roughly 40% of a long-lived cache exists only as prompts in
  `history.jsonl`; those get graph nodes and are findable, but can never be loaded. Say so plainly
  rather than implying they are missing.
- The graph is derived data. If it looks wrong, `--full` rebuilds from scratch; nothing is lost.
