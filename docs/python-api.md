# Python API

A vault can be used as agent memory by importing it, not just from the CLI.

```bash
pip install obsidian-wiki
```

```python
from obsidian_wiki import Memory

memory = Memory("~/brain", create=True)

memory.remember("stack", "Python, FastAPI", confidence=0.9)   # about the person
memory.add("Postgres was chosen over MySQL for partial indexes.")  # knowledge
memory.search("postgres")
memory.recap()                                                 # at session start
```

No API key, no embedding model, no vector store, no network. The vault is markdown files on disk, so everything it remembers is readable and diffable.

## Three verbs, not one

Vector memory layers take raw conversation messages and run an LLM *inside* `add()` to decide what is worth keeping. That is the right call when memory is a black box. It is the wrong call here: this package has no LLM and no API key, and the point of the vault is that a person can read and correct what it stored.

So the routing decision stays with the caller and is made explicit:

| Call | Stores | Lives in |
|---|---|---|
| `add(content)` | Knowledge — a thing that is true | `<category>/<slug>.md` |
| `remember(key, value)` | A durable fact about the person | `_meta/profile.md` |
| `todo(text)` | A thread to pick up next time | `_meta/todos.md` |

The caller already has an LLM. It does not need a second one hidden in the storage layer deciding which of the three a sentence belongs in.

## Reference

### `Memory(vault=None, *, user_id="", link_format="wikilink", create=False)`

Omit `vault` to use the Config Resolution Protocol: `OBSIDIAN_VAULT_PATH`, then a `.env` up the directory tree, then the global config.

### Knowledge

| Method | Returns |
|---|---|
| `add(content, *, title, category, tags, sources, summary, sync=True)` | `{path, title, category, created}` |
| `search(query, *, limit=8)` | list of `{path, title, summary, score, tier, should_read}` |
| `get(path)` | the page as markdown |
| `context(topic, *, budget=8000, recent=False)` | a token-bounded slice for a prompt |

`content` is a string or OpenAI-shaped messages (`[{"role": ..., "content": ...}]`). Messages are rendered verbatim — summarising is the caller's job.

Writing an existing title updates that page and keeps its original `created` date. `add` does not distil, dedupe, or cross-link; `/wiki-ingest` and `cross-linker` are the passes that do.

A derived title is deliberately dumb: the opening sentence, capped in words and characters, because it becomes a filename. Pass `title=` when you want a good one.

`search` is lexical and index-backed. `should_read` is the index's judgement on which results are worth opening in full; the rest are answerable from the summary.

**Lexical means terms must overlap.** Searching `"database choice"` will not find a page that only ever says "Postgres" and "MySQL" — there is no embedding to bridge the paraphrase. Give pages `tags=` and a `summary=` that use the words you will later search for. This is the main thing a semantic index would fix; see the honesty section below.

### Person-shaped memory

| Method | Returns |
|---|---|
| `remember(key, value, *, confidence=0.6, source, user_id)` | the fact |
| `forget(key, *, user_id)` | `True` if something was removed |
| `profile(*, user_id)` | list of facts |
| `todo(text, *, origin, user_id)` | the thread |
| `todos(*, include_closed=False, user_id)` | list, each with `stale` |
| `close_todo(id, *, dropped=False, user_id)` | the thread |
| `scopes()` | scope names with memory in this vault |

`confidence` is your own calibration, not a measurement. Stated outright is around 0.9; inferred from one session is around 0.5. Below 0.5, do not write it.

Staleness is **reported, never enforced**. An open thread untouched for 30 days is flagged; nothing closes it on the user's behalf.

### Session

| Method | Returns |
|---|---|
| `recap(*, project, max_words=350, min_confidence=0.0, user_id)` | the injectable block |
| `sync(verb, **fields)` | `{log_line, pages, hot_words, skipped}` |
| `status()` | index drift, hot budget, counts, migration state |

## Multi-user

`user_id` namespaces the **person-shaped** memory. Pages stay shared.

```python
alice = Memory("/srv/vault", user_id="alice")
bob   = Memory("/srv/vault", user_id="bob")

alice.remember("stack", "Go")
bob.remember("stack", "Rust")

alice.add("Partial indexes are a Postgres feature.")
bob.search("partial indexes")        # finds it — knowledge is shared
bob.profile()                         # Rust only — memory about a person is not
```

That split is the design, not a limitation: a vault is a shared brain, and only what it remembers *about someone* is per-someone. Each scope is its own readable file, `_meta/profile.alice.md`, which a person can open in Obsidian and correct.

A `user_id` arrives from a request in a server deployment, so it is validated as untrusted input: 1–64 characters of letters, digits, `.`, `_` or `-`. Anything else raises rather than touching the filesystem.

It is a **namespace, not an authorization boundary**. Anyone who can reach the vault can read any scope. For real isolation, run a vault per tenant.

Per-call overrides work too: `memory.remember("stack", "Rust", user_id="bob")`.

## How this compares

Honest positioning, because the alternatives are good and solve a different problem.

| | obsidian-wiki | mem0 | Zep / Graphiti | Letta |
|---|---|---|---|---|
| Stores memory as | markdown files | vector embeddings | temporal knowledge graph | agent state blocks |
| Human-readable | yes, it is the point | no | no | partly |
| Needs an LLM to write | no | yes, inside `add()` | yes | yes |
| Needs a vector/graph store | no | yes | yes | yes |
| Dependencies | none | several | several | several |
| Decides what to remember | you do | the library | the library | the agent |
| Retrieval | lexical + graph | semantic | temporal graph | tiered |
| Scoping | `user_id` on person-memory | `user_id` / `agent_id` / `run_id` | `session_id` | per agent |
| Version control | git, natively | export | export | export |

**Use a vector layer instead when** you need semantic recall over paraphrased text, you are happy for memory to be opaque, and you already run the infrastructure. `mem0`'s in-`add()` extraction is genuinely less work per call.

**Use this when** you want to read, grep, edit and `git log` what your agent remembers; when you do not want another database or another API key; and when the thing accumulating is knowledge worth keeping rather than a cache of conversation.

The honest weakness is retrieval: lexical matching misses paraphrase. The benchmark numbers are in [CLI Reference → Retrieval evals](cli.md#retrieval-evals), including `should_read_precision`, which is the metric a semantic index would improve.

## The other three faces

Same vault, same files, four ways in:

- **Python** — this page.
- **CLI** — [`obsidian-wiki memory`](cli.md#memory-surface), what the skills call.
- **MCP** — `memory_recap`, `memory_profile`, `memory_todo`, `memory_sync`, plus search/read/write, all taking `user_id`. See [Deployment](deployment.md).
- **REST** — `/v1/memory/*` on the same server.

## Related

- [Memory Surface](memory.md) — what the files are and who writes them
- [Deployment](deployment.md) — running a vault as a service
