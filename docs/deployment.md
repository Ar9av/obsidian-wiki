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

## Configuration

| Variable | What it does | Default |
|---|---|---|
| `OBSIDIAN_VAULT_PATH` | Vault the service serves | `/vault` |
| `WIKI_API_KEY` | Bearer token for every `/v1/*` and `/mcp` request | *(none — required)* |
| `WIKI_ALLOW_ANONYMOUS` | `1` disables auth entirely. Local development only | *(unset)* |
| `WIKI_PORT` | Port to listen on | `8080` |

The process **refuses to start** without `WIKI_API_KEY` unless `WIKI_ALLOW_ANONYMOUS=1`. There is no
default key.

## Connect an agent (MCP)

```bash
claude mcp add --transport http wiki-memory http://localhost:8080/mcp/ \
  --header "Authorization: Bearer $WIKI_API_KEY"
```

Four tools: `memory_search`, `memory_read`, `memory_write`, `memory_context_pack`.

## REST

Every route below `/v1` needs `Authorization: Bearer <key>`. `/health` does not.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Liveness; also reports whether the vault directory exists |
| `GET` | `/v1/search?q=&limit=` | Ranked pages with summaries, from the same GraphRAG index the `wiki-query` skill uses |
| `GET` | `/v1/pages/{path}` | One page as markdown, by vault-relative path |
| `POST` | `/v1/pages` | `{title, category, content, tags, sources, summary, upsert}` |
| `POST` | `/v1/context-pack` | `{topic, budget, recent, public_only, metadata_only}` |

```bash
curl -X POST localhost:8080/v1/pages -H "Authorization: Bearer $WIKI_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"title":"Merkle Tree","category":"concepts","summary":"Hash tree for cheap diffing.","content":"Each node hashes its children."}'
# -> {"path":"concepts/merkle-tree.md", ...}
```

Writes land at `<category>/<slug-of-title>.md` with the six required frontmatter keys plus `summary`,
and append a line to `log.md`. `created:` is preserved across updates. Use `category: "_raw"` for a
rough capture you intend to promote with `wiki-ingest` later — the same role `_raw/` plays for the
`wiki-capture` skill.

`POST /v1/pages` writes exactly what you send. It does not distil, dedupe, or cross-link — those are
the agent's job, via the `wiki-capture` and `cross-linker` skills.

## Backups

The vault is a directory, so back it up like one:

```bash
docker run --rm -v wiki-data:/vault -v ~/.aws:/root/.aws:ro amazon/aws-cli \
  s3 sync /vault s3://your-bucket/vault
```

Or point the vault at a git remote and use `obsidian-wiki sync` — see
[Configuration](configuration.md).

## What this is not

Single-tenant: one container serves one vault behind one key. No per-user isolation, no quotas, no
rate limiting, no billing. To serve several people, run a container per vault and put a reverse proxy
in front. Terminate TLS at that proxy — the container speaks plain HTTP, and the API key is only as
private as the connection carrying it.
