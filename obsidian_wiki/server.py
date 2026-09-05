"""HTTP + MCP front end for a vault, so remote agents can use it as memory.

Single tenant: one process, one vault, one API key. The container does no LLM
work — search, packing and frontmatter parsing all delegate to the existing
`graphrag` / `context_pack` modules, and the caller's agent does the thinking.

Needs the optional extra: ``pip install 'obsidian-wiki[server]'``.
Run it with ``python -m obsidian_wiki.server``.
"""

from __future__ import annotations

import hmac
import os
import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from obsidian_wiki.context_pack import ContextError, build_context_pack
from obsidian_wiki.graphrag import query as graph_query

VAULT = Path(os.environ.get("OBSIDIAN_VAULT_PATH", "/vault")).expanduser()
API_KEY = os.environ.get("WIKI_API_KEY", "")
ANONYMOUS = os.environ.get("WIKI_ALLOW_ANONYMOUS") == "1"

if not API_KEY and not ANONYMOUS:
    raise RuntimeError(
        "refusing to start without WIKI_API_KEY. "
        "Set it, or set WIKI_ALLOW_ANONYMOUS=1 for local development."
    )


# --- vault operations -------------------------------------------------------
# Every route and every MCP tool goes through these four functions, so the
# path check below is the single trust boundary for the whole service.

def _resolve(rel: str) -> Path:
    """Resolve a caller-supplied path inside the vault, or refuse."""
    root = VAULT.resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(400, f"path escapes the vault: {rel}")
    return target


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "untitled"


def _category_slug(category: str) -> str:
    """Slugify a category, preserving a reserved leading underscore."""
    slug = _slug(category)
    return f"_{slug}" if category.lower().startswith("_") else slug


def search(q: str, limit: int = 8) -> dict[str, Any]:
    return graph_query(VAULT, q, top_n=limit)


def read_page(path: str) -> dict[str, Any]:
    target = _resolve(path)
    if not target.is_file():
        raise HTTPException(404, f"no such page: {path}")
    return {"path": path, "markdown": target.read_text(encoding="utf-8")}


def _folded(key: str, value: str) -> str:
    """Emit a free-text scalar as a YAML folded block (`key: >-`).

    A bare scalar containing ": ", "#", or a quote breaks YAML parsing, and
    Obsidian then reports "Invalid properties". A folded block needs no
    escaping, so it stays readable on disk for any value — including
    non-ASCII — and the vault's own frontmatter readers already understand it.
    """
    return f"{key}: >-\n  " + " ".join(str(value).split())


def write_page(
    title: str,
    category: str,
    content: str,
    *,
    tags: list[str] | None = None,
    sources: list[str] | None = None,
    summary: str = "",
    upsert: bool = True,
) -> dict[str, Any]:
    rel = f"{_category_slug(category)}/{_slug(title)}.md"
    target = _resolve(rel)
    if target.exists() and not upsert:
        raise HTTPException(409, f"page already exists: {rel}")
    today = date.today().isoformat()
    created = today
    if target.exists():
        # Preserve the original created: date across updates.
        match = re.search(r"^created:\s*(\S+)", target.read_text(encoding="utf-8"), re.MULTILINE)
        created = match.group(1) if match else today
    front = "\n".join(
        [
            "---",
            _folded("title", title),
            f"category: {_category_slug(category)}",
            "tags: [" + ", ".join(tags or []) + "]",
            "sources: [" + ", ".join(sources or []) + "]",
            _folded("summary", summary) if summary else "summary:",
            f"created: {created}",
            f"updated: {today}",
            "---",
            "",
            "",
        ]
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(front + content.rstrip() + "\n", encoding="utf-8")
    log = VAULT / "log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"- {today} — wrote [[{title}]] via API ({rel})\n")
    return {"path": rel, "created": created, "updated": today}


def context_pack(
    topic: str,
    *,
    budget: int = 8000,
    recent: bool = False,
    public_only: bool = False,
    metadata_only: bool = False,
) -> dict[str, Any]:
    try:
        return build_context_pack(
            VAULT, topic, budget=budget, recent=recent,
            public_only=public_only, metadata_only=metadata_only,
        )
    except ContextError as exc:
        raise HTTPException(400, str(exc)) from exc


# --- HTTP -------------------------------------------------------------------

def require_key(request: Request) -> None:
    if ANONYMOUS:
        return
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(token, API_KEY):
        raise HTTPException(401, "missing or invalid API key")


class PageWrite(BaseModel):
    title: str
    category: str = "concepts"
    content: str
    tags: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    summary: str = ""
    upsert: bool = True


class PackRequest(BaseModel):
    topic: str = ""
    budget: int = 8000
    recent: bool = False
    public_only: bool = False
    metadata_only: bool = False


mcp = MCPServer("obsidian-wiki")
mcp.tool(name="memory_search", description="Search the wiki. Returns ranked pages with summaries.")(search)
mcp.tool(name="memory_read", description="Read one wiki page as markdown, by vault-relative path.")(read_page)
mcp.tool(name="memory_write", description="Write a wiki page. Use category '_raw' for a rough capture.")(write_page)
mcp.tool(name="memory_context_pack", description="Compile a token-bounded context pack on a topic.")(context_pack)


# Must be built before `mcp.session_manager` exists. Mounted at /mcp below, so
# its own path is "/". Stateless: no server-side session state to lose on restart.
_mcp_app = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Without running the session manager here, /mcp accepts the first request
    # and then hangs.
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="obsidian-wiki memory", lifespan=lifespan)
app.mount("/mcp", _mcp_app)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": VAULT.is_dir(), "vault": str(VAULT)}


@app.get("/v1/search", dependencies=[Depends(require_key)])
def http_search(q: str, limit: int = 8) -> dict[str, Any]:
    return search(q, limit)


@app.get("/v1/pages/{path:path}", dependencies=[Depends(require_key)])
def http_read(path: str) -> dict[str, Any]:
    return read_page(path)


@app.post("/v1/pages", dependencies=[Depends(require_key)])
def http_write(body: PageWrite) -> dict[str, Any]:
    return write_page(
        body.title, body.category, body.content,
        tags=body.tags, sources=body.sources, summary=body.summary, upsert=body.upsert,
    )


@app.post("/v1/context-pack", dependencies=[Depends(require_key)])
def http_pack(body: PackRequest) -> dict[str, Any]:
    return context_pack(
        body.topic, budget=body.budget, recent=body.recent,
        public_only=body.public_only, metadata_only=body.metadata_only,
    )


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("WIKI_PORT", "8080")))


if __name__ == "__main__":
    main()
