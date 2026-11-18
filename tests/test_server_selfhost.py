"""Self-hosting: the read-only key, `obsidian-wiki serve`, and two-way git sync.

The server checks are skipped unless the optional [server] extra is installed;
the git sync checks need only git.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from obsidian_wiki import sync as vault_sync

WRITE, READ = "write-key", "read-key"
MCP_HEADERS = {"accept": "application/json, text/event-stream", "host": "localhost:8080"}


@pytest.fixture(autouse=True)
def git_identity(monkeypatch):
    # The Docker image sets these; CI runners may have no global git identity.
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "wiki test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "wiki@test.invalid")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
    ).stdout


def _load_server(monkeypatch, vault: Path, **env: str):
    pytest.importorskip("fastapi")
    pytest.importorskip("mcp")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    for var in ("WIKI_API_KEY", "WIKI_READ_KEY", "WIKI_ALLOW_ANONYMOUS",
                "WIKI_GIT_REMOTE", "WIKI_GIT_SYNC_INTERVAL", "WIKI_HOST"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    sys.modules.pop("obsidian_wiki.server", None)
    return importlib.import_module("obsidian_wiki.server")


def _mcp(client, key: str, method: str, params: dict | None = None):
    response = client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers={**MCP_HEADERS, "authorization": f"Bearer {key}"},
    )
    assert response.status_code == 200, response.text
    if response.headers["content-type"].startswith("application/json"):
        return response.json()
    data = [line[5:] for line in response.text.splitlines() if line.startswith("data:")]
    return json.loads(data[-1])


# --- read-only key ----------------------------------------------------------

@pytest.fixture
def two_key_client(tmp_path, monkeypatch):
    server = _load_server(monkeypatch, tmp_path, WIKI_API_KEY=WRITE, WIKI_READ_KEY=READ)
    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        yield client


PAGE = {"title": "Gossip", "category": "concepts", "content": "Epidemic broadcast."}


def test_read_key_reads_but_cannot_write_over_rest(two_key_client):
    read = {"authorization": f"Bearer {READ}"}
    write = {"authorization": f"Bearer {WRITE}"}
    assert two_key_client.post("/v1/pages", json=PAGE, headers=write).status_code == 200

    assert two_key_client.get("/v1/search", params={"q": "gossip"}, headers=read).status_code == 200
    assert two_key_client.get("/v1/pages/concepts/gossip.md", headers=read).status_code == 200
    assert two_key_client.post("/v1/context-pack", json={"topic": "gossip"}, headers=read).status_code == 200
    assert two_key_client.get("/v1/memory/recap", headers=read).status_code == 200

    assert two_key_client.post("/v1/pages", json=PAGE, headers=read).status_code == 403
    assert two_key_client.post("/v1/memory/profile", json={"key": "a", "value": "b"}, headers=read).status_code == 403
    assert two_key_client.post("/v1/memory/todos", json={"text": "x"}, headers=read).status_code == 403
    assert two_key_client.post("/v1/memory/sync", json={}, headers=read).status_code == 403


def test_read_key_sees_only_read_tools_over_mcp(two_key_client):
    write_tools = {t["name"] for t in _mcp(two_key_client, WRITE, "tools/list")["result"]["tools"]}
    read_tools = {t["name"] for t in _mcp(two_key_client, READ, "tools/list")["result"]["tools"]}
    assert {"memory_write", "memory_profile", "memory_todo", "memory_sync"} <= write_tools
    assert read_tools == {"memory_search", "memory_read", "memory_context_pack", "memory_recap"}

    called = _mcp(two_key_client, READ, "tools/call",
                  {"name": "memory_write", "arguments": {"title": "x", "category": "concepts", "content": "x"}})
    assert "error" in called or called["result"].get("isError")


def test_tools_carry_read_only_annotations(two_key_client):
    tools = {t["name"]: t for t in _mcp(two_key_client, WRITE, "tools/list")["result"]["tools"]}
    assert tools["memory_search"]["annotations"]["readOnlyHint"] is True
    assert tools["memory_write"]["annotations"]["readOnlyHint"] is False
    assert tools["memory_write"]["annotations"]["destructiveHint"] is True


def test_connect_lists_the_tools_the_key_will_see(two_key_client):
    body = two_key_client.get("/v1/connect", headers={"authorization": f"Bearer {READ}"}).json()
    assert body["access"] == "read"
    assert "memory_write" not in {t["name"] for t in body["tools"]}


def test_read_only_server_rejects_an_empty_bearer(tmp_path, monkeypatch):
    """With no write key set, an empty token must not match the empty key."""
    server = _load_server(monkeypatch, tmp_path, WIKI_READ_KEY=READ)
    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        for header in ("Bearer ", "Bearer", ""):
            assert client.post("/v1/pages", json=PAGE, headers={"authorization": header}).status_code == 401
            r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                            headers={**MCP_HEADERS, "authorization": header})
            assert r.status_code == 401
        assert client.get("/v1/search", params={"q": "x"},
                          headers={"authorization": f"Bearer {READ}"}).status_code == 200


def test_same_key_for_read_and_write_is_refused(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="must differ"):
        _load_server(monkeypatch, tmp_path, WIKI_API_KEY="same", WIKI_READ_KEY="same")


# --- obsidian-wiki serve ----------------------------------------------------

def _serve(monkeypatch, tmp_path, *argv: str, **env: str):
    pytest.importorskip("fastapi")
    pytest.importorskip("mcp")
    import uvicorn

    from obsidian_wiki import cli

    for var in ("WIKI_API_KEY", "WIKI_READ_KEY", "WIKI_ALLOW_ANONYMOUS", "WIKI_HOST",
                "WIKI_PORT", "WIKI_GIT_REMOTE", "WIKI_GIT_SYNC_INTERVAL"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    import obsidian_wiki

    # `from obsidian_wiki import server` reads the package attribute, not just
    # sys.modules, so drop both or an earlier test's module (and keys) leaks in.
    sys.modules.pop("obsidian_wiki.server", None)
    monkeypatch.delattr(obsidian_wiki, "server", raising=False)
    seen: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    code = cli.main(["serve", "--vault", str(tmp_path), *argv])
    return code, seen


def test_serve_binds_loopback_by_default(tmp_path, monkeypatch):
    code, seen = _serve(monkeypatch, tmp_path, WIKI_API_KEY=WRITE)
    assert code == 0 and seen == {"host": "127.0.0.1", "port": 8080}


def test_serve_takes_host_and_port(tmp_path, monkeypatch):
    code, seen = _serve(monkeypatch, tmp_path, "--host", "0.0.0.0", "--port", "9000", WIKI_API_KEY=WRITE)
    assert code == 0 and seen == {"host": "0.0.0.0", "port": 9000}


def test_serve_without_a_key_explains_instead_of_crashing(tmp_path, monkeypatch, capsys):
    code, seen = _serve(monkeypatch, tmp_path)
    assert code == 1 and not seen
    assert "WIKI_API_KEY" in capsys.readouterr().err


def test_serve_refuses_anonymous_off_loopback(tmp_path, monkeypatch, capsys):
    code, seen = _serve(monkeypatch, tmp_path, "--host", "0.0.0.0", WIKI_ALLOW_ANONYMOUS="1")
    assert code == 1 and not seen
    assert "refusing" in capsys.readouterr().err


# --- two-way git sync -------------------------------------------------------

@pytest.fixture
def remote(tmp_path):
    """A bare remote seeded with one page, as a laptop would have pushed it."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
    (seed / "concepts").mkdir()
    (seed / "concepts" / "raft.md").write_text("Raft.\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", "origin", "HEAD")
    return bare


def _laptop(tmp_path, remote: Path) -> Path:
    laptop = tmp_path / "laptop"
    subprocess.run(["git", "clone", "-q", str(remote), str(laptop)], check=True, capture_output=True)
    return laptop


def test_bootstrap_clones_into_an_empty_vault(tmp_path, remote):
    vault = tmp_path / "vault"
    assert "cloned" in vault_sync.bootstrap_remote(vault, str(remote))
    assert (vault / "concepts" / "raft.md").is_file()
    # Lock files and caches stay out of commits without touching .gitignore.
    assert ".memory.lock" in (vault / ".git" / "info" / "exclude").read_text()
    assert not (vault / ".gitignore").exists()


def test_bootstrap_keeps_an_existing_checkout(tmp_path, remote):
    laptop = _laptop(tmp_path, remote)
    (laptop / "mine.md").write_text("untouched\n", encoding="utf-8")
    assert "existing checkout" in vault_sync.bootstrap_remote(laptop, "https://elsewhere.invalid/x.git")
    assert vault_sync.get_remote(laptop) == str(remote)
    assert (laptop / "mine.md").read_text() == "untouched\n"


def test_edits_on_both_sides_meet(tmp_path, remote):
    server = tmp_path / "server"
    vault_sync.bootstrap_remote(server, str(remote))
    laptop = _laptop(tmp_path, remote)

    (laptop / "concepts" / "paxos.md").write_text("Paxos.\n", encoding="utf-8")
    _git(laptop, "add", "-A")
    _git(laptop, "commit", "-q", "-m", "laptop edit")
    _git(laptop, "push", "-q")
    (server / "concepts" / "gossip.md").write_text("Gossip.\n", encoding="utf-8")
    (server / ".memory.lock").write_text("", encoding="utf-8")

    code, message = vault_sync.pull_and_push(server)
    assert code == 0, message
    assert (server / "concepts" / "paxos.md").is_file()

    _git(laptop, "pull", "-q")
    assert (laptop / "concepts" / "gossip.md").read_text() == "Gossip.\n"
    assert not (laptop / ".memory.lock").exists()
    assert vault_sync.pull_and_push(server) == (0, "wiki-sync: up to date")


def test_a_conflict_keeps_both_sides_and_pushes_nothing(tmp_path, remote):
    server = tmp_path / "server"
    vault_sync.bootstrap_remote(server, str(remote))
    laptop = _laptop(tmp_path, remote)

    (laptop / "concepts" / "raft.md").write_text("Raft, laptop.\n", encoding="utf-8")
    _git(laptop, "commit", "-q", "-am", "laptop")
    _git(laptop, "push", "-q")
    (server / "concepts" / "raft.md").write_text("Raft, server.\n", encoding="utf-8")

    code, message = vault_sync.pull_and_push(server)
    assert code == 1 and "conflict" in message
    # Rebase aborted: the server's edit is committed locally, not lost or half-merged.
    assert not (server / ".git" / "rebase-merge").exists()
    assert (server / "concepts" / "raft.md").read_text() == "Raft, server.\n"
    assert "server" in _git(server, "log", "-1", "--format=%s")
    assert _git(remote, "show", "HEAD:concepts/raft.md") == "Raft, laptop.\n"


def test_credentials_in_a_remote_url_are_redacted():
    text = "fatal: unable to access 'https://x-access-token:ghp_secret@github.com/me/v.git/'"
    assert "ghp_secret" not in vault_sync.redact_remote(text)
    assert "https://***@github.com/me/v.git" in vault_sync.redact_remote(text)
    assert vault_sync.redact_remote("git@github.com:me/v.git") == "git@github.com:me/v.git"


def test_server_clones_on_boot_and_pushes_a_write_at_shutdown(tmp_path, monkeypatch, remote):
    vault = tmp_path / "vault"
    server = _load_server(monkeypatch, vault, WIKI_API_KEY=WRITE,
                          WIKI_GIT_REMOTE=str(remote), WIKI_GIT_SYNC_INTERVAL="3600")
    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        client.headers["authorization"] = f"Bearer {WRITE}"
        assert (vault / "concepts" / "raft.md").is_file()
        assert client.get("/health").json()["git_sync_ok"] is True
        assert client.post("/v1/pages", json=PAGE).status_code == 200
        status = client.get("/v1/status").json()["git"]["sync"]
        assert status["enabled"] and status["interval"] == 3600
    assert "Epidemic broadcast." in _git(remote, "show", "HEAD:concepts/gossip.md")
    assert ".memory.lock" not in _git(remote, "ls-tree", "-r", "--name-only", "HEAD")
