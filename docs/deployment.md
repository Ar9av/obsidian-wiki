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

## Sign in with OAuth

Some clients would rather sign in than be handed a header: claude.ai and ChatGPT connectors,
Cursor, VS Code, and Codex (`codex mcp login`). Turn on OAuth 2.1 and they discover it from the
server's 401, register themselves, and open a sign-in page:

```bash
# .env, next to the tls profile's WIKI_DOMAIN
WIKI_OAUTH=1
WIKI_PUBLIC_URL=https://wiki.example.com
```

- **Signing in** means typing a vault key into the server's consent page. `WIKI_API_KEY` grants
  `wiki:read` and `wiki:write`; `WIKI_READ_KEY` grants `wiki:read` only, and that client then
  sees the four read tools, like a read-only key. The page names the app and where the grant is
  sent; approve only connections you started.
- **Tokens** are standard: PKCE, dynamic client registration (RFC 7591), protected-resource
  metadata (RFC 9728), one-hour access tokens, and 30-day refresh tokens that rotate on every use.
  The protocol handling is the MCP SDK's; this server supplies storage and the consent step.
- **Storage** is `<vault>/.wiki-server/oauth.json`, holding SHA-256 digests rather than tokens, so
  the file grants nothing if it leaks. The folder carries its own `.gitignore`, so no git setup
  commits it.
- **Revoking:** `GET /v1/oauth/clients` lists signed-in apps; `DELETE /v1/oauth/clients/{id}`
  revokes one. Both need the write key. Deleting `oauth.json` revokes them all.

`WIKI_PUBLIC_URL` must be the exact `https://` address clients use: it is the token issuer, and
it can't be inferred from a request behind a proxy. Static bearer keys keep working alongside
OAuth.

## Rate limits and lockout

Every request except `/health` counts toward a per-client limit, 600 a minute by default
(`WIKI_RATE_LIMIT`). After 10 rejected credentials in 5 minutes (`WIKI_AUTH_LOCKOUT`,
`WIKI_AUTH_LOCKOUT_SECONDS`), that client gets **429** with `Retry-After` until the window passes,
without its credentials being checked, so a lucky guess during the lockout reveals nothing.
Rejected bearer keys, OAuth tokens and keys typed on the consent page all count. A request that
carries no credential doesn't: MCP clients send exactly that to discover OAuth. Set either limit to
`0` to turn it off.

"Client" means the connecting address. Behind a reverse proxy that is the proxy, which would make
both limits global, so tell the server which peers may name the real client in `X-Forwarded-For`:
`WIKI_TRUSTED_PROXIES` takes addresses, CIDRs, or `*`. The compose file, `fly.toml` and
`render.yaml` set `*`, since only their proxy reaches the server. If you publish the port directly
on a network, set it to your proxy's address or leave it empty, or a client could spoof the
header to dodge the limits.

## Deploy to a platform

Each template runs the released image with a persistent volume at `/vault` and checks `/health`.
The platform terminates TLS. The server listens on `$PORT` when the platform assigns one. After
the first deploy, set `WIKI_PUBLIC_URL` to the platform's address if you turn on OAuth.

### Fly.io

```bash
fly launch --no-deploy --copy-config -c deploy/fly.toml --name <your-app>
fly volumes create wiki_data --size 1
fly secrets set WIKI_API_KEY=$(openssl rand -hex 24)
fly deploy -c deploy/fly.toml              # https://<your-app>.fly.dev/mcp/
```

[`deploy/fly.toml`](../deploy/fly.toml) keeps one machine running, because it owns the volume
and runs git sync.

### Render

[Deploy to Render](https://render.com/deploy?repo=https://github.com/Ar9av/obsidian-wiki) reads
[`render.yaml`](../render.yaml): a web service from the image with a 1 GB disk, and a generated
`WIKI_API_KEY` (copy it from the service's Environment tab). Persistent disks need a paid instance
type.

### Railway

Create a service from this repo, then point **Settings → Config-as-code** at
[`deploy/railway.json`](../deploy/railway.json). It builds the Dockerfile, checks `/health`, and
refuses to deploy until a volume is mounted at `/vault`. Add the volume and `WIKI_API_KEY`
(plus `WIKI_TRUSTED_PROXIES=*`), then generate a domain under **Networking**.

## MCP Registry

The server is listed in the official [MCP Registry](https://registry.modelcontextprotocol.io) as
`io.github.Ar9av/obsidian-wiki`, from [`server.json`](../server.json). Clients that browse the
registry (VS Code, Copilot) can install it three ways:

- the PyPI package over stdio: `uvx --with fastapi --with mcp obsidian-wiki mcp`
- the image over stdio, with your vault mounted
- a remote entry pointing at your own host

Every release tag re-publishes it from `.github/workflows/mcp-registry.yml`, once PyPI and GHCR
have the new version. The registry checks ownership against the `mcp-name:` comment in the README
and the image's `io.modelcontextprotocol.server.name` label.

## Web viewer

`obsidian-wiki ui` opens a browser viewer for the resolved vault on `http://127.0.0.1:3114/ui`: an overview, page browser with search, rendered pages with backlinks, the link graph, the activity log, profile facts and open threads (add, close, forget), the hot cache, and the health, staging and sources views. It binds to loopback only and needs no key unless `WIKI_API_KEY` is set. `--port` and `--vault` override the defaults; `--no-open` skips the browser tab.

**Connect an agent** (in the viewer's sidebar) generates ready-to-paste MCP configs for Claude Code, Codex, Cursor, Claude Desktop, Gemini CLI, VS Code / Copilot, Windsurf, and any other MCP client, either over stdio or over HTTP to this server. The stdio configs launch `python -m obsidian_wiki mcp --vault <vault>` with the server's own interpreter, so they work in GUI apps that can't see your `PATH`. HTTP configs read the key from `WIKI_API_KEY` and never embed it. The server also sends usage instructions to every MCP client when it connects (the read-only server sends only the read half), so most agents call `memory_recap` at session start without any setup. For a client that ignores server instructions, the page gives you the same text to paste into `AGENTS.md` or a system prompt.

### Working from the viewer

The viewer does more than browse:

- **Vault switcher** (top of the sidebar). It lists the vault the server started on, your global default, and every `config.<name>` that `/wiki-switch` manages. Picking one repoints this server, MCP clients included. Your default vault stays the same, and only configured vaults can be opened.
- **Inbox.** Drop files anywhere in the window, paste a note (a pasted screenshot becomes its own file), or add a link with a line on why it matters. Each item lands at the top level of `_raw/`, which the next `wiki-ingest` reads in raw mode. Files are capped at 25 MB.
- **Ask.** Answers come from a context pack of your own pages, with each claim cited as a link to its page and a "Worth adding" list of gaps. Turn on web search to fill those gaps; web findings go in their own section with URLs. **Save to inbox** files an answer for the next ingest.
- **Insights.** The `graph-analyse` output: questions your graph raises, bridge pages, unexpected connections, hubs, clusters, and blind spots (pages with no links in or out).
- **Actions.** What the vault needs next (files waiting in `_raw/`, lint findings, staged writes, lost sources, stale threads, uncommitted changes), plus one-click runs of `wiki-ingest`, `wiki-lint`, `cross-linker`, `wiki-synthesize` and `wiki-digest`.

Ask and Actions need a model, set up under **Settings**:

| Provider | Uses | Covers |
|---|---|---|
| Claude Code CLI | `claude -p` on this machine, signed in as you, so a Claude subscription works | Ask and agent jobs |
| Anthropic API key | The `anthropic` SDK (in the `[server]` extra), billed to your API account; defaults to `claude-opus-5-5` | Ask only |

**Automatic** (the default) picks Claude Code when it is on `PATH`, else the key. Agent jobs always need Claude Code because they edit files. A job runs `claude -p` in the vault with `--permission-mode acceptEdits` and an allowlist of file tools plus `obsidian-wiki`, `mkdir`, `mv` and `ls`. Settings live in `<global config dir>/ui-settings.json` (mode 0600), outside the vault so a key is never committed. The browser sees whether a key is set and its last four characters, never the key itself.

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
| `WIKI_OAUTH` | `1` turns on [OAuth sign-in](#sign-in-with-oauth) for MCP clients | *(unset)* |
| `WIKI_PUBLIC_URL` | The `https://` address clients reach; required with `WIKI_OAUTH=1` | *(unset)* |
| `WIKI_RATE_LIMIT` | Requests per client per minute; `0` is off | `600` |
| `WIKI_AUTH_LOCKOUT` | Rejected credentials before a client is locked out; `0` is off | `10` |
| `WIKI_AUTH_LOCKOUT_SECONDS` | Window for counting failures, and how long a lockout lasts | `300` |
| `WIKI_TRUSTED_PROXIES` | Peers whose `X-Forwarded-For` names the client (addresses, CIDRs, or `*`) | `127.0.0.1` |

`WIKI_PORT` falls back to `PORT` (what Render and Railway assign), then `8080`.

The process **refuses to start** without `WIKI_API_KEY` or `WIKI_READ_KEY`, unless
`WIKI_ALLOW_ANONYMOUS=1`. There is no default key, and the two keys must differ.

Read only by `docker-compose.yml`: `WIKI_VERSION` (image tag, default `latest`), `WIKI_PUBLISH`
(host port mapping, default `127.0.0.1:8080`), and `WIKI_DOMAIN` (the `tls` profile's hostname).

## Connect an agent (MCP)

The endpoint is `https://<your-host>/mcp/` (streamable HTTP), with `Authorization: Bearer <key>`.
Keep the key in an environment variable rather than pasting it into a config file. The viewer's
**Connect an agent** page writes these for you. With [OAuth](#sign-in-with-oauth) on, drop the
header in any client that supports sign-in (Codex: `codex mcp login wiki-memory`).

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
with the URL and an `Authorization: Bearer …` request header, or with no header when OAuth is on
(Claude opens the sign-in page). Claude connects from Anthropic's
cloud, so the server needs a public HTTPS address (the Caddy profile, or `tailscale funnel`). For a
server only your machine can reach, bridge it into `claude_desktop_config.json` with
[`mcp-remote`](https://github.com/geelen/mcp-remote):

```json
{ "mcpServers": { "wiki-memory": {
    "command": "npx",
    "args": ["-y", "mcp-remote", "http://localhost:8080/mcp/", "--header", "Authorization:${WIKI_AUTH}"],
    "env": { "WIKI_AUTH": "Bearer <your key>" } } } }
```

Nine tools. Five for knowledge — `memory_search`, `memory_read`, `memory_write`, `memory_forget`, `memory_context_pack` — and four for memory proper: `memory_recap`, `memory_profile`, `memory_todo`, and `memory_sync`. A [read-only key](#read-only-access) sees four of them.

`memory_forget` takes a page path and moves the page to `_archives/forgotten/<date>/<same path>` instead of deleting it. Search, the graph and lint skip that folder and git keeps it, so restoring is moving the file back. Links to a forgotten page become broken, so call `memory_sync` afterward. `index.md`, `log.md`, `hot.md` and anything under `_`- or `.`-prefixed folders are refused.

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
| `GET` | `/v1/search?q=&limit=&path_prefix=` | Ranked pages with summaries, (optionally one folder via `path_prefix`) from the same GraphRAG index the `wiki-query` skill uses |
| `GET` | `/v1/pages/{path}` | One page as markdown, by vault-relative path |
| `POST` | `/v1/pages` | `{title, category, content, tags, sources, summary, upsert}` |
| `POST` | `/v1/context-pack` | `{topic, budget, recent, public_only, metadata_only}` |
| `GET` | `/v1/memory/recap?project=&max_words=&user_id=` | Owner profile, open threads, recent activity |
| `GET` | `/v1/memory/profile?user_id=` | Durable facts about a person |
| `POST` | `/v1/memory/profile` | `{action: set\|forget, key, value, confidence, source, user_id}` |
| `GET` | `/v1/memory/todos?include_closed=&user_id=` | Threads carried between sessions |
| `POST` | `/v1/memory/todos` | `{action: add\|done\|drop, text, todo_id, origin, user_id}` |
| `POST` | `/v1/memory/sync` | `{verb, takeaways, fields}` — reconcile index and hot cache |
| `GET` `POST` | `/v1/vaults` | List configured vaults; `{path}` switches to one of them |
| `GET` `POST` | `/v1/inbox` | List top-level `_raw/` files; `{kind: text\|url\|file, title, text, url, filename, data_b64}` adds one |
| `POST` | `/v1/inbox/remove` | `{name}` deletes one top-level `_raw/` file |
| `GET` | `/v1/insights` | Graph analysis: hubs, bridges, communities, suggested questions |
| `POST` | `/v1/ask` | `{question, web}` answers from the vault through the configured model |
| `GET` `POST` | `/v1/settings` | Viewer settings; the API key is write-only |
| `GET` `POST` | `/v1/jobs` | Agent jobs; `{task: ingest\|lint\|cross-link\|synthesize\|digest}` starts one |
| `POST` | `/v1/git/sync` | Commit and push the vault (`obsidian-wiki sync`) |
| `GET` | `/v1/oauth/clients` | Apps signed in over OAuth, with live grant counts (write key) |
| `DELETE` | `/v1/oauth/clients/{client_id}` | Revoke an app's tokens and registration (write key) |

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
billing; rate limiting is per client address, not per person. To serve several people, run a container per vault and put a reverse proxy
in front. Terminate TLS at that proxy — the container speaks plain HTTP, and the API key is only as
private as the connection carrying it.
