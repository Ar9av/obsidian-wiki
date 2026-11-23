"""HTTP + MCP front end for a vault, so remote agents can use it as memory.

Single tenant: one process, one vault at a time, one API key (plus an optional
read-only one). The memory API does no LLM work: search, packing and frontmatter
parsing all delegate to the existing `graphrag` / `context_pack` modules, and the
caller's agent does the thinking. The viewer's Ask and Actions pages are the
exception; see `ui_tools`.

Needs the optional extra: ``pip install 'obsidian-wiki[server]'``.
Run it with ``obsidian-wiki serve`` or ``python -m obsidian_wiki.server``.
"""

from __future__ import annotations

import difflib
import hmac
import json
import os
import re
import sys
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from obsidian_wiki import clock
from obsidian_wiki.cache import _iter_entries
from obsidian_wiki.context_pack import ContextError, build_context_pack
from obsidian_wiki.graphrag import query as graph_query
from obsidian_wiki.staging import StagingError, list_staged, resolve_in_vault
from obsidian_wiki.lint import lint_vault
from obsidian_wiki import sync as vault_sync
from obsidian_wiki.sync import _git
from obsidian_wiki.vault import iter_md, iter_md_under, okignore_patterns, okignored

VAULT = Path(os.environ.get("OBSIDIAN_VAULT_PATH", "/vault")).expanduser()
API_KEY = os.environ.get("WIKI_API_KEY", "")
# Optional second key that can search and read but never write. Set it alone for
# a read-only deployment; hand it to agents that should consult the vault, not edit it.
READ_KEY = os.environ.get("WIKI_READ_KEY", "")
ANONYMOUS = os.environ.get("WIKI_ALLOW_ANONYMOUS") == "1"

if not API_KEY and not READ_KEY and not ANONYMOUS:
    raise RuntimeError(
        "refusing to start without WIKI_API_KEY (or WIKI_READ_KEY for a read-only server). "
        "Set one, or set WIKI_ALLOW_ANONYMOUS=1 for local development."
    )
if API_KEY and API_KEY == READ_KEY:
    raise RuntimeError("WIKI_READ_KEY must differ from WIKI_API_KEY")

# Optional OAuth 2.1 for MCP clients that sign in rather than send a header.
# The issuer must be the URL clients reach, so it can't be guessed from a request.
OAUTH = os.environ.get("WIKI_OAUTH") == "1"
PUBLIC_URL = os.environ.get("WIKI_PUBLIC_URL", "").strip().rstrip("/")
if OAUTH and not PUBLIC_URL:
    raise RuntimeError("WIKI_OAUTH=1 needs WIKI_PUBLIC_URL, the https:// address clients use")
if OAUTH and ANONYMOUS:
    raise RuntimeError("WIKI_OAUTH=1 signs in with WIKI_API_KEY or WIKI_READ_KEY; it can't run anonymous")

# Optional two-way git sync, so the container's vault and the owner's laptop copy
# stay one vault. Off unless an interval is set.
GIT_REMOTE = os.environ.get("WIKI_GIT_REMOTE", "").strip()
GIT_SYNC_INTERVAL = int(os.environ.get("WIKI_GIT_SYNC_INTERVAL", "0") or 0)

# Held by every page write and by the working-tree half of a git sync, so a
# rebase never lands on top of a half-written page. Memory files have their own
# file lock (memory.memory_lock); sync takes that one too.
_VAULT_WRITE_LOCK = threading.Lock()


# --- vault operations -------------------------------------------------------
# Every route and every MCP tool goes through these four functions, so the
# path check below is the single trust boundary for the whole service.

def _resolve(rel: str) -> Path:
    """Resolve a caller-supplied path inside the vault, or refuse."""
    try:
        return resolve_in_vault(VAULT, rel)
    except StagingError as exc:
        raise HTTPException(400, str(exc)) from exc


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
    with _VAULT_WRITE_LOCK:
        return _write_page_locked(rel, target, title, category, content,
                                  tags=tags, sources=sources, summary=summary, upsert=upsert)


def _write_page_locked(rel, target, title, category, content, *, tags, sources, summary, upsert):
    if target.exists() and not upsert:
        raise HTTPException(409, f"page already exists: {rel}")
    today = clock.today(clock.wiki_timezone(VAULT))
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
    # Through the shared writer, so an API write is locked and parseable like
    # every other one. Previously this appended its own ad-hoc format.
    from obsidian_wiki import memory as mem

    mem.append_log(VAULT, "API_WRITE", {"page": rel, "title": title})
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

oauth_provider = None
if OAUTH:
    from obsidian_wiki.oauth import WikiOAuthProvider

    # Late-bound: _key_access is defined just below.
    oauth_provider = WikiOAuthProvider(VAULT, PUBLIC_URL, lambda secret: _key_access(secret))

def _key_access(secret: str) -> str | None:
    """"write" or "read" for one of the static keys, else None."""
    token = secret.encode()
    # An unset key must never match: compare_digest(b"", b"") is True.
    if API_KEY and hmac.compare_digest(token, API_KEY.encode()):
        return "write"
    if READ_KEY and hmac.compare_digest(token, READ_KEY.encode()):
        return "read"
    return None


def _access(header: str) -> str | None:
    """"write", "read", or None for an Authorization header."""
    if ANONYMOUS:
        return "write"
    token = header[7:] if header.lower().startswith("bearer ") else ""
    access = _key_access(token)
    if access is None and token and oauth_provider is not None:
        access = oauth_provider.access_for(token)
    return access


def _key_ok(header: str) -> bool:
    return _access(header) is not None


def require_key(request: Request) -> None:
    if not _key_ok(request.headers.get("authorization", "")):
        raise HTTPException(401, "missing or invalid API key")


def require_write_key(request: Request) -> None:
    access = _access(request.headers.get("authorization", ""))
    if access is None:
        raise HTTPException(401, "missing or invalid API key")
    if access != "write":
        raise HTTPException(403, "this key is read-only")


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


class ProfileWrite(BaseModel):
    action: str = "set"
    key: str = ""
    value: str = ""
    confidence: float = 0.6
    source: str = "agent"
    until: str = ""
    user_id: str = ""


class TodoWrite(BaseModel):
    action: str = "add"
    text: str = ""
    todo_id: str = ""
    origin: str = ""
    user_id: str = ""


class SyncRequest(BaseModel):
    verb: str = "API_WRITE"
    takeaways: str = ""
    fields: dict[str, str] | None = None


def _scope(user_id: str) -> str:
    """Validate a caller-supplied user_id before it becomes a filename."""
    from obsidian_wiki import memory as mem

    try:
        return mem.check_scope(user_id)
    except mem.MemoryError_ as exc:
        raise HTTPException(400, str(exc))


def memory_recap(project: str = "", max_words: int = 350, min_confidence: float = 0.0,
                 user_id: str = "") -> dict[str, Any]:
    """The owner profile, open threads, and recent activity as one block."""
    from obsidian_wiki import memory as mem

    return {
        "recap": mem.build_recap(
            VAULT, max_words=max_words, min_confidence=min_confidence,
            project=project or None, scope=_scope(user_id),
        )
    }


def memory_profile(action: str = "list", key: str = "", value: str = "",
                   confidence: float = 0.6, source: str = "agent",
                   until: str = "", user_id: str = "") -> dict[str, Any]:
    """Read or update facts about a person. `user_id` scopes them.

    Pass `until` (YYYY-MM-DD) for a time-bound fact ("travelling until Friday")
    so it stops being injected once it is over.
    """
    from obsidian_wiki import memory as mem

    scope = _scope(user_id)
    if action == "list":
        return {"facts": [fact.__dict__ for fact in mem.load_profile(VAULT, scope)]}
    if action == "set":
        if not key or not value:
            raise HTTPException(400, "key and value are required for action='set'")
        return {"fact": mem.set_fact(
            VAULT, key, value, confidence=confidence, source=source, until=until, scope=scope
        ).__dict__}
    if action == "forget":
        return {"removed": mem.forget_fact(VAULT, key, scope=scope)}
    raise HTTPException(400, f"action must be list, set, or forget; got {action!r}")


def memory_todo(action: str = "list", text: str = "", todo_id: str = "",
                origin: str = "", include_closed: bool = False,
                user_id: str = "") -> dict[str, Any]:
    """Read or update threads carried between sessions. `user_id` scopes them."""
    from obsidian_wiki import memory as mem

    scope = _scope(user_id)
    if action == "list":
        todos = mem.load_todos(VAULT, scope)
        if not include_closed:
            todos = [todo for todo in todos if todo.status == "open"]
        return {"todos": [dict(todo.__dict__, stale=todo.is_stale()) for todo in todos]}
    if action == "add":
        if not text:
            raise HTTPException(400, "text is required for action='add'")
        return {"todo": mem.add_todo(VAULT, text, origin=origin, scope=scope).__dict__}
    if action in ("done", "drop"):
        if not todo_id:
            raise HTTPException(400, f"todo_id is required for action={action!r}")
        status = "done" if action == "done" else "dropped"
        return {"todo": mem.set_todo_status(VAULT, todo_id, status, scope=scope).__dict__}
    raise HTTPException(400, f"action must be list, add, done, or drop; got {action!r}")


def memory_sync(verb: str = "API_WRITE", takeaways: str = "", **fields: str) -> dict[str, Any]:
    """Reconcile the index and hot cache after writes, under one lock."""
    from obsidian_wiki import memory as mem

    try:
        with mem.memory_lock(VAULT):
            line = mem.append_log(VAULT, verb, fields, lock=False)
            index = mem.rebuild_index(VAULT, lock=False)
            hot = mem.rebuild_hot(VAULT, lock=False, takeaways=takeaways or None)
    except mem.MemoryError_ as exc:
        if exc.code == "unmigrated":
            raise HTTPException(409, str(exc))
        raise HTTPException(400, str(exc))
    return {
        "log_line": line,
        "index": {"total": index.total, "added": list(index.added)},
        "hot": {"words": hot.words},
    }


# Annotations let a client auto-approve the read tools and ask before the rest.
# Every tool touches only this vault, so none is open-world.
_READS = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_OVERWRITES = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)
_EDITS = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

#: (name, function, description, annotations, read-only?)
_TOOLS = (
    ("memory_search", search, "Search the wiki. Returns ranked pages with summaries.", _READS, True),
    ("memory_read", read_page, "Read one wiki page as markdown, by vault-relative path.", _READS, True),
    ("memory_write", write_page, "Write a wiki page. Use category '_raw' for a rough capture.", _OVERWRITES, False),
    ("memory_context_pack", context_pack, "Compile a token-bounded context pack on a topic.", _READS, True),
    ("memory_recap", memory_recap, "Owner profile, open threads, and recent activity — call at session start.", _READS, True),
    ("memory_profile", memory_profile, "Read or update durable facts about a person (list|set|forget); user_id scopes them.", _OVERWRITES, False),
    ("memory_todo", memory_todo, "Read or update threads carried between sessions (list|add|done|drop); user_id scopes them.", _EDITS, False),
    ("memory_sync", memory_sync, "Reconcile index.md and hot.md after writes, under one lock.", _EDITS, False),
)


def _build_mcp(read_only: bool) -> MCPServer:
    server = MCPServer("obsidian-wiki")
    for name, fn, description, annotations, reads in _TOOLS:
        if reads or not read_only:
            server.tool(name=name, description=description, annotations=annotations)(fn)
    return server


# Two servers rather than a per-call check: a read-only caller never even sees a
# write tool, so its agent doesn't plan around one it can't use.
mcp = _build_mcp(read_only=False)
mcp_read = _build_mcp(read_only=True)


# Must be built before `session_manager` exists. Mounted at /mcp below, so its
# own path is "/". Stateless: no server-side session state to lose on restart.
# `host` must match the bind address: left at its loopback default, mcp turns on
# DNS-rebinding protection and answers every LAN or container request with 421.
def _http_app(server: MCPServer):
    return server.streamable_http_app(
        streamable_http_path="/", stateless_http=True,
        host=os.environ.get("WIKI_HOST", "127.0.0.1"),
    )


_mcp_app = _http_app(mcp)
_mcp_read_app = _http_app(mcp_read)


def _keyed(write_app, read_app):
    """Route dependencies do not reach a mounted app, so /mcp checks the key itself."""
    async def app(scope, receive, send):
        target = write_app
        if scope["type"] == "http":
            header = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
            access = _access(header)
            if access is None:
                # RFC 9728: point an OAuth-capable client at the metadata to sign in.
                headers = {"WWW-Authenticate": f'Bearer resource_metadata="{_RESOURCE_METADATA}"'} if OAUTH else None
                await JSONResponse({"detail": "missing or invalid API key"}, 401, headers=headers)(scope, receive, send)
                return
            target = write_app if access == "write" else read_app
        await target(scope, receive, send)
    return app


# --- git sync ---------------------------------------------------------------

_SYNC_STATE: dict[str, Any] = {"enabled": False}
# One cycle at a time: the shutdown sync can overlap a loop tick, and two git
# processes in one checkout trip over .git/index.lock.
_SYNC_RUN_LOCK = threading.Lock()


@contextmanager
def _tree_lock():
    """Everything that writes the working tree: page writes and the memory writer."""
    from obsidian_wiki import memory as mem

    with _VAULT_WRITE_LOCK, mem.memory_lock(VAULT, timeout=60):
        yield


def sync_once() -> dict[str, Any]:
    with _SYNC_RUN_LOCK:
        try:
            code, message = vault_sync.pull_and_push(VAULT, lock=_tree_lock)
        except Exception as exc:  # a lock timeout or git crash must not take the server down
            code, message = 1, vault_sync.redact_remote(f"wiki-sync: {exc}")
        _SYNC_STATE.update(
            ok=code == 0, message=message, last_run=datetime.now(timezone.utc).isoformat(),
        )
    print(message, file=sys.stderr, flush=True)
    return dict(_SYNC_STATE)


def _sync_loop(stop: threading.Event) -> None:
    while not stop.wait(GIT_SYNC_INTERVAL):
        sync_once()


def _start_git_sync() -> threading.Event | None:
    """Clone or adopt the remote, sync once, then keep syncing in the background."""
    if GIT_REMOTE:
        print(vault_sync.bootstrap_remote(VAULT, GIT_REMOTE), file=sys.stderr, flush=True)
    if GIT_SYNC_INTERVAL <= 0:
        return None
    _SYNC_STATE.update(enabled=True, interval=GIT_SYNC_INTERVAL)
    sync_once()
    stop = threading.Event()
    threading.Thread(target=_sync_loop, args=(stop,), name="wiki-git-sync", daemon=True).start()
    return stop


@asynccontextmanager
async def lifespan(_: FastAPI):
    import anyio

    stop = await anyio.to_thread.run_sync(_start_git_sync)
    # Without running the session managers here, /mcp accepts the first request
    # and then hangs.
    try:
        async with mcp.session_manager.run(), mcp_read.session_manager.run():
            yield
    finally:
        if stop is not None:
            stop.set()
            # One last push, so a write made just before shutdown isn't stranded.
            await anyio.to_thread.run_sync(sync_once)


app = FastAPI(title="obsidian-wiki memory", lifespan=lifespan)
app.mount("/mcp", _keyed(_mcp_app, _mcp_read_app))

_RESOURCE_METADATA = f"{PUBLIC_URL}/.well-known/oauth-protected-resource/mcp/"
if OAUTH:
    from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
    from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
    from pydantic import AnyHttpUrl

    from obsidian_wiki.oauth import CONSENT_PATH, SCOPES

    from mcp.server.auth.settings import AuthSettings

    # Through AuthSettings, not AnyHttpUrl(): pydantic appends "/" to a bare
    # host, and RFC 8414 compares the issuer as an exact string.
    _issuer = AuthSettings(issuer_url=PUBLIC_URL, resource_server_url=None).issuer_url
    app.router.routes.extend(create_auth_routes(
        oauth_provider, issuer_url=_issuer,
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=SCOPES, default_scopes=SCOPES,
        ),
        revocation_options=RevocationOptions(enabled=True),
    ))
    # Clients derive the metadata path from the URL they were given, with or
    # without the trailing slash, or fall back to the bare well-known path. Each
    # document names the resource it was fetched for (RFC 9728 §3.3).
    for resource in (f"{PUBLIC_URL}/mcp/", f"{PUBLIC_URL}/mcp", PUBLIC_URL):
        app.router.routes.extend(create_protected_resource_routes(
            resource_url=AnyHttpUrl(resource), authorization_servers=[_issuer],
            scopes_supported=SCOPES, resource_name="obsidian-wiki",
        ))
    app.add_api_route(CONSENT_PATH, oauth_provider.consent, methods=["GET", "POST"], include_in_schema=False)


# Anonymous mode trusts loopback, but any web page can reach loopback through DNS
# rebinding: attacker.example re-resolves to 127.0.0.1 and its script becomes
# same-origin with the vault API. The Host header still says attacker.example, so
# refuse anything but a loopback name. Keyed servers don't need this: a rebound
# page has no key.
_LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "::1", "[::1]"]
if ANONYMOUS and os.environ.get("WIKI_HOST", "127.0.0.1") in _LOOPBACK_HOSTS:
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_LOOPBACK_HOSTS)

# Outermost: rate limiting and the failed-auth lockout see every request,
# including /mcp and the OAuth endpoints.
from obsidian_wiki.guard import Guard  # noqa: E402

app.add_middleware(
    Guard,
    rate_limit=int(os.environ.get("WIKI_RATE_LIMIT", "600") or 0),
    lockout_limit=int(os.environ.get("WIKI_AUTH_LOCKOUT", "10") or 0),
    lockout_seconds=int(os.environ.get("WIKI_AUTH_LOCKOUT_SECONDS", "300") or 300),
)


@app.get("/health")
def health() -> dict[str, Any]:
    body: dict[str, Any] = {"ok": VAULT.is_dir(), "vault": str(VAULT)}
    if _SYNC_STATE.get("enabled"):
        # Unauthenticated, so a yes/no only — the message can name the remote.
        body["git_sync_ok"] = _SYNC_STATE.get("ok", True)
    return body


@app.get("/v1/search", dependencies=[Depends(require_key)])
def http_search(q: str, limit: int = 8) -> dict[str, Any]:
    return search(q, limit)


@app.get("/v1/pages/{path:path}", dependencies=[Depends(require_key)])
def http_read(path: str) -> dict[str, Any]:
    return read_page(path)


@app.post("/v1/pages", dependencies=[Depends(require_write_key)])
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


# --- operations console -----------------------------------------------------
# Read-only. The vault stays the source of truth: every number below is derived
# from the files on disk, from `.manifest.json`, or from git — no state of our
# own. Reuses lint_vault / run_doctor rather than shelling out to the CLI.

# `.manifest.json` is written by several skills and is not one shape: wiki-ingest
# keys sources under "sources", wiki-update under "projects", wiki-research under
# "research_sessions", and each names its page list differently. Read every known
# shape — a real vault usually holds more than one.
_MANIFEST_CONTAINERS = ("sources", "projects", "research_sessions")
_MANIFEST_PAGE_KEYS = ("pages_produced", "pages_created", "pages_in_vault")


def _count_md(rel: str) -> int:
    return len(iter_md_under(VAULT, VAULT / rel))


def _dirty_lines(porcelain_z: str) -> list[str]:
    """Porcelain status lines, minus any path excluded by `.okignore`.

    Takes `-z` output because plain porcelain C-quotes a path holding a space or
    non-ASCII character, which no pattern would match.
    """
    patterns = okignore_patterns(VAULT)

    def hidden(path: str) -> bool:
        return okignored(Path(path), patterns)

    def shown(path: str) -> str:
        return "(ignored)" if hidden(path) else path

    lines = []
    fields = iter(porcelain_z.split("\0"))
    for field in fields:
        if not field:
            continue
        code, path = field[:2], field[3:]
        # -z puts a rename's or copy's source in the next field, with no arrow.
        source = next(fields) if "R" in code or "C" in code else None
        if source is None:
            if not hidden(path):
                lines.append(field)
        elif not (hidden(source) and hidden(path)):
            # Half public is still a real change, so report it without the hidden side.
            lines.append(f"{code} {shown(source)} -> {shown(path)}")
    return lines


def _git_status() -> dict[str, Any]:
    if not (VAULT / ".git").is_dir():
        return {"repo": False}
    # Every untracked file, not git's collapsed `?? dir/`: that names a directory
    # the filter can't see into, even when all it holds is ignored.
    porcelain = _git(VAULT, "status", "--porcelain", "-z", "--untracked-files=all")
    branch = _git(VAULT, "rev-parse", "--abbrev-ref", "HEAD")
    log = _git(VAULT, "log", "-5", "--pretty=%h %s")
    dirty = _dirty_lines(porcelain.stdout)
    return {
        "repo": True,
        "sync": dict(_SYNC_STATE),
        "branch": branch.stdout.strip(),
        "dirty": dirty[:50],
        "dirty_count": len(dirty),
        "recent": log.stdout.splitlines(),
    }


def status() -> dict[str, Any]:
    """Operational snapshot: page counts, staging/raw depth, source freshness."""
    pages = [p for p in iter_md(VAULT) if not p.relative_to(VAULT).parts[0].startswith("_")]
    categories: dict[str, int] = {}
    for page in pages:
        parts = page.relative_to(VAULT).parts
        # index.md / log.md / hot.md sit at the root and belong to no category.
        top = parts[0] if len(parts) > 1 else "(root)"
        categories[top] = categories.get(top, 0) + 1
    recent = sorted(pages, key=lambda p: p.stat().st_mtime, reverse=True)[:20]

    manifest_path = VAULT / ".manifest.json"
    sources: list[dict[str, Any]] = []
    last_ingest = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(500, f"unreadable .manifest.json: {exc}") from exc
        last_ingest = manifest.get("last_ingest")
        for container in _MANIFEST_CONTAINERS:
            for key, entry in _iter_entries(manifest.get(container)):
                produced = [
                    rel for field in _MANIFEST_PAGE_KEYS for rel in entry.get(field, [])
                ]
                sources.append({
                    "source_id": entry.get("source_id") or entry.get("session_id") or key or "",
                    "container": container,
                    "type": entry.get("type") or entry.get("skill") or "",
                    "ingested_at": (
                        entry.get("ingested_at")
                        or entry.get("last_synced")
                        or entry.get("completed")
                        or ""
                    ),
                    "pages_produced": len(produced),
                    # A produced page that no longer exists means the source needs re-ingesting.
                    "missing_pages": [rel for rel in produced if not (VAULT / rel).is_file()],
                })

    return {
        "vault": str(VAULT),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages": len(pages),
        "categories": dict(sorted(categories.items())),
        "raw_count": _count_md("_raw"),
        # Every top-level file the next ingest will see, not just markdown: a dropped PDF counts.
        "raw_files": len(ui_tools.list_inbox(VAULT)),
        "staging_count": _count_md("_staging"),
        "last_ingest": last_ingest,
        "sources": sources,
        "recent_pages": [
            {
                "path": p.relative_to(VAULT).as_posix(),
                "modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
            }
            for p in recent
        ],
        "git": _git_status(),
    }


_LINT_TTL = 60.0  # seconds a cached lint result may be reused while no page has changed
_lint_cache: dict[str, Any] = {}


def lint_summary() -> dict[str, Any]:
    """lint_vault, reused while the vault is unchanged.

    The Overview and Actions pages ask for this on every visit, and a full lint parses
    every page. The key is the vault plus each page's mtime, with a short TTL for what
    the page walk can't see (`.manifest.json`, `_raw/`).
    """
    pages = iter_md(VAULT)
    sig = (str(VAULT), len(pages), max((p.stat().st_mtime_ns for p in pages), default=0))
    if _lint_cache.get("sig") != sig or time.monotonic() - _lint_cache["at"] > _LINT_TTL:
        _lint_cache.update(sig=sig, at=time.monotonic(), lint=lint_vault(VAULT))
    return _lint_cache["lint"]


def vault_health() -> dict[str, Any]:
    """Doctor + lint, straight from the same functions the CLI calls."""
    from obsidian_wiki.cli import run_doctor

    return {"doctor": run_doctor(vault_override=str(VAULT)), "lint": lint_vault(VAULT)}


def staging() -> dict[str, Any]:
    """Staged pages, each with a unified diff against the live page (if any).

    difflib emits plain text and the UI inserts it as textContent, so
    agent-authored markdown never reaches the browser as HTML.
    """
    def lines(path: Path) -> list[str]:
        if not path.is_file():
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

    items = []
    for entry in list_staged(VAULT):
        item = entry.as_dict()
        item["diff"] = "".join(
            difflib.unified_diff(
                lines(VAULT / entry.live_path),
                lines(VAULT / entry.staged_path),
                "live",
                "staged",
            )
        )
        items.append(item)
    return {"count": len(items), "items": items}


def graph() -> dict[str, Any]:
    """The wikilink graph the viewer draws: one node per page, deduped edges.

    Same page set and link resolution as `wiki-status` insights, so the picture
    matches the hub/bridge numbers.
    """
    from obsidian_wiki.graph_analysis import iter_pages, parse_vault_graph
    from obsidian_wiki.link_provenance import link_provenance
    from obsidian_wiki.links import PageIndex
    from obsidian_wiki.lint import _parse_frontmatter_values
    from obsidian_wiki.vault import split_frontmatter

    def title_of(rel: str) -> str:
        # ponytail: re-reads each page parse_vault_graph already read; fold titles
        # into that walk if /v1/graph ever shows up as slow on a big vault.
        try:
            text = (VAULT / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return _parse_frontmatter_values(split_frontmatter(text)[0]).get("title", "")

    outgoing, tags = parse_vault_graph(VAULT)
    rels = [p.relative_to(VAULT).as_posix() for p in iter_pages(VAULT)]
    index = PageIndex(rels)
    # setdefault: two files sharing one key share one id; the first wins, as in PageIndex.
    paths: dict[str, str] = {}
    for rel in rels:
        paths.setdefault(index.id_for(rel), rel)
    nodes = []
    for node_id in outgoing:
        path = paths.get(node_id, "")
        nodes.append({
            "id": node_id,
            "path": path,
            "title": title_of(path) if path else "",
            "category": path.split("/", 1)[0] if "/" in path else "(root)",
            "tags": tags.get(node_id, []),
        })
    edges = sorted({(src, dst) for src, dsts in outgoing.items() for dst in dsts})
    # Links resting on an ^[inferred]/^[ambiguous] claim; every other edge is extracted.
    weak = [[r["from"], r["to"], r["state"]] for r in link_provenance(VAULT) if r["state"] != "extracted"]
    return {"nodes": nodes, "edges": [list(e) for e in edges], "weak": weak}


# The viewer is a prebuilt React bundle (source in ui/, `npm run build` writes here).
_WEBUI = Path(__file__).with_name("webui")


@app.get("/v1/memory/recap", dependencies=[Depends(require_key)])
def http_recap(project: str = "", max_words: int = 350, min_confidence: float = 0.0,
               user_id: str = "") -> dict[str, Any]:
    return memory_recap(project=project, max_words=max_words,
                        min_confidence=min_confidence, user_id=user_id)


@app.get("/v1/memory/profile", dependencies=[Depends(require_key)])
def http_profile_list(user_id: str = "") -> dict[str, Any]:
    return memory_profile("list", user_id=user_id)


@app.post("/v1/memory/profile", dependencies=[Depends(require_write_key)])
def http_profile_set(body: ProfileWrite) -> dict[str, Any]:
    return memory_profile(
        body.action, key=body.key, value=body.value,
        confidence=body.confidence, source=body.source, until=body.until, user_id=body.user_id,
    )


@app.get("/v1/memory/todos", dependencies=[Depends(require_key)])
def http_todo_list(include_closed: bool = False, user_id: str = "") -> dict[str, Any]:
    return memory_todo("list", include_closed=include_closed, user_id=user_id)


@app.post("/v1/memory/todos", dependencies=[Depends(require_write_key)])
def http_todo_write(body: TodoWrite) -> dict[str, Any]:
    return memory_todo(body.action, text=body.text, todo_id=body.todo_id,
                       origin=body.origin, user_id=body.user_id)


@app.post("/v1/memory/sync", dependencies=[Depends(require_write_key)])
def http_memory_sync(body: SyncRequest) -> dict[str, Any]:
    return memory_sync(verb=body.verb, takeaways=body.takeaways, **(body.fields or {}))


@app.get("/ui", response_class=HTMLResponse)
def http_ui() -> str:
    """The viewer shell. Carries no vault data — every number is fetched with the key."""
    return (_WEBUI / "index.html").read_text(encoding="utf-8")


# Hashed JS/CSS chunks only; the shell above is the one HTML route.
app.mount("/ui/assets", StaticFiles(directory=_WEBUI / "assets", check_dir=False), name="webui-assets")


@app.get("/", include_in_schema=False)
def http_root() -> RedirectResponse:
    return RedirectResponse("/ui")


@app.get("/v1/graph", dependencies=[Depends(require_key)])
def http_graph() -> dict[str, Any]:
    return graph()


@app.get("/v1/connect", dependencies=[Depends(require_key)])
async def http_connect(request: Request) -> dict[str, Any]:
    """What an agent needs to plug into this vault, for the viewer's Connect page.

    `python` is this process's interpreter, which already has the server extra, so
    `python -m obsidian_wiki mcp` works even where `obsidian-wiki` isn't on PATH
    (GUI apps) or resolves to an install without the extra. Behind the key: it
    reveals local paths. Lists the tools the caller's key will actually see.
    """
    access = _access(request.headers.get("authorization", ""))
    server = mcp if access == "write" else mcp_read
    return {
        "python": sys.executable,
        "vault": str(VAULT),
        "key_required": not ANONYMOUS,
        "access": access,
        "oauth": OAUTH,
        "public_url": PUBLIC_URL,
        "tools": [{"name": t.name, "description": t.description or ""} for t in await server.list_tools()],
    }


@app.get("/v1/status", dependencies=[Depends(require_key)])
def http_status() -> dict[str, Any]:
    return status()


@app.get("/v1/lint", dependencies=[Depends(require_key)])
def http_lint() -> dict[str, Any]:
    """Cached lint for the viewer's Next actions; /v1/health is the fresh, full report."""
    return lint_summary()


@app.get("/v1/health", dependencies=[Depends(require_key)])
def http_vault_health() -> dict[str, Any]:
    return vault_health()


@app.get("/v1/staging", dependencies=[Depends(require_key)])
def http_staging() -> dict[str, Any]:
    return staging()


# --- viewer tools: vault switching, inbox, settings, ask, agent jobs ------------
# The logic lives in ui_tools; these routes only translate its errors.

from obsidian_wiki import ui_tools  # noqa: E402

STARTUP_VAULT = VAULT


def _ui(fn, *args):
    try:
        return fn(*args)
    except ui_tools.UiError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


class VaultSwitch(BaseModel):
    path: str


class InboxItem(BaseModel):
    kind: str = "text"
    title: str = ""
    text: str = ""
    url: str = ""
    filename: str = ""
    data_b64: str = ""


class InboxRemove(BaseModel):
    name: str


class SettingsPatch(BaseModel):
    provider: str | None = None
    model: str | None = None
    anthropic_api_key: str | None = None
    litellm_api_base: str | None = None
    litellm_api_key: str | None = None
    web: bool | None = None


class AskRequest(BaseModel):
    question: str
    web: bool | None = None


class JobRequest(BaseModel):
    task: str


@app.get("/v1/vaults", dependencies=[Depends(require_key)])
def http_vaults() -> dict[str, Any]:
    return {"current": str(VAULT), "vaults": ui_tools.known_vaults(STARTUP_VAULT)}


@app.post("/v1/vaults", dependencies=[Depends(require_write_key)])
def http_switch_vault(body: VaultSwitch) -> dict[str, Any]:
    """Point this process at another configured vault. MCP clients follow too."""
    global VAULT
    VAULT = _ui(ui_tools.pick_vault, STARTUP_VAULT, body.path)
    return {"current": str(VAULT)}


@app.get("/v1/inbox", dependencies=[Depends(require_key)])
def http_inbox() -> dict[str, Any]:
    return {"items": ui_tools.list_inbox(VAULT)}


@app.post("/v1/inbox", dependencies=[Depends(require_write_key)])
def http_inbox_add(body: InboxItem) -> dict[str, Any]:
    return _ui(ui_tools.add_to_inbox, VAULT, body.model_dump())


@app.post("/v1/inbox/remove", dependencies=[Depends(require_write_key)])
def http_inbox_remove(body: InboxRemove) -> dict[str, Any]:
    _ui(ui_tools.remove_from_inbox, VAULT, body.name)
    return {"removed": body.name}


@app.get("/v1/insights", dependencies=[Depends(require_key)])
def http_insights() -> dict[str, Any]:
    from obsidian_wiki.graph_analysis import analyse_vault

    return analyse_vault(VAULT, top_n=12)


@app.get("/v1/settings", dependencies=[Depends(require_key)])
def http_settings() -> dict[str, Any]:
    return ui_tools.public_settings()


@app.post("/v1/settings", dependencies=[Depends(require_write_key)])
def http_settings_save(body: SettingsPatch) -> dict[str, Any]:
    return _ui(ui_tools.save_settings, body.model_dump(exclude_none=True))


@app.post("/v1/ask", dependencies=[Depends(require_write_key)])
def http_ask(body: AskRequest) -> dict[str, Any]:
    return _ui(ui_tools.ask, VAULT, body.question, body.web)


@app.get("/v1/jobs", dependencies=[Depends(require_key)])
def http_jobs() -> dict[str, Any]:
    return {
        "jobs": ui_tools.list_jobs(),
        "tasks": [{"task": k, "label": v[0], "prompt": v[1]} for k, v in ui_tools.AGENT_TASKS.items()],
        "agent": bool(ui_tools.shutil.which("claude")),
    }


@app.post("/v1/jobs", dependencies=[Depends(require_write_key)])
def http_job_start(body: JobRequest) -> dict[str, Any]:
    return _ui(ui_tools.start_job, VAULT, body.task)


@app.post("/v1/git/sync", dependencies=[Depends(require_write_key)])
def http_git_sync() -> dict[str, Any]:
    from obsidian_wiki.sync import run_sync

    code, message = run_sync(VAULT)
    if code:
        raise HTTPException(409, message)
    return {"message": message}


@app.get("/v1/oauth/clients", dependencies=[Depends(require_write_key)])
def http_oauth_clients() -> dict[str, Any]:
    """Apps that signed in over OAuth, so the owner can see and revoke them."""
    if oauth_provider is None:
        return {"enabled": False, "clients": []}
    return {"enabled": True, "clients": oauth_provider.clients()}


@app.delete("/v1/oauth/clients/{client_id}", dependencies=[Depends(require_write_key)])
def http_oauth_forget(client_id: str) -> dict[str, Any]:
    if oauth_provider is None or not oauth_provider.forget_client(client_id):
        raise HTTPException(404, f"no such OAuth client: {client_id}")
    return {"revoked": client_id}


def run(host: str | None = None, port: int | None = None) -> None:
    """Serve `app` with uvicorn — shared by `obsidian-wiki serve` and `python -m`."""
    import uvicorn

    # Loopback by default: /ui is a browser console over the whole vault, and the
    # bare `python -m obsidian_wiki.server` case is a laptop or a dev box, not a
    # deliberate exposure. Containers need every interface, so the Dockerfile sets
    # WIKI_HOST=0.0.0.0 explicitly.
    host = host or os.environ.get("WIKI_HOST", "127.0.0.1")
    # PORT is what Render, Railway, Heroku and friends assign.
    port = port or int(os.environ.get("WIKI_PORT") or os.environ.get("PORT") or 8080)
    kwargs: dict[str, Any] = {}
    # Behind a proxy every client is the proxy, which would make the per-client
    # rate limit and lockout global. Trusted peers' X-Forwarded-For names the
    # real client instead. Unset keeps uvicorn's default (127.0.0.1 only).
    if os.environ.get("WIKI_TRUSTED_PROXIES"):
        kwargs["forwarded_allow_ips"] = os.environ["WIKI_TRUSTED_PROXIES"]
    uvicorn.run(app, host=host, port=port, **kwargs)


def main() -> None:
    run()


if __name__ == "__main__":
    main()
