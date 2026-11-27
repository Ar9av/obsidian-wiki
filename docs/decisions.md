# Decision layer (optional)

The decision layer hands small, closed judgments to a **System One** decision model instead of
having the main agent read pages to make them. System One models answer typed questions (yes/no,
pick one) with calibrated probabilities and never write text. The first backend is TypeSafe's
[Jev](https://docs.typesafe.ai/concepts/system-one), called through
[`POST /v1/systemone`](https://docs.typesafe.ai/api).

The layer is **off by default** and the repo works the same without it: no key, no network, and
byte-identical output.

Three checks are in v1:

| Check | Used by | Question per item | Primitive | What changes |
|---|---|---|---|---|
| D1 relevance gate | `wiki-query` (`graph-query --decide`) | Would reading this page help answer the query? | Noul | Confident hits move up, confident misses drop, and `should_read` is rebuilt |
| D4 ingest triage | `wiki-ingest`, `wiki-dedup` (`decide triage`) | Is this page updated by, duplicated by, or unrelated to the source? | Choice | A verdict plus a ranked reading shortlist |
| D3 contradiction screen | `wiki-lint` (`decide contradictions`) | Do these two sections about the entity contradict, corroborate, add detail, or neither? | Choice | A prioritised reading list. It never decides |

The agent still does every read, write, merge, and answer. See [`skills/wiki-decisions`](../skills/wiki-decisions/SKILL.md)
for the agent-facing instructions.

## Enable

```bash
export TYPESAFE_API_KEY=...                 # never commit it; it is read from the environment only
export OBSIDIAN_WIKI_DECISIONS=typesafe     # or pass --decide per command
obsidian-wiki decide status --pretty        # shows config and key_present; makes no network call
```

| Variable | Default | Meaning |
|---|---|---|
| `OBSIDIAN_WIKI_DECISIONS` | `off` | `typesafe` (or `on`) turns the layer on for every command that supports it |
| `TYPESAFE_API_KEY` | — | Bearer key. Read from the environment only, never printed or logged |
| `OBSIDIAN_WIKI_DECISIONS_MODEL` | `jev-1.14.0` | Pinned, because thresholds only mean something against the model they were set on |
| `OBSIDIAN_WIKI_DECISIONS_ACT` | `0.9` | Confidence at or above which a decision is acted on |
| `OBSIDIAN_WIKI_DECISIONS_CONFIRM` | `0.5` | Confidence at or above which a decision is kept but flagged to confirm |
| `OBSIDIAN_WIKI_DECISIONS_TIMEOUT` | `5` | Seconds per backend call |
| `OBSIDIAN_WIKI_DECISIONS_URL` | `https://api.typesafe.ai` | Must be `https` (plain `http` is accepted only for loopback) |

The flags `--decide`, `--no-decide`, `--decide-act`, `--decide-confirm`, `--decide-timeout`,
`--decide-model`, and `--no-order-check` override the environment for one command. An unparseable
env value falls back to its default with a warning on stderr, so a typo never breaks the plain
command. A bad flag value exits with code 2.

## Commands

```bash
# D1: the wiki-query pre-pass, gated
obsidian-wiki graph-query "$VAULT" "how should tool errors be retried" --decide --pretty

# D4: triage a source before planning an ingest (or a vault page, for dedup)
obsidian-wiki decide triage path/to/source.md --vault "$VAULT" --decide --pretty

# D3: section pairs about the same entity, ranked for reading
obsidian-wiki decide contradictions --vault "$VAULT" [--entity entities/acme.md] [--max-pairs 40] --decide --pretty
```

Without the opt-in, `decide triage` and `decide contradictions` still run and return the plain
result: lexical order with an `undecided` verdict for triage, and every pair unscreened for the
contradiction screen. Each result has `decision.reason: "disabled"`.

## Confidence bands

| Band | Confidence | Behaviour |
|---|---|---|
| `act` | ≥ act (0.9) | Acted on: promote, drop, skip, or set the verdict |
| `confirm` | ≥ confirm (0.5) | Kept in place and flagged for the agent to confirm |
| `fallback` | < confirm | Treated as undecided, so the normal LLM path applies |

How each answer type maps to confidence:

- For a **Noul** (D1), confidence is the distance from 0.5 scaled to 0–1, which is the formula in
  [TypeSafe's confidence guide](https://docs.typesafe.ai/confidence). So `act` needs P(relevant) ≥ 0.95
  or ≤ 0.05, and anything from 0.25 to 0.75 is `fallback`.
- For a **Choice** (D3, D4), confidence is the probability of the chosen option, which the same guide
  recommends over the summary `confidence` field.

These defaults have **not been calibrated** on real vaults. Set them from a labelled sample of your own.

## Position bias

Decision models can favour an option or item because of where it sits in the request. Two
mitigations are built in:

- Candidates go into the state shuffled, under opaque ids `P0`, `P1`, …, so lexical rank and paths
  aren't visible. The seed comes from the input, so the same query always sends the same order and
  runs are reproducible.
- Each Choice is asked **twice in the same request**, with the options in opposite order. The two
  probability sets are averaged. If the two orderings pick different answers, the judgment is
  `order_flip: true` and is treated as `fallback`. `--no-order-check` turns this off and halves the
  question tokens.

## Fails open

Every decision function catches backend problems and returns the plain result, plus a `decision`
record with `failed_open: true` and a `reason`:

`missing_key`, `insecure_url`, `unknown_backend`, `timeout`, `network`, `http_<status>` (including `401`, `429`, `529`),
`invalid_response` (not JSON, no `answers`), `invalid_answer` (wrong type, missing question,
probability out of range).

There are no retries. A failed call costs one timeout at most and the work goes on without the
decision. None of the decision functions writes to the vault, and a test checks that every file is
byte-identical after all three checks run.

## Provenance

Every result carries a `decision` record:

```json
{
  "kind": "relevance_gate",
  "enabled": true,
  "backend": "typesafe",
  "model": "jev-1.14.0",
  "latency_ms": 412.3,
  "thresholds": {"act": 0.9, "confirm": 0.5},
  "failed_open": false,
  "reason": null,
  "usage": {"input_tokens": 512, "output_tokens": 24},
  "sent": true,
  "payload": {"fields": ["query", "title", "summary", "tags"], "pages": 6, "withheld_pii": 0}
}
```

`model` is the versioned ID the API reports. `sent` is `false` when nothing left the machine (for
example `missing_key`), and `null` when a timeout or network error leaves it unknown. Per-item
judgments carry their own `band`, probabilities, and, for Choices, `order_flip`.

## Privacy: what is sent

Nothing is sent unless the layer is on. When it is on, requests go only to the configured URL:

| Check | Sent | Never sent |
|---|---|---|
| D1 | the query (≤ 500 chars), plus each candidate's title, `summary` (≤ 400 chars), and tags | paths, bodies, `visibility/*` tags, pages tagged `visibility/pii` |
| D4 | the source body after its frontmatter (first 1,500 chars, `--max-source-chars`), plus candidate titles and summaries | paths, candidate bodies, `visibility/pii` pages |
| D3 | the entity title, plus each section's page title, heading, and text (≤ 1,200 chars, `--max-section-chars`) | paths, the rest of the page, `visibility/pii` pages |

Before anything is sent, emails, URLs with embedded credentials, and token-shaped strings (`sk-…`,
`ghp_…`, `AKIA…`, long hex, and long mixed letter-digit runs) are masked. D3 and D4 send page text
by necessity. Don't enable the layer on a vault whose content may not leave the machine. TypeSafe
does not train on requests, and zero data retention is available on enterprise plans
([Legal](https://docs.typesafe.ai/legal)).

## Benchmark

`tools/bench_decisions.py` compares the plain `graph-query` pre-pass with the gated one on
`examples/demo-vault`, using the 12-question gold set in `tools/bench/demo-vault-gold.jsonl`. It
reports recall@1/@3, MRR, the pages and estimated tokens in `should_read`, wall time, and
failed-open counts, and it also times triage and the contradiction screen.

```bash
python tools/bench_decisions.py                       # offline lexical mock: plumbing only
python tools/bench_decisions.py --mock-latency-ms 400 # what a ~0.4 s network call adds
TYPESAFE_API_KEY=... python tools/bench_decisions.py --backend typesafe --json > results.json
```

What the mock measures: **the gate adds wall-clock time to the pre-pass.** It adds one backend
round trip per query, about 400 ms at the latency the mock simulates. Any end-to-end saving has to
come from the agent opening fewer, or better, pages afterwards, which only a live run on real
questions can show. The mock's recall numbers come from a lexical stand-in and say nothing about
Jev's quality.

## Adding a backend

A backend is any object with `name`, `model`, and
`ask(state, questions) -> BackendAnswer` that raises `DecisionError` on failure
(`obsidian_wiki.decisions.DecisionBackend`). The request and answer shapes are System One's, so a
local decider that speaks the same shapes can be added in `make_backend` without touching the checks.
