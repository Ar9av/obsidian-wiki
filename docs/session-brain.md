# Session Brain

Your agent session history is a knowledge base you never get to search. You know you solved this before. You don't know the UUID.

The session brain builds a topic graph over that history — every Claude transcript plus the pruned sessions that survive only as prompts in `history.jsonl` — so you can find the session where something happened.

```bash
obsidian-wiki sessions-build                      # ~3s cold, under a second incrementally
obsidian-wiki sessions-query "prismor telemetry"  # ranked by relevance x recency
obsidian-wiki sessions-show <session-id>          # one session and its nearest neighbours
obsidian-wiki sessions-clusters                   # the discovered topics
open ~/.claude/session-brain/graph.html           # interactive graph, time slider, search
```

## Ingest vs. retrieve

This is the distinction that matters:

| You want | Use | Writes to |
|---|---|---|
| Knowledge preserved as permanent pages | `/wiki-history-ingest` | The vault |
| To find the session where something happened | `/session-brain` + `/wiki-sessions` | A sidecar only |

The session brain **never writes to your vault**. Everything lands in `~/.claude/session-brain/` (override with `WIKI_SESSION_BRAIN_DIR`).

## How the clustering works

Local TF-IDF plus community detection over a k-nearest-neighbour graph. No embeddings, no API calls, no new dependencies — which is why a cold build takes about three seconds.

Ranking applies an exponential 90-day time decay with a floor, so recent work surfaces first while an old exact match still beats a fresh weak one. Tune the half-life at build time with `--half-life`, or override it per query.

## From an agent

| Command | What it does |
|---|---|
| `/session-brain` | Build the graph and name the discovered topic clusters |
| `/wiki-sessions <topic>` | Find the matching session and load its transcript into the current conversation |

Cluster names assigned via `/session-brain` are durable — they survive rebuilds, stored separately from the generated graph.

## Tuning the build

```bash
obsidian-wiki sessions-build --k 12 --min-sim 0.12 --mutual
```

| Flag | Effect |
|---|---|
| `--k N` | Neighbours per session (default 8). Higher → denser graph, larger clusters |
| `--min-sim F` | Minimum cosine similarity for an edge (default 0.08). Higher → fewer, stronger links |
| `--mutual` | Keep only mutual kNN edges — tighter, smaller, more precise clusters |
| `--half-life D` | Recency half-life in days (default 90) |
| `--since DATE` | Only read sessions modified on or after an ISO date |
| `--skip a,b` | Skip project dirs matching these substrings (or set `WIKI_SKIP_PROJECTS`) |
| `--full` | Ignore caches and re-read every session |
| `--no-html` | Skip writing `graph.html` |
| `--claude-dir PATH` | Read a different agent session cache |

> Cache directory names begin with `-`, which argparse reads as a flag. Pass the bare name (`--skip game`) or use `--skip=-w-game`.

Rebuilds are incremental by default — only sessions whose mtime changed get re-read.

## Querying

```bash
obsidian-wiki sessions-query "auth bug" --project my-app --top 20
obsidian-wiki sessions-query "telemetry" --cluster 3 --since 2026-01-01 --json
```

| Flag | Effect |
|---|---|
| `--top N` | Candidates to return (default 10) |
| `--max-load N` | Max sessions recommended for loading (default 3) |
| `--project NAME` | Restrict to one project |
| `--cluster ID` | Restrict to one topic cluster |
| `--since DATE` | Only sessions ending on or after this ISO date |
| `--min-score F` | Drop candidates below this score (default 0.05) |
| `--half-life D` | Override the build-time recency half-life |

## The interactive graph

```bash
open ~/.claude/session-brain/graph.html
```

Self-contained HTML — no server, no build step. Nodes are sessions, colored by cluster; the time slider filters by recency; search highlights matches in place.

Skip generating it with `--no-html` if you only use the CLI.
