# Deployment — run your vault as a memory service

Everything else in this project is local: skills on your machine, a vault on your disk. This is the
one piece that puts a vault behind a URL, so an agent somewhere else — another machine, CI, a hosted
product — can search it and write to it.

**One container, one vault, one API key.** The vault stays plain markdown on a mounted volume, so
you can still open it in Obsidian. The container does no LLM work: it searches, reads, writes, and
packs. The calling agent does the thinking.

## Run it

```bash
echo "WIKI_API_KEY=$(openssl rand -hex 24)" > .env
docker compose up --build
```

The vault lives in the named volume `wiki-data`. To use a vault you already have, swap the volume
for a bind mount:

```yaml
volumes:
  - /path/to/your/vault:/vault
```

Locally, without Docker:

```bash
pip install 'obsidian-wiki[server]'
WIKI_API_KEY=dev OBSIDIAN_VAULT_PATH=~/vault python -m obsidian_wiki.server
```

## Web viewer

`obsidian-wiki ui` opens a browser viewer for the resolved vault on `http://127.0.0.1:3114/ui`: an overview, page browser with search, rendered pages with backlinks, the link graph, the activity log, profile facts and open threads (add, close, forget), the hot cache, and the health, staging and sources views. It binds to loopback only and needs no key unless `WIKI_API_KEY` is set. `--port` and `--vault` override the defaults; `--no-open` skips the browser tab.

**Connect an agent** (in the viewer's sidebar) generates ready-to-paste MCP configs for Claude Code, Codex, Cursor, Claude Desktop, Gemini CLI, VS Code / Copilot, Windsurf, and any other MCP client, either over stdio or over HTTP to this server. The stdio configs launch `python -m obsidian_wiki mcp --vault <vault>` with the server's own interpreter, so they work in GUI apps that can't see your `PATH`. HTTP configs read the key from `WIKI_API_KEY` and never embed it. The page also gives you instructions to paste into `AGENTS.md` or a system prompt, so the agent actually calls `memory_recap` at session start and saves findings back.

The same viewer is served at `/ui` by the HTTP server above, behind its API key (it asks once and keeps the key in `sessionStorage`).

The viewer is a React app built with [Saas UI](https://saas-ui.dev) (Chakra UI). The source is in `ui/` and the built bundle is committed to `obsidian_wiki/webui/`, so installing the package needs no Node. After changing `ui/src`, rebuild with `cd ui && npm install && npm run build`. `npm run dev` gives hot reload against a running `obsidian-wiki ui --no-open`.

## Configuration

| Variable | What it does | Default |
|---|---|---|
| `OBSIDIAN_VAULT_PATH` | Vault the service serves | `/vault` |
| `WIKI_API_KEY` | Bearer token for every `/v1/*` and `/mcp` request | *(none — required)* |
| `WIKI_ALLOW_ANONYMOUS` | `1` disables auth entirely. Local development only | *(unset)* |
| `WIKI_PORT` | Port to listen on | `8080` |
| `WIKI_HOST` | Interface to bind. The Docker image sets `0.0.0.0`; override only to expose the server deliberately | `127.0.0.1` |

The process **refuses to start** without `WIKI_API_KEY` unless `WIKI_ALLOW_ANONYMOUS=1`. There is no
default key.

## Connect an agent (MCP)

```bash
claude mcp add --transport http wiki-memory http://localhost:8080/mcp/ \
  --header "Authorization: Bearer $WIKI_API_KEY"
```

Eight tools. Four for knowledge — `memory_search`, `memory_read`, `memory_write`, `memory_context_pack` — and four for memory proper: `memory_recap`, `memory_profile`, `memory_todo`, and `memory_sync`.

`memory_recap` is the one to call at session start: it returns the owner profile, open threads, and recent activity as a single block, optionally scoped to a `project`.

`memory_recap`, `memory_profile` and `memory_todo` all take a **`user_id`**, which namespaces that person's profile and todo list so one deployment can serve several people. Pages stay shared. A `user_id` becomes a filename, so it is validated as untrusted input — 1–64 characters of letters, digits, `.`, `_` or `-` — and anything else is a **400** rather than a filesystem touch.

For an agent on the same machine, skip the HTTP server and let the agent launch the tools over stdio. It needs the same `[server]` extra, no key (stdio opens no port), and finds the vault the way every other command does:

```bash
claude mcp add wiki-memory -- obsidian-wiki mcp
```

Any agent that takes a stdio MCP server can use the same command; pass `--vault <path>` to pin one vault.

For in-process use, `from obsidian_wiki import Memory` skips the server entirely — see [Python API](python-api.md).

## REST

Every route below `/v1` needs `Authorization: Bearer <key>`. `/health` does not.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Liveness; also reports whether the vault directory exists |
| `GET` | `/v1/search?q=&limit=` | Ranked pages with summaries, from the same GraphRAG index the `wiki-query` skill uses |
| `GET` | `/v1/pages/{path}` | One page as markdown, by vault-relative path |
| `POST` | `/v1/pages` | `{title, category, content, tags, sources, summary, upsert}` |
| `POST` | `/v1/context-pack` | `{topic, budget, recent, public_only, metadata_only}` |
| `GET` | `/v1/memory/recap?project=&max_words=&user_id=` | Owner profile, open threads, recent activity |
| `GET` | `/v1/memory/profile?user_id=` | Durable facts about a person |
| `POST` | `/v1/memory/profile` | `{action: set\|forget, key, value, confidence, source, user_id}` |
| `GET` | `/v1/memory/todos?include_closed=&user_id=` | Threads carried between sessions |
| `POST` | `/v1/memory/todos` | `{action: add\|done\|drop, text, todo_id, origin, user_id}` |
| `POST` | `/v1/memory/sync` | `{verb, takeaways, fields}` — reconcile index and hot cache |

```bash
curl -X POST localhost:8080/v1/pages -H "Authorization: Bearer $WIKI_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"title":"Merkle Tree","category":"concepts","summary":"Hash tree for cheap diffing.","content":"Each node hashes its children."}'
# -> {"path":"concepts/merkle-tree.md", ...}
```

Writes land at `<category>/<slug-of-title>.md` with the six required frontmatter keys plus `summary`,
and append a line to `log.md` through the shared memory writer, so an API write is locked and
parseable like every other operation. `created:` is preserved across updates. Use `category: "_raw"` for a
rough capture you intend to promote with `wiki-ingest` later — the same role `_raw/` plays for the
`wiki-capture` skill.

`POST /v1/pages` writes exactly what you send. It does not distil, dedupe, or cross-link — those are
the agent's job, via the `wiki-capture` and `cross-linker` skills. Call `POST /v1/memory/sync`
afterwards to fold the new pages into `index.md` and `hot.md`.

On a vault whose memory files predate this writer, `memory_sync` and `POST /v1/memory/sync` return
**409** rather than overwriting curated files. Run `obsidian-wiki memory migrate --apply` against
the mounted vault once — see [Memory Surface](memory.md#adopting-an-existing-vault).

## Backups

The vault is a directory, so back it up like one:

```bash
docker run --rm -v wiki-data:/vault -v ~/.aws:/root/.aws:ro amazon/aws-cli \
  s3 sync /vault s3://your-bucket/vault
```

Or point the vault at a git remote and use `obsidian-wiki sync` — see
[Configuration](configuration.md).

## What this is not

Single-tenant: one container serves one vault behind one key. `user_id` separates *memory about people* within that vault, which is enough for a team sharing one brain; it is not per-user isolation and is not an authorization boundary — anyone with the key can read any scope. No per-user isolation, no quotas, no
rate limiting, no billing. To serve several people, run a container per vault and put a reverse proxy
in front. Terminate TLS at that proxy — the container speaks plain HTTP, and the API key is only as
private as the connection carrying it.
