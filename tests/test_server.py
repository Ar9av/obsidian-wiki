"""Server checks. Skipped unless the optional [server] extra is installed."""

from __future__ import annotations

import importlib
import sys

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")
from fastapi.testclient import TestClient  # noqa: E402

KEY = "test-key"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WIKI_API_KEY", KEY)
    monkeypatch.delenv("WIKI_ALLOW_ANONYMOUS", raising=False)
    sys.modules.pop("obsidian_wiki.server", None)
    server = importlib.import_module("obsidian_wiki.server")
    with TestClient(server.app) as c:
        c.headers["authorization"] = f"Bearer {KEY}"
        yield c


def test_health_needs_no_key(client):
    client.headers.pop("authorization")
    assert client.get("/health").json()["ok"] is True


def test_missing_and_wrong_key_are_rejected(client):
    client.headers.pop("authorization")
    assert client.get("/v1/search", params={"q": "x"}).status_code == 401
    client.headers["authorization"] = "Bearer nope"
    assert client.get("/v1/search", params={"q": "x"}).status_code == 401


def test_write_then_search_and_read_round_trips(client, tmp_path):
    written = client.post("/v1/pages", json={
        "title": "Vector Clocks",
        "category": "concepts",
        "summary": "Ordering events without a global clock.",
        "tags": ["distributed-systems"],
        "content": "Vector clocks track causality across replicas.",
    }).json()
    assert written["path"] == "concepts/vector-clocks.md"
    on_disk = (tmp_path / written["path"]).read_text()
    assert "title: Vector Clocks" in on_disk and "updated:" in on_disk
    assert "vector-clocks.md" in (tmp_path / "log.md").read_text()

    hits = client.get("/v1/search", params={"q": "vector clocks"}).json()
    assert any("vector-clocks" in c["page"] for c in hits["candidates"])
    assert "causality" in client.get(f"/v1/pages/{written['path']}").json()["markdown"]


def test_created_date_survives_an_update(client, tmp_path):
    body = {"title": "Raft", "category": "concepts", "content": "one"}
    first = client.post("/v1/pages", json=body).json()
    body["content"] = "two"
    assert client.post("/v1/pages", json=body).json()["created"] == first["created"]
    assert (tmp_path / first["path"]).read_text().endswith("two\n")


def test_upsert_false_conflicts(client):
    body = {"title": "Paxos", "category": "concepts", "content": "x", "upsert": False}
    assert client.post("/v1/pages", json=body).status_code == 200
    assert client.post("/v1/pages", json=body).status_code == 409


@pytest.mark.parametrize("path", ["../../etc/passwd", "concepts/../../escape.md", "/etc/passwd"])
def test_path_traversal_is_refused(client, path):
    # A leading slash is absorbed by the route, so absolute paths land as relative
    # ones inside the vault — a 404, never a read outside it.
    assert client.get(f"/v1/pages/{path}").status_code in (400, 404)


def test_write_cannot_escape_the_vault(client, tmp_path):
    resp = client.post("/v1/pages", json={
        "title": "escape", "category": "../../..", "content": "x",
    })
    # The category is slugified before it becomes a directory, so dots never survive.
    assert ".." not in resp.json()["path"]
    assert not (tmp_path.parent / "escape.md").exists()
