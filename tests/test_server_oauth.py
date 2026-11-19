"""OAuth 2.1 sign-in for MCP clients, the rate limit / lockout guard, and PORT.

Skipped unless the optional [server] extra is installed.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import secrets
import sys
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")
from fastapi.testclient import TestClient  # noqa: E402

from obsidian_wiki.guard import Guard  # noqa: E402

WRITE, READ = "write-key", "read-key"
PUBLIC = "http://localhost:8080"
CALLBACK = "http://127.0.0.1:9999/callback"
MCP_HEADERS = {"accept": "application/json, text/event-stream", "host": "localhost:8080"}
_ENV = ("WIKI_API_KEY", "WIKI_READ_KEY", "WIKI_ALLOW_ANONYMOUS", "WIKI_OAUTH", "WIKI_PUBLIC_URL",
        "WIKI_GIT_REMOTE", "WIKI_GIT_SYNC_INTERVAL", "WIKI_HOST", "WIKI_RATE_LIMIT",
        "WIKI_AUTH_LOCKOUT", "WIKI_AUTH_LOCKOUT_SECONDS", "WIKI_PORT", "PORT", "WIKI_TRUSTED_PROXIES")


def _load(monkeypatch, vault, **env):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    for var in _ENV:
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    sys.modules.pop("obsidian_wiki.server", None)
    return importlib.import_module("obsidian_wiki.server")


@pytest.fixture
def oauth(tmp_path, monkeypatch):
    server = _load(monkeypatch, tmp_path, WIKI_API_KEY=WRITE, WIKI_READ_KEY=READ,
                   WIKI_OAUTH="1", WIKI_PUBLIC_URL=PUBLIC)
    with TestClient(server.app, follow_redirects=False) as client:
        yield client, server, tmp_path


def _tools(client, token):
    r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                    headers={**MCP_HEADERS, "authorization": f"Bearer {token}"})
    if r.status_code != 200:
        return r.status_code
    data = [line[5:] for line in r.text.splitlines() if line.startswith("data:")]
    body = json.loads(data[-1]) if data else r.json()
    return {t["name"] for t in body["result"]["tools"]}


def _sign_in(client, key, scope=None):
    """Register, authorize with PKCE, approve on the consent page, exchange the code."""
    reg = client.post("/register", json={
        "redirect_uris": [CALLBACK], "client_name": "Test <Client>",
        "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
    })
    assert reg.status_code == 201, reg.text
    client_id = reg.json()["client_id"]

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    query = {"response_type": "code", "client_id": client_id, "redirect_uri": CALLBACK,
             "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz",
             "resource": f"{PUBLIC}/mcp/"}
    if scope:
        query["scope"] = scope
    auth = client.get("/authorize", params=query)
    assert auth.status_code == 302, auth.text
    consent_url = urlparse(auth.headers["location"])
    request_id = parse_qs(consent_url.query)["request"][0]

    page = client.get(consent_url.path, params={"request": request_id})
    assert page.status_code == 200 and "Test &lt;Client&gt;" in page.text and "127.0.0.1:9999" in page.text
    assert page.headers["x-frame-options"] == "DENY"

    approved = client.post("/oauth/consent", data={"request": request_id, "key": key, "decision": "approve"})
    if approved.status_code != 302:
        return approved, None
    back = parse_qs(urlparse(approved.headers["location"]).query)
    assert back["state"] == ["xyz"]
    token = client.post("/token", data={
        "grant_type": "authorization_code", "code": back["code"][0], "redirect_uri": CALLBACK,
        "client_id": client_id, "code_verifier": verifier, "resource": f"{PUBLIC}/mcp/",
    })
    assert token.status_code == 200, token.text
    return token.json(), client_id


def test_metadata_points_clients_at_the_sign_in(oauth):
    client, _, _ = oauth
    unauth = client.post("/mcp/", json={}, headers=MCP_HEADERS)
    assert unauth.status_code == 401
    assert f'resource_metadata="{PUBLIC}/.well-known/oauth-protected-resource/mcp/"' in unauth.headers["www-authenticate"]

    for path in ("/.well-known/oauth-protected-resource/mcp/", "/.well-known/oauth-protected-resource/mcp",
                 "/.well-known/oauth-protected-resource"):
        meta = client.get(path).json()
        assert meta["authorization_servers"] == [PUBLIC] and "wiki:write" in meta["scopes_supported"]
    server_meta = client.get("/.well-known/oauth-authorization-server").json()
    assert server_meta["issuer"] == PUBLIC  # exact string: no trailing slash added
    assert server_meta["registration_endpoint"] == f"{PUBLIC}/register"
    assert server_meta["code_challenge_methods_supported"] == ["S256"]


def test_write_key_sign_in_gets_every_tool_and_refresh_rotates(oauth):
    client, _, vault = oauth
    tokens, client_id = _sign_in(client, WRITE)
    assert set(tokens["scope"].split()) == {"wiki:read", "wiki:write"}
    assert "memory_write" in _tools(client, tokens["access_token"])
    # Works on REST too: an OAuth token is just another credential.
    assert client.get("/v1/search", params={"q": "x"},
                      headers={"authorization": f"Bearer {tokens['access_token']}"}).status_code == 200

    # Stored hashed, never in the clear, and kept out of git.
    stored = (vault / ".wiki-server" / "oauth.json").read_text()
    assert tokens["access_token"] not in stored and tokens["refresh_token"] not in stored
    assert (vault / ".wiki-server" / ".gitignore").read_text().strip().endswith("*")

    fresh = client.post("/token", data={"grant_type": "refresh_token", "client_id": client_id,
                                        "refresh_token": tokens["refresh_token"]})
    assert fresh.status_code == 200, fresh.text
    assert _tools(client, tokens["access_token"]) == 401  # rotated out with its refresh token
    assert "memory_write" in _tools(client, fresh.json()["access_token"])
    replay = client.post("/token", data={"grant_type": "refresh_token", "client_id": client_id,
                                         "refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 400


def test_read_key_sign_in_is_read_only_even_when_write_is_asked_for(oauth):
    client, _, _ = oauth
    tokens, _ = _sign_in(client, READ, scope="wiki:read wiki:write")
    assert tokens["scope"] == "wiki:read"
    assert _tools(client, tokens["access_token"]) == {
        "memory_search", "memory_read", "memory_context_pack", "memory_recap"}


def test_wrong_key_on_the_consent_page_is_a_counted_401(oauth):
    client, _, _ = oauth
    response, _ = _sign_in(client, "guess")
    assert response.status_code == 401 and "isn&#x27;t valid" in response.text
    assert "x-wiki-auth-failed" not in response.headers


def test_owner_can_list_and_revoke_signed_in_apps(oauth):
    client, _, _ = oauth
    tokens, client_id = _sign_in(client, WRITE)
    owner = {"authorization": f"Bearer {WRITE}"}
    listed = client.get("/v1/oauth/clients", headers=owner).json()
    assert [c["client_name"] for c in listed["clients"]] == ["Test <Client>"]
    assert listed["clients"][0]["active_grants"] == 1
    assert client.delete(f"/v1/oauth/clients/{client_id}", headers=owner).status_code == 200
    assert _tools(client, tokens["access_token"]) == 401
    # An OAuth token can't manage OAuth clients unless it holds write scope... and here it's gone.
    assert client.get("/v1/oauth/clients", headers={"authorization": f"Bearer {READ}"}).status_code == 403


def test_tokens_for_another_resource_are_refused(oauth):
    client, _, _ = oauth
    reg = client.post("/register", json={"redirect_uris": [CALLBACK], "token_endpoint_auth_method": "none"})
    r = client.get("/authorize", params={
        "response_type": "code", "client_id": reg.json()["client_id"], "redirect_uri": CALLBACK,
        "code_challenge": "x" * 43, "code_challenge_method": "S256", "resource": "https://elsewhere.example/mcp",
    })
    assert r.status_code == 302 and "error=invalid_target" in r.headers["location"]


def test_oauth_needs_a_public_url(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="WIKI_PUBLIC_URL"):
        _load(monkeypatch, tmp_path, WIKI_API_KEY=WRITE, WIKI_OAUTH="1")


# --- guard ------------------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_lockout_after_repeated_bad_keys_then_expiry(tmp_path, monkeypatch):
    server = _load(monkeypatch, tmp_path, WIKI_API_KEY=WRITE, WIKI_AUTH_LOCKOUT="3",
                   WIKI_AUTH_LOCKOUT_SECONDS="60")
    clock = FakeClock()
    guard = server.app.user_middleware[0]
    guard.kwargs["clock"] = clock
    with TestClient(server.app) as client:
        bad = {"authorization": "Bearer nope"}
        assert [client.get("/v1/status", headers=bad).status_code for _ in range(3)] == [401] * 3
        locked = client.get("/v1/status", headers={"authorization": f"Bearer {WRITE}"})
        assert locked.status_code == 429 and int(locked.headers["retry-after"]) == 60
        assert client.get("/health").status_code == 200  # never limited
        clock.now += 61
        assert client.get("/v1/status", headers={"authorization": f"Bearer {WRITE}"}).status_code == 200


def test_keyless_probes_do_not_count_toward_the_lockout(tmp_path, monkeypatch):
    """MCP clients hit /mcp without a token to discover OAuth; that isn't a guess."""
    server = _load(monkeypatch, tmp_path, WIKI_API_KEY=WRITE, WIKI_AUTH_LOCKOUT="2")
    with TestClient(server.app) as client:
        for _ in range(5):
            assert client.post("/mcp/", json={}, headers=MCP_HEADERS).status_code == 401
        assert client.get("/v1/status", headers={"authorization": f"Bearer {WRITE}"}).status_code == 200


def test_rate_limit_per_client(tmp_path, monkeypatch):
    server = _load(monkeypatch, tmp_path, WIKI_API_KEY=WRITE, WIKI_RATE_LIMIT="5")
    clock = FakeClock()
    server.app.user_middleware[0].kwargs["clock"] = clock
    with TestClient(server.app) as client:
        client.headers["authorization"] = f"Bearer {WRITE}"
        codes = [client.get("/v1/search", params={"q": "x"}).status_code for _ in range(6)]
        assert codes == [200] * 5 + [429]
        clock.now += 61
        assert client.get("/v1/search", params={"q": "x"}).status_code == 200


def test_guard_tells_clients_apart():
    """Two addresses keep separate budgets (unit level: no proxy in the way)."""
    guard = Guard(app=None, rate_limit=1, clock=lambda: 5.0)
    assert guard.retry_after("10.0.0.1", 5.0) == 0
    assert guard.retry_after("10.0.0.1", 5.0) > 0
    assert guard.retry_after("10.0.0.2", 5.0) == 0


@pytest.mark.parametrize("env, port", [({}, 8080), ({"PORT": "10000"}, 10000),
                                        ({"PORT": "10000", "WIKI_PORT": "9000"}, 9000)])
def test_port_falls_back_to_the_paas_port(tmp_path, monkeypatch, env, port):
    import uvicorn

    server = _load(monkeypatch, tmp_path, WIKI_API_KEY=WRITE, **env)
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    server.main()
    assert seen["port"] == port


def test_trusted_proxies_reach_uvicorn(tmp_path, monkeypatch):
    import uvicorn

    server = _load(monkeypatch, tmp_path, WIKI_API_KEY=WRITE, WIKI_TRUSTED_PROXIES="172.16.0.0/12")
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    server.main()
    assert seen["forwarded_allow_ips"] == "172.16.0.0/12"
