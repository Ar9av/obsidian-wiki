"""OAuth 2.1 for the MCP endpoint, so clients can connect with a sign-in prompt.

Off unless ``WIKI_OAUTH=1``. A static bearer key still works alongside it;
OAuth is for clients where pasting a key is awkward or impossible (claude.ai
and ChatGPT connectors, Cursor, VS Code, Codex ``mcp login``).

Single tenant, so there is no user database. "Signing in" means proving you
hold a key: the consent page asks for ``WIKI_API_KEY`` (grants ``wiki:read``
and ``wiki:write``) or ``WIKI_READ_KEY`` (``wiki:read`` only). Clients register
themselves (RFC 7591 dynamic registration), use PKCE, and get a one-hour access
token plus a 30-day refresh token that rotates on every use.

The protocol plumbing — metadata, registration, PKCE, code and redirect checks
— is the MCP SDK's (`mcp.server.auth`). This module is the provider behind it:
storage, the consent page, and scope decisions.

Tokens are stored as SHA-256 digests in ``<vault>/.wiki-server/oauth.json``, so
the file grants nothing if it leaks. That directory carries its own
``.gitignore`` and is never committed by any git setup. Delete the file to
revoke every client at once.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

SCOPE_READ = "wiki:read"
SCOPE_WRITE = "wiki:write"
SCOPES = [SCOPE_READ, SCOPE_WRITE]

ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400
CODE_TTL = 300
PENDING_TTL = 600
CONSENT_PATH = "/oauth/consent"
STATE_DIR = ".wiki-server"
#: Marks a 401 that rejected a typed key, for the Guard (which strips it).
FAILED_HEADER = "x-wiki-auth-failed"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class OAuthStore:
    """Clients and hashed tokens in one JSON file, written atomically."""

    def __init__(self, vault: Path) -> None:
        self.dir = Path(vault) / STATE_DIR
        self.path = self.dir / "oauth.json"
        self._lock = threading.Lock()
        self.data: dict[str, dict[str, Any]] = {"clients": {}, "access": {}, "refresh": {}}
        if self.path.is_file():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            for key in self.data:
                self.data[key] = loaded.get(key, {})

    def save(self) -> None:
        with self._lock:
            now = time.time()
            for table in ("access", "refresh"):
                self.data[table] = {
                    k: v for k, v in self.data[table].items()
                    if not v.get("expires_at") or v["expires_at"] > now
                }
            self.dir.mkdir(parents=True, exist_ok=True)
            ignore = self.dir / ".gitignore"
            if not ignore.is_file():
                ignore.write_text("# obsidian-wiki server state: never commit\n*\n", encoding="utf-8")
            fd, tmp = tempfile.mkstemp(prefix=".oauth.", suffix=".tmp", dir=self.dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self.data, fh, indent=1)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise


class WikiOAuthProvider:
    """`OAuthAuthorizationServerProvider` for a single-owner vault."""

    def __init__(self, vault: Path, public_url: str, key_access: Callable[[str], Optional[str]]) -> None:
        self.store = OAuthStore(vault)
        self.public_url = public_url.rstrip("/")
        self.key_access = key_access
        # In memory on purpose: both live for minutes, and a restart just means
        # the user clicks "connect" again.
        self.pending: dict[str, dict[str, Any]] = {}
        self.codes: dict[str, AuthorizationCode] = {}
        self._resources = {self.public_url, f"{self.public_url}/mcp"}

    # --- clients -----------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        raw = self.store.data["clients"].get(client_id)
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        record = client_info.model_dump(mode="json", exclude_none=True)
        record["registered_at"] = int(time.time())
        self.store.data["clients"][client_info.client_id] = record
        self.store.save()

    # --- authorization -----------------------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource and params.resource.rstrip("/") not in self._resources:
            raise AuthorizeError("invalid_target", f"this server only issues tokens for {self.public_url}/mcp/")
        now = time.time()
        self.pending = {k: v for k, v in self.pending.items() if v["created"] > now - PENDING_TTL}
        request_id = secrets.token_urlsafe(24)
        self.pending[request_id] = {"client_id": client.client_id, "params": params, "created": now}
        return f"{self.public_url}{CONSENT_PATH}?request={request_id}"

    async def load_authorization_code(self, client, authorization_code: str) -> AuthorizationCode | None:
        return self.codes.get(authorization_code)

    async def exchange_authorization_code(self, client, authorization_code: AuthorizationCode) -> OAuthToken:
        # Single use: a replayed code is simply unknown.
        if self.codes.pop(authorization_code.code, None) is None:
            raise TokenError("invalid_grant", "authorization code already used")
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.resource)

    # --- tokens ------------------------------------------------------------

    def _issue(self, client_id: str, scopes: list[str], resource: str | None) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = int(time.time())
        a, r = _digest(access), _digest(refresh)
        self.store.data["access"][a] = {
            "client_id": client_id, "scopes": scopes, "expires_at": now + ACCESS_TTL,
            "resource": resource, "refresh": r,
        }
        self.store.data["refresh"][r] = {
            "client_id": client_id, "scopes": scopes, "expires_at": now + REFRESH_TTL,
            "resource": resource, "access": a,
        }
        self.store.save()
        return OAuthToken(
            access_token=access, expires_in=ACCESS_TTL, scope=" ".join(scopes), refresh_token=refresh,
        )

    async def load_refresh_token(self, client, refresh_token: str) -> RefreshToken | None:
        record = self.store.data["refresh"].get(_digest(refresh_token))
        if not record:
            return None
        return RefreshToken(
            token=refresh_token, client_id=record["client_id"], scopes=record["scopes"],
            expires_at=record["expires_at"], resource=record.get("resource"),
        )

    async def exchange_refresh_token(self, client, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        old = self.store.data["refresh"].pop(_digest(refresh_token.token), None)
        if old is None:
            raise TokenError("invalid_grant", "refresh token already used")
        self.store.data["access"].pop(old.get("access", ""), None)
        return self._issue(client.client_id, scopes, refresh_token.resource)

    def access_record(self, token: str) -> dict[str, Any] | None:
        record = self.store.data["access"].get(_digest(token))
        if not record or record["expires_at"] <= time.time():
            return None
        return record

    async def load_access_token(self, token: str) -> AccessToken | None:
        record = self.access_record(token)
        if record is None:
            return None
        return AccessToken(
            token=token, client_id=record["client_id"], scopes=record["scopes"],
            expires_at=record["expires_at"], resource=record.get("resource"),
        )

    def access_for(self, token: str) -> str | None:
        """"write", "read", or None — the same levels the static keys grant."""
        record = self.access_record(token)
        if record is None:
            return None
        return "write" if SCOPE_WRITE in record["scopes"] else "read"

    async def revoke_token(self, token) -> None:
        digest = _digest(token.token)
        access = self.store.data["access"].pop(digest, None)
        refresh = self.store.data["refresh"].pop(digest, None)
        if access:
            self.store.data["refresh"].pop(access.get("refresh", ""), None)
        if refresh:
            self.store.data["access"].pop(refresh.get("access", ""), None)
        self.store.save()

    async def exchange_identity_assertion(self, client, params) -> OAuthToken:
        raise TokenError("unsupported_grant_type", "the JWT bearer grant is not supported")

    # --- owner management --------------------------------------------------

    def clients(self) -> list[dict[str, Any]]:
        live: dict[str, int] = {}
        now = time.time()
        for record in self.store.data["refresh"].values():
            if record["expires_at"] > now:
                live[record["client_id"]] = live.get(record["client_id"], 0) + 1
        return [
            {
                "client_id": cid,
                "client_name": c.get("client_name", ""),
                "redirect_uris": c.get("redirect_uris", []),
                "registered_at": c.get("registered_at"),
                "active_grants": live.get(cid, 0),
            }
            for cid, c in self.store.data["clients"].items()
        ]

    def forget_client(self, client_id: str) -> bool:
        """Revoke every token a client holds and drop its registration."""
        found = self.store.data["clients"].pop(client_id, None) is not None
        for table in ("access", "refresh"):
            self.store.data[table] = {
                k: v for k, v in self.store.data[table].items() if v["client_id"] != client_id
            }
        self.codes = {k: v for k, v in self.codes.items() if v.client_id != client_id}
        self.store.save()
        return found

    # --- consent page ------------------------------------------------------

    def _page(self, request_id: str, entry: dict[str, Any], error: str = "", status: int = 200) -> Response:
        client = self.store.data["clients"].get(entry["client_id"], {})
        params: AuthorizationParams = entry["params"]
        target = urlparse(str(params.redirect_uri))
        # A custom scheme (cursor://, vscode://) is part of who receives the grant, so show it.
        where = target.netloc if target.scheme in ("http", "https") else f"{target.scheme}://{target.netloc}"
        name = html.escape(client.get("client_name") or "An MCP client")
        notice = f'<p class="err">{html.escape(error)}</p>' if error else ""
        body = f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect to obsidian-wiki</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:28rem;margin:4rem auto;padding:0 1rem;color:#222}}
.box{{border:1px solid #ddd;border-radius:10px;padding:1.5rem}}
code{{background:#f3f3f3;padding:.1rem .3rem;border-radius:4px}}
input[type=password]{{width:100%;padding:.5rem;font:inherit;box-sizing:border-box}}
button{{font:inherit;padding:.5rem 1rem;margin:.75rem .5rem 0 0;border-radius:6px;border:1px solid #888;cursor:pointer}}
.go{{background:#222;color:#fff;border-color:#222}} .err{{color:#b00020}} small{{color:#666}}
</style>
<div class="box">
<h2>Connect {name}?</h2>
<p><b>{name}</b> wants access to this vault's memory tools. Approving sends access to
<code>{html.escape(where or "an unknown address")}</code>. Only continue if you started this connection.</p>
<form method="post" action="{CONSENT_PATH}">
<input type="hidden" name="request" value="{html.escape(request_id)}">
<label>Vault key<br><input type="password" name="key" autocomplete="current-password" autofocus></label>
<small>Your <code>WIKI_API_KEY</code> grants read and write; <code>WIKI_READ_KEY</code> grants read-only.</small>
{notice}
<div><button class="go" name="decision" value="approve">Approve</button>
<button name="decision" value="deny">Deny</button></div>
</form></div>"""
        return HTMLResponse(body, status_code=status, headers={
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        })

    def _live(self, request_id: str) -> dict[str, Any] | None:
        entry = self.pending.get(request_id)
        if entry and entry["created"] > time.time() - PENDING_TTL:
            return entry
        return None

    async def consent(self, request: Request) -> Response:
        if request.method == "GET":
            request_id = request.query_params.get("request", "")
            entry = self._live(request_id)
            if entry is None:
                return HTMLResponse("This sign-in link has expired. Start the connection again.", 400)
            return self._page(request_id, entry)

        # Parsed by hand: Starlette's form parser needs python-multipart, which the
        # server extra doesn't pull in for one urlencoded form.
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode("utf-8", "replace")).items()}
        request_id = form.get("request", "")
        entry = self._live(request_id)
        if entry is None:
            return HTMLResponse("This sign-in link has expired. Start the connection again.", 400)
        params: AuthorizationParams = entry["params"]

        if form.get("decision") != "approve":
            self.pending.pop(request_id, None)
            return RedirectResponse(construct_redirect_uri(
                str(params.redirect_uri), error="access_denied", state=params.state), 302)

        # A wrong key is a 401, which the Guard counts toward the lockout.
        access = self.key_access(form.get("key", ""))
        if access is None:
            page = self._page(request_id, entry, "That key isn't valid for this vault.", status=401)
            page.headers[FAILED_HEADER] = "1"
            return page

        allowed = SCOPES if access == "write" else [SCOPE_READ]
        requested = params.scopes or allowed
        granted = [s for s in requested if s in allowed] or [SCOPE_READ]
        self.pending.pop(request_id, None)
        code = secrets.token_urlsafe(32)
        self.codes[code] = AuthorizationCode(
            code=code, scopes=granted, expires_at=time.time() + CODE_TTL,
            client_id=entry["client_id"], code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        return RedirectResponse(construct_redirect_uri(
            str(params.redirect_uri), code=code, state=params.state), 302)
