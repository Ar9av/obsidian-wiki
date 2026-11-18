# Deployment — self-host your vault as a memory service

Everything else in this project is local: skills on your machine, a vault on your disk. This is the
one piece that puts a vault behind a URL, so an agent somewhere else (another machine, CI, a hosted
product, Claude on your phone) can search it and write to it over MCP or REST.

**One container, one vault, one API key** (plus an optional read-only key). The vault stays plain
markdown on a mounted volume, so you can still open it in Obsidian. The container does no LLM work:
it searches, reads, writes, and packs. The calling agent does the thinking.

## Run it

The image is published to GHCR on every release, so there is nothing to build:

```bash
curl -fsSLO https://raw.githubusercontent.com/Ar9av/obsidian-wiki/main/docker-compose.yml
echo "WIKI_API_KEY=$(openssl rand -hex 24)" > .env
docker compose up -d
curl localhost:8080/health
```

Or with plain Docker:

```bash
docker run -d --name wiki -p 127.0.0.1:8080:8080 \
  -e WIKI_API_KEY=... -v wiki-data:/vault ghcr.io/ar9av/obsidian-wiki:latest
```

The vault lives in the named volume `wiki-data`. To serve a vault you already have, swap the volume
for a bind mount (`/path/to/your/vault:/vault`). From a checkout, `docker compose up --build` builds
the image from source instead. Pin a release with `WIKI_VERSION=2026.11.6` in `.env`.

The compose file publishes the port on **loopback only**: until TLS sits in front, the API key
travels in plain HTTP. Set `WIKI_PUBLISH=8080` to reach it from your LAN anyway, or read
[HTTPS](#https) below.

Without Docker, `serve` runs the same server for whatever vault the CLI resolves (`--vault` overrides):

```bash
pip install 'obsidian-wiki[server]'
WIKI_API_KEY=$(openssl rand -hex 24) obsidian-wiki serve            # http://127.0.0.1:8080
obsidian-wiki serve --host 0.0.0.0 --port 8080                     # behind your own proxy
```

`serve` binds loopback unless you pass `--host`, and refuses `WIKI_ALLOW_ANONYMOUS=1` on any other
interface. `python -m obsidian_wiki.server` still works and reads only the environment.

## HTTPS

Anything off your machine should reach the server over TLS. Three ways, easiest first:

- **Caddy, bundled.** Point a domain's DNS at the host, open ports 80 and 443, and start the `tls`
  profile. Caddy gets and renews a Let's Encrypt certificate on its own
  ([`deploy/Caddyfile`](../deploy/Caddyfile)):

  ```bash
  echo "WIKI_DOMAIN=wiki.example.com" >> .env
  docker compose --profile tls up -d     # https://wiki.example.com/mcp/
  ```

- **Tailscale.** For a server only your own devices reach, `tailscale serve --bg 8080` gives it an
  HTTPS address on your tailnet with no ports opened. Hosted clients such as claude.ai connect from
  the public internet, so they can't reach a tailnet-only address; `tailscale funnel 8080` makes it
  public.
- **Your own proxy** (nginx, Traefik, a cloud load balancer). Forward to port 8080 and don't buffer
  responses: MCP answers as `text/event-stream`.

## Keep the server and your laptop on one vault

A container's vault and the copy your laptop's Obsidian opens are two directories. Point both at one
git repository and the server keeps them in step: every `WIKI_GIT_SYNC_INTERVAL` seconds it commits
its own writes, rebases onto the remote, and pushes.

```bash
# .env
WIKI_GIT_REMOTE=https://x-access-token:<token>@github.com/you/brain.git
WIKI_GIT_SYNC_INTERVAL=300
```

- **On first start** an empty vault is cloned from `WIKI_GIT_REMOTE`. An existing checkout keeps its
  own `origin`. A non-empty folder that isn't a repo is initialised, and the first sync pushes it.
  No file is ever deleted or overwritten.
- **Each cycle** commits, then `fetch` + `rebase --autostash` + `push`. API writes and the
  memory writer are held off while the working tree changes, so a rebase never lands on a
  half-written page. One last sync runs at shutdown.
- **On a conflict** (the same page edited on both sides) the rebase is aborted, the server's edit
  stays committed locally, and nothing is pushed until you resolve it from a clone. `/health` shows
  `git_sync_ok: false`; `/v1/status` gives the message.
- **Lock files and caches** (`.memory.lock`, `.graph-cache.json` and friends) go into the clone's
  `.git/info/exclude`, so they're never committed and your `.gitignore` is left alone.
- **Credentials:** a token in the HTTPS URL (a fine-grained token with write access to that one
  repo), or an SSH remote with a key mounted at `/home/wiki/.ssh`. Tokens are redacted from every
  sync message. Commits are authored as `obsidian-wiki server`; set `GIT_AUTHOR_NAME` /
  `GIT_AUTHOR_EMAIL` to change that.

On the laptop, push and pull as usual: by hand, with `obsidian-wiki sync`, or with the Obsidian Git
plugin. Syncthing or any other folder sync on a bind-mounted vault works too. Leave
`WIKI_GIT_SYNC_INTERVAL` unset in that case.

## Read-only access

Set `WIKI_READ_KEY` to a second, different key and hand it to agents that should consult the vault
but not edit it (a CI job, a shared team bot, a hosted product you're trying out):

- Over **MCP** that key sees four tools: `memory_search`, `memory_read`, `memory_context_pack`
  and `memory_recap`. The write tools are not listed at all, so the agent never plans around one it
  can't call.
- Over **REST**, every write route answers **403**.

Set `WIKI_READ_KEY` without `WIKI_API_KEY` and the whole server is read-only.

Every tool also carries MCP annotations: `readOnlyHint` on the reads, and `destructiveHint` on
`memory_write` and `memory_profile`, which can overwrite or forget. A client can use them to
auto-approve reads and ask before writes.

## Web viewer

`obsidian-wiki ui` opens a browser viewer for the resolved vault on `http://127.0.0.1:3114/ui`: an overview, page browser with search, rendered pages with backlinks, the link graph, the activity log, profile facts and open threads (add, close, forget), the hot cache, and the health, staging and sources views. It binds to loopback only and needs no key unless `WIKI_API_KEY` is set. `--port` and `--vault` override the defaults; `--no-open` skips the browser tab.

**Connect an agent** (in the viewer's sidebar) generates ready-to-paste MCP configs for Claude Code, Codex, Cursor, Claude Desktop, Gemini CLI, VS Code / Copilot, Windsurf, and any other MCP client, either over stdio or over HTTP to this server. The stdio configs launch `python -m obsidian_wiki mcp --vault <vault>` with the server's own interpreter, so they work in GUI apps that can't see your `PATH`. HTTP configs read the key from `WIKI_API_KEY` and never embed it. The page also gives you instructions to paste into `AGENTS.md` or a system prompt, so the agent actually calls `memory_recap` at session start and saves findings back.

The same viewer is served at `/ui` by the HTTP server above, behind its API key (it asks once and keeps the key in `sessionStorage`).

The viewer is a React app built with [Saas UI](https://saas-ui.dev) (Chakra UI). The source is in `ui/` and the built bundle is committed to `obsidian_wiki/webui/`, so installing the package needs no Node. After changing `ui/src`, rebuild with `cd ui && npm install && npm run build`. `npm run dev` gives hot reload against a running `obsidian-wiki ui --no-open`.

## Configuration

| Variable | What it does | Default |
|---|---|---|
| `OBSIDIAN_VAULT_PATH` | Vault the service serves | `/vault` |
| `WIKI_API_KEY` | Bearer token for every `/v1/*` and `/mcp` request; full read-write access | *(none)* |
| `WIKI_READ_KEY` | Second bearer token that can search and read but never write. Alone, it makes the server read-only | *(unset)* |
| `WIKI_ALLOW_ANONYMOUS` | `1` disables auth entirely. Local development only; `serve` refuses it off loopback | *(unset)* |
| `WIKI_PORT` | Port to listen on | `8080` |
| `WIKI_HOST` | Interface to bind. The Docker image sets `0.0.0.0`; override only to expose the server deliberately | `127.0.0.1` |
| `WIKI_GIT_REMOTE` | Git remote to clone an empty vault from at start | *(unset)* |
| `WIKI_GIT_SYNC_INTERVAL` | Seconds between two-way git syncs; `0` turns sync off | `0` |

The process **refuses to start** without `WIKI_API_KEY` or `WIKI_READ_KEY`, unless
`WIKI_ALLOW_ANONYMOUS=1`. There is no default key, and the two keys must differ.

Read only by `docker-compose.yml`: `WIKI_VERSION` (image tag, default `latest`), `WIKI_PUBLISH`
(host port mapping, default `127.0.0.1:8080`), and `WIKI_DOMAIN` (the `tls` profile's hostname).

## Connect an agent (MCP)

The endpoint is `https://<your-host>/mcp/` (streamable HTTP), with `Authorization: Bearer <key>`.
Keep the key in an environment variable rather than pasting it into a config file. The viewer's
**Connect an agent** page writes these for you.

**Claude Code**

```bash
claude mcp add --scope user --transport http wiki-memory https://wiki.example.com/mcp/ \
  --header "Authorization: Bearer $WIKI_API_KEY"
```

**Codex** (`~/.codex/config.toml`)

```toml
[mcp_servers.wiki-memory]
url = "https://wiki.example.com/mcp/"
bearer_token_env_var = "WIKI_API_KEY"
```

**Cursor** (`~/.cursor/mcp.json`)

```json
{ "mcpServers": { "wiki-memory": {
    "url": "https://wiki.example.com/mcp/",
    "headers": { "Authorization": "Bearer ${env:WIKI_API_KEY}" } } } }
```

**VS Code / Copilot** (`.vscode/mcp.json`)

```json
{ "inputs": [{ "type": "promptString", "id": "wiki-key", "description": "WIKI_API_KEY", "password": true }],
  "servers": { "wiki-memory": { "type": "http", "url": "https://wiki.example.com/mcp/",
    "headers": { "Authorization": "Bearer ${input:wiki-key}" } } } }
```

**Claude Desktop and claude.ai**: add it under **Settings → Connectors → Add custom connector**
with the URL and an `Authorization: Bearer …` request header. Claude connects from Anthropic's
cloud, so the server needs a public HTTPS address (the Caddy profile, or `tailscale funnel`). For a
server only your machine can reach, bridge it into `claude_desktop_config.json` with
[`mcp-remote`](https://github.com/geelen/mcp-remote):

```json
{ "mcpServers": { "wiki-memory": {
    "command": "npx",
    "args": ["-y", "mcp-remote", "http://localhost:8080/mcp/", "--header", "Authorization:${WIKI_AUTH}"],
    "env": { "WIKI_AUTH": "Bearer <your key>" } } } }
```

Eight tools. Four for knowledge — `memory_search`, `memory_read`, `memory_write`, `memory_context_pack` — and four for memory proper: `memory_recap`, `memory_profile`, `memory_todo`, and `memory_sync`. A [read-only key](#read-only-access) sees four of them.

`memory_recap` is the one to call at session start: it returns the owner profile, open threads, and recent activity as a single block, optionally scoped to a `project`.

`memory_recap`, `memory_profile` and `memory_todo` all take a **`user_id`**, which namespaces that person's profile and todo list so one deployment can serve several people. Pages stay shared. A `user_id` becomes a filename, so it is validated as untrusted input — 1–64 characters of letters, digits, `.`, `_` or `-` — and anything else is a **400** rather than a filesystem touch.

For an agent on the same machine, skip the HTTP server and let the agent launch the tools over stdio. It needs the same `[server]` extra, no key (stdio opens no port), and finds the vault the way every other command does:

```bash
claude mcp add wiki-memory -- obsidian-wiki mcp
```

Any agent that takes a stdio MCP server can use the same command; pass `--vault <path>` to pin one vault.

For in-process use, `from obsidian_wiki import Memory` skips the server entirely — see [Python API](python-api.md).

## REST

Every route below `/v1` needs `Authorization: Bearer <key>`. `/health` does not. With the read-only key, the `POST` routes that write (`/v1/pages`, `/v1/memory/*`) answer **403**; `/v1/context-pack` only reads and stays open to it.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Liveness; also reports whether the vault directory exists, and `git_sync_ok` when sync is on |
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

Single-tenant: one container serves one vault behind one key (and optionally one read-only key). `user_id` separates *memory about people* within that vault, which is enough for a team sharing one brain; it is not per-user isolation and is not an authorization boundary — anyone with the key can read any scope. No per-user isolation, no quotas, no
rate limiting, no billing. To serve several people, run a container per vault and put a reverse proxy
in front. Terminate TLS at that proxy — the container speaks plain HTTP, and the API key is only as
private as the connection carrying it.
