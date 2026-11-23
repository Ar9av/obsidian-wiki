"""Server checks. Skipped unless the optional [server] extra is installed."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys

import pytest

from obsidian_wiki.lint import _parse_frontmatter_values

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
    assert "title: >-\n  Vector Clocks" in on_disk and "updated:" in on_disk
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


def test_reserved_raw_category_keeps_its_underscore(client):
    # The four skip lists exclude a page by exact path match against "_raw";
    # a dropped leading underscore would land it in "raw/" instead.
    written = client.post("/v1/pages", json={
        "title": "Clipped Note", "category": "_raw", "content": "x",
    }).json()
    assert written["path"] == "_raw/clipped-note.md"


def test_frontmatter_scalars_round_trip_through_yaml(client, tmp_path):
    # A bare scalar containing ": " or "#" breaks YAML parsing — Obsidian then
    # reports "Invalid properties" and hides the frontmatter. write_page emits
    # title/summary as folded blocks, which need no escaping, so every value
    # survives for a YAML reader and stays readable on disk.
    title = 'Kafka: "Rebalance" #notes — offsets: 42'
    summary = "Entità documentate; offsets: 42."
    written = client.post("/v1/pages", json={
        "title": title, "category": "concepts", "summary": summary, "content": "x",
    }).json()
    on_disk = (tmp_path / written["path"]).read_text(encoding="utf-8")
    for key, expected in (("title", title), ("summary", summary)):
        assert f"{key}: >-\n  {expected}" in on_disk, f"{key} not folded:\n{on_disk}"
    # The vault's own frontmatter reader must see the value, not an escape.
    front = on_disk.split("---")[1]
    assert _parse_frontmatter_values(front)["title"] == title
    assert _parse_frontmatter_values(front)["summary"] == summary


# --- operations console -----------------------------------------------------

def _page(vault, rel, body="# hi\n"):
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_console_endpoints_need_a_key(client):
    client.headers.pop("authorization")
    for route in ("/v1/status", "/v1/health", "/v1/staging"):
        assert client.get(route).status_code == 401


def test_status_derives_counts_from_the_vault(client, tmp_path):
    _page(tmp_path, "concepts/a.md")
    _page(tmp_path, "concepts/b.md")
    _page(tmp_path, "entities/c.md")
    _page(tmp_path, "_raw/note.md")
    _page(tmp_path, "_staging/concepts/a.md")
    _page(tmp_path, "index.md")
    (tmp_path / ".manifest.json").write_text(
        '{"last_ingest": "2026-01-01T00:00:00Z", "sources": [{"source_id": "s1",'
        ' "type": "repository", "ingested_at": "2026-01-01T00:00:00Z",'
        ' "pages_produced": ["concepts/a.md", "concepts/gone.md"]}]}',
        encoding="utf-8",
    )

    body = client.get("/v1/status").json()
    # Underscore folders are staging areas, not pages, so they stay out of the count.
    assert body["pages"] == 4
    # Root files like index.md are pages but belong to no category folder.
    assert body["categories"] == {"(root)": 1, "concepts": 2, "entities": 1}
    assert body["raw_count"] == 1 and body["staging_count"] == 1
    assert body["last_ingest"] == "2026-01-01T00:00:00Z"
    assert body["sources"][0]["missing_pages"] == ["concepts/gone.md"]
    assert body["git"]["repo"] is False


def test_status_reads_every_manifest_container_shape(client, tmp_path):
    """Real vaults mix the shapes different skills write; none may be dropped."""
    _page(tmp_path, "concepts/a.md")
    (tmp_path / ".manifest.json").write_text(
        """{
          "sources": [{"source_id": "ingested", "type": "repository",
                       "ingested_at": "2026-01-01", "pages_produced": ["concepts/a.md"]}],
          "projects": {"tractorex": {"last_synced": "2026-02-02",
                       "pages_in_vault": ["concepts/a.md", "concepts/gone.md"]}},
          "research_sessions": [{"session_id": "r1", "skill": "wiki-research",
                       "completed": "2026-03-03", "pages_created": ["concepts/a.md"],
                       "pages_updated": ["index.md"]}]
        }""",
        encoding="utf-8",
    )

    by_id = {s["source_id"]: s for s in client.get("/v1/status").json()["sources"]}
    assert set(by_id) == {"ingested", "tractorex", "r1"}
    # A dict container keys entries by name; a list container carries its own id.
    assert by_id["tractorex"]["ingested_at"] == "2026-02-02"
    assert by_id["tractorex"]["missing_pages"] == ["concepts/gone.md"]
    assert by_id["r1"]["type"] == "wiki-research"


def test_staging_diffs_new_and_updated_pages(client, tmp_path):
    _page(tmp_path, "concepts/live.md", "old\n")
    _page(tmp_path, "_staging/concepts/live.md", "new\n")
    _page(tmp_path, "_staging/concepts/fresh.md", "brand new\n")

    items = {i["live_path"]: i for i in client.get("/v1/staging").json()["items"]}
    assert items["concepts/fresh.md"]["kind"] == "new"
    update = items["concepts/live.md"]
    assert update["kind"] == "update"
    assert "-old" in update["diff"] and "+new" in update["diff"]


def _git_in(vault, *args):
    subprocess.run(
        ["git", "-C", str(vault), "-c", "user.name=t", "-c", "user.email=t@e.test", *args],
        check=True,
        capture_output=True,
    )


def test_status_leaves_okignored_paths_out(client, tmp_path):
    for rel in (
        "concepts/kept page.md",
        "concepts/\u0e42\u0e19\u0e49\u0e15.md",
        "Private/secret-a.md",
        "My Inbox/secret-\u0e01.md",
        "_raw/note.md",
        "_raw/quarantine/secret-b.md",
        "_staging/private/secret-c.md",
    ):
        _page(tmp_path, rel)
    # Distinct bodies, so git can't pair these two renames the other way round.
    _page(tmp_path, "concepts/moved.md", "moved\n")
    _page(tmp_path, "Private/secret-rename.md", "rename\n")
    (tmp_path / ".okignore").write_text(
        "Private/\nMy Inbox/\n_raw/quarantine\n_staging/private\n*.draft.md\n", encoding="utf-8"
    )
    _git_in(tmp_path, "init", "-q")
    _git_in(tmp_path, "add", "-A")
    _git_in(tmp_path, "commit", "-qm", "seed")
    for rel in (
        "concepts/kept page.md",
        "concepts/\u0e42\u0e19\u0e49\u0e15.md",
        "Private/secret-a.md",
        "My Inbox/secret-\u0e01.md",
    ):
        _page(tmp_path, rel, "edited\n")
    _page(tmp_path, "Private/secret-new.md")
    _page(tmp_path, "notes/fresh.md")
    # git would report this as `?? clients/secret-acme/`, which no file pattern matches.
    _page(tmp_path, "clients/secret-acme/plan.draft.md")
    _git_in(tmp_path, "mv", "concepts/moved.md", "concepts/renamed.md")
    _git_in(tmp_path, "mv", "Private/secret-rename.md", "concepts/out-of-private.md")

    response = client.get("/v1/status")
    body = response.json()

    assert "secret" not in response.text
    assert body["raw_count"] == 1 and body["staging_count"] == 0
    assert sorted(body["git"]["dirty"]) == sorted([
        " M concepts/kept page.md",
        " M concepts/\u0e42\u0e19\u0e49\u0e15.md",
        "?? notes/fresh.md",
        "R  concepts/moved.md -> concepts/renamed.md",
        "R  (ignored) -> concepts/out-of-private.md",
    ])
    assert body["git"]["dirty_count"] == 5


def test_staging_endpoint_does_not_diff_an_ignored_live_page(client, tmp_path):
    _page(tmp_path, "concepts/kept.md", "kept\n")
    _page(tmp_path, "_staging/concepts/kept.md", "revised\n")
    _page(tmp_path, "Areas/Personal/page.md", "secret\n")
    _page(tmp_path, "_staging/Areas/Personal/page.md", "revised\n")
    (tmp_path / ".okignore").write_text("Areas/Personal/\n", encoding="utf-8")

    response = client.get("/v1/staging")

    assert "secret" not in response.text
    assert response.json()["count"] == 1


def test_health_reports_doctor_and_lint(client, tmp_path):
    _page(tmp_path, "concepts/a.md")
    body = client.get("/v1/health").json()
    assert body["doctor"]["status"] in {"pass", "info", "warn", "fail"}
    assert body["lint"]["stats"]["pages"] == 1


def test_graph_lists_pages_and_resolved_links(client, tmp_path):
    _page(tmp_path, "concepts/a.md", "links [[b]] and [[b|again]] and [[missing]]\n")
    _page(tmp_path, "entities/b.md", "---\ntitle: >-\n  Bee Page\n---\nback to [[a]]\n")
    _page(tmp_path, "index.md", "[[a]] [[b]]\n")  # bookkeeping, not a node
    g = client.get("/v1/graph").json()
    assert {(n["id"], n["path"], n["category"]) for n in g["nodes"]} == {
        ("a", "concepts/a.md", "concepts"), ("b", "entities/b.md", "entities"),
    }
    assert g["edges"] == [["a", "b"], ["b", "a"]]  # deduped, unresolved dropped
    assert {n["id"]: n["title"] for n in g["nodes"]} == {"a": "", "b": "Bee Page"}
    client.headers.pop("authorization")
    assert client.get("/v1/graph").status_code == 401


def test_ui_shell_carries_no_vault_data(client, tmp_path):
    _page(tmp_path, "concepts/secret-page.md", "sensitive\n")
    client.headers.pop("authorization")
    page = client.get("/ui")
    # The shell is static: it must be fetch-driven, never server-rendered with vault content.
    assert page.status_code == 200
    assert "secret-page" not in page.text and "sensitive" not in page.text


def test_connect_reports_what_an_agent_needs_behind_the_key(client, tmp_path):
    body = client.get("/v1/connect").json()
    # The interpreter running the server has the [server] extra, so configs that
    # launch `python -m obsidian_wiki mcp` with it work without PATH.
    assert body["python"] == sys.executable
    assert body["vault"] == str(tmp_path)
    assert body["key_required"] is True
    assert {t["name"] for t in body["tools"]} >= {"memory_recap", "memory_search", "memory_write"}
    client.headers.pop("authorization")
    assert client.get("/v1/connect").status_code == 401  # reveals local paths


def test_root_redirects_to_the_viewer_and_its_bundle_is_served(client):
    import re

    assert client.get("/", follow_redirects=False).headers["location"] == "/ui"
    shell = client.get("/ui").text
    assets = re.findall(r'(?:src|href)="(/ui/assets/[^"]+)"', shell)
    assert assets, "built viewer missing: run `cd ui && npm run build`"
    for asset in assets:
        res = client.get(asset)
        assert res.status_code == 200 and len(res.content) > 1000
    assert client.get("/ui/assets/../../server.py").status_code == 404


@pytest.mark.parametrize("key", ["", "set-key"])
def test_ui_command_binds_loopback_and_only_drops_auth_without_a_key(tmp_path, monkeypatch, key):
    import uvicorn
    import webbrowser

    from obsidian_wiki import cli

    monkeypatch.delenv("WIKI_ALLOW_ANONYMOUS", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    if key:
        monkeypatch.setenv("WIKI_API_KEY", key)
    else:
        monkeypatch.delenv("WIKI_API_KEY", raising=False)
    # A fresh import, so the server reads the env cmd_ui sets; `from obsidian_wiki
    # import server` would otherwise reuse the package attribute.
    import obsidian_wiki

    sys.modules.pop("obsidian_wiki.server", None)
    monkeypatch.delattr(obsidian_wiki, "server", raising=False)
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw, app=app))
    monkeypatch.setattr(webbrowser, "open", lambda url: pytest.fail("--no-open still opened a browser"))

    assert cli.main(["ui", "--vault", str(tmp_path), "--port", "4321", "--no-open"]) == 0
    assert (seen["host"], seen["port"]) == ("127.0.0.1", 4321)
    assert seen["app"] is sys.modules["obsidian_wiki.server"].app
    assert os.environ["OBSIDIAN_VAULT_PATH"] == str(tmp_path.resolve())
    assert os.environ.get("WIKI_ALLOW_ANONYMOUS") == (None if key else "1")


@pytest.mark.parametrize("wiki_host, expected", [(None, "127.0.0.1"), ("0.0.0.0", "0.0.0.0")])
def test_bind_host_is_loopback_unless_asked(client, monkeypatch, wiki_host, expected):
    """A browser console over the whole vault must not reach every interface by default."""
    import uvicorn

    monkeypatch.delenv("WIKI_HOST", raising=False)
    if wiki_host:
        monkeypatch.setenv("WIKI_HOST", wiki_host)

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    sys.modules["obsidian_wiki.server"].main()
    assert seen["host"] == expected


def test_anonymous_server_refuses_a_rebound_host(tmp_path, monkeypatch):
    """Keyless `obsidian-wiki ui` must not answer a DNS-rebinding page (Host: attacker)."""
    (tmp_path / "concepts").mkdir()
    (tmp_path / "concepts" / "secret.md").write_text("pin 1234\n", encoding="utf-8")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.delenv("WIKI_API_KEY", raising=False)
    monkeypatch.delenv("WIKI_HOST", raising=False)
    monkeypatch.setenv("WIKI_ALLOW_ANONYMOUS", "1")
    sys.modules.pop("obsidian_wiki.server", None)
    server = importlib.import_module("obsidian_wiki.server")
    with TestClient(server.app) as c:
        page = "/v1/pages/concepts/secret.md"
        assert c.get(page, headers={"host": "attacker.example:3114"}).status_code == 400
        write = {"title": "planted", "content": "x"}
        assert c.post("/v1/pages", json=write, headers={"host": "attacker.example"}).status_code == 400
        assert c.get(page, headers={"host": "127.0.0.1:3114"}).status_code == 200
        assert c.get(page, headers={"host": "localhost:3114"}).status_code == 200
    assert not (tmp_path / "concepts" / "planted.md").exists()


MCP_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
# TestClient sends Host: testserver, which loopback rebinding protection refuses.
MCP_HEADERS = {"accept": "application/json, text/event-stream", "host": "localhost:8080"}


def test_mcp_needs_a_key(client):
    """A mounted app skips route dependencies; /mcp must still refuse a keyless caller."""
    assert client.post("/mcp/", json=MCP_LIST, headers=MCP_HEADERS).status_code == 200
    client.headers.pop("authorization")
    assert client.post("/mcp/", json=MCP_LIST, headers=MCP_HEADERS).status_code == 401
    client.headers["authorization"] = "Bearer nope"
    assert client.post("/mcp/", json=MCP_LIST, headers=MCP_HEADERS).status_code == 401


def test_mcp_answers_a_lan_host_when_bound_to_every_interface(tmp_path, monkeypatch):
    """WIKI_HOST=0.0.0.0 (the Docker image) must not 421 a request by LAN address (#266)."""
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WIKI_API_KEY", KEY)
    monkeypatch.setenv("WIKI_HOST", "0.0.0.0")
    sys.modules.pop("obsidian_wiki.server", None)
    server = importlib.import_module("obsidian_wiki.server")
    with TestClient(server.app) as c:
        r = c.post("/mcp/", json=MCP_LIST, headers={
            **MCP_HEADERS, "authorization": f"Bearer {KEY}", "host": "192.168.1.5:8080",
        })
    assert r.status_code == 200


def test_mcp_subcommand_serves_the_vault_over_stdio(tmp_path, monkeypatch):
    """`obsidian-wiki mcp` is what an agent launches; it needs no key and finds the vault."""
    import anyio
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    (tmp_path / "concepts").mkdir()
    (tmp_path / "concepts" / "tides.md").write_text(
        "---\ntitle: Tides\nsummary: How the moon moves water.\n---\nThe moon pulls the sea.\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WIKI_API_KEY", raising=False)
    monkeypatch.delenv("WIKI_ALLOW_ANONYMOUS", raising=False)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "obsidian_wiki", "mcp", "--vault", str(tmp_path)],
    )

    async def run():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            page = await session.call_tool("memory_read", {"path": "concepts/tides.md"})
            return names, page

    names, page = anyio.run(run)
    assert {"memory_search", "memory_read", "memory_write"} <= names
    assert "The moon pulls the sea." in page.content[0].text


@pytest.fixture
def ui_config(tmp_path, monkeypatch):
    """A private global config dir holding one named vault, for the viewer's tools."""
    from obsidian_wiki import ui_tools

    cfg = tmp_path / "cfg"
    other = tmp_path / "other-vault"
    other.mkdir()
    cfg.mkdir()
    (cfg / "config.work").write_text(f'OBSIDIAN_VAULT_PATH="{other}"\n')
    (cfg / "config.bak-20260101").write_text(f'OBSIDIAN_VAULT_PATH="{tmp_path / "gone"}"\n')
    monkeypatch.setattr(ui_tools, "config_dir", lambda: cfg)
    return cfg, other


def test_vault_switch_only_reaches_configured_vaults(client, tmp_path, ui_config):
    _, other = ui_config
    listed = client.get("/v1/vaults").json()
    assert [v["name"] for v in listed["vaults"]] == ["startup", "work"]  # the .bak backup is skipped
    assert client.post("/v1/vaults", json={"path": "/etc"}).status_code == 400
    assert client.post("/v1/vaults", json={"path": str(other)}).json()["current"] == str(other)
    assert client.get("/v1/status").json()["vault"] == str(other)
    assert client.post("/v1/vaults", json={"path": str(tmp_path.resolve())}).status_code == 200


def test_inbox_writes_into_raw_and_stays_inside_it(client, tmp_path):
    import base64

    note = client.post("/v1/inbox", json={"kind": "text", "title": "Idea: x", "text": "body"}).json()
    assert note["path"].startswith("_raw/") and note["path"].endswith("-idea-x.md")
    assert "title: >-\n  Idea: x" in (tmp_path / note["path"]).read_text()
    link = client.post("/v1/inbox", json={"kind": "url", "url": "https://example.com/a"}).json()
    assert "source_url: https://example.com/a" in (tmp_path / link["path"]).read_text()
    assert client.post("/v1/inbox", json={"kind": "url", "url": "javascript:alert(1)"}).status_code == 400
    up = client.post("/v1/inbox", json={"kind": "file", "filename": "../../evil.pdf",
                                        "data_b64": base64.b64encode(b"%PDF").decode()}).json()
    assert up["path"].startswith("_raw/") and (tmp_path / up["path"]).read_bytes() == b"%PDF"
    assert len(client.get("/v1/inbox").json()["items"]) == 3
    assert client.get("/v1/status").json()["raw_files"] == 3  # the PDF counts, unlike raw_count
    assert client.post("/v1/inbox/remove", json={"name": "../log.md"}).status_code == 404
    assert client.post("/v1/inbox/remove", json={"name": up["name"]}).status_code == 200
    assert not (tmp_path / up["path"]).exists()


def test_settings_keep_the_key_out_of_the_browser(client, ui_config, monkeypatch):
    cfg, _ = ui_config
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    saved = client.post("/v1/settings", json={"anthropic_api_key": "sk-ant-secret-1234", "provider": "anthropic"}).json()
    assert saved["anthropic_key_set"] and saved["anthropic_key_hint"] == "…1234"
    assert "secret" not in json.dumps(client.get("/v1/settings").json())
    assert (cfg / "ui-settings.json").stat().st_mode & 0o077 == 0
    assert client.post("/v1/settings", json={"provider": "nope"}).status_code == 400
    assert not client.post("/v1/settings", json={"anthropic_api_key": ""}).json()["anthropic_key_set"]


def test_litellm_settings_keep_the_key_out_of_the_browser(client, ui_config, monkeypatch):
    saved = client.post("/v1/settings", json={
        "provider": "litellm", "model": "gemini/gemini-2.5-flash",
        "litellm_api_base": "http://localhost:4000", "litellm_api_key": "sk-proxy-secret-5678",
    }).json()
    assert saved["provider"] == "litellm" and saved["litellm_key_hint"] == "…5678"
    assert saved["litellm_api_base"] == "http://localhost:4000"
    assert "secret" not in json.dumps(client.get("/v1/settings").json())


def test_ask_says_so_when_no_model_is_available(client, ui_config, monkeypatch):
    from obsidian_wiki import ui_tools

    monkeypatch.setattr(ui_tools.shutil, "which", lambda _: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/v1/ask", json={"question": "anything"})
    assert r.status_code == 409 and "API key" in r.json()["detail"]
    assert client.post("/v1/jobs", json={"task": "ingest"}).status_code == 409
    assert client.post("/v1/jobs", json={"task": "rm -rf"}).status_code == 400


def test_lint_for_next_actions_is_reused_until_a_page_changes(client, tmp_path, monkeypatch):
    server = sys.modules["obsidian_wiki.server"]
    runs = []
    monkeypatch.setattr(server, "lint_vault", lambda vault: runs.append(1) or {"status": "pass", "stats": {}})
    (tmp_path / "a.md").write_text("---\ntitle: A\n---\n")
    assert client.get("/v1/lint").json()["status"] == "pass"
    client.get("/v1/lint")
    assert len(runs) == 1
    (tmp_path / "b.md").write_text("---\ntitle: B\n---\n")
    client.get("/v1/lint")
    assert len(runs) == 2
    client.get("/v1/health")  # the Health view always runs a fresh one
    assert len(runs) == 3


def test_agent_jobs_ignore_the_vaults_own_claude_settings(tmp_path, monkeypatch):
    """A shared vault's .claude/settings.json hooks or .mcp.json must not run in a job."""
    from obsidian_wiki import ui_tools

    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
    monkeypatch.setattr(ui_tools.shutil, "which", lambda name: "/bin/claude")
    seen = {}
    monkeypatch.setattr(ui_tools, "_run_job", lambda job, cmd, vault: seen.update(cmd=cmd))
    monkeypatch.setattr(ui_tools, "_jobs", {})
    # Run the job thread inline, so the command is captured before we look.
    monkeypatch.setattr(ui_tools.threading, "Thread",
                        lambda target, args, **kw: type("T", (), {"start": lambda self: target(*args)})())
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ui_tools.UiError, match="wiki-lint skill isn't installed"):
        ui_tools.start_job(vault, "lint")

    (claude_home / "skills" / "wiki-lint").mkdir(parents=True)
    (claude_home / "skills" / "wiki-lint" / "SKILL.md").write_text("x")
    ui_tools.start_job(vault, "lint")
    cmd = seen["cmd"]
    assert cmd[cmd.index("--setting-sources") + 1] == "user"
    assert "--strict-mcp-config" in cmd


def test_search_reports_its_scope_and_can_be_limited_to_a_folder(client, tmp_path):
    for rel, name in (("projects/acme/zebra-plan.md", "Zebra Plan"), ("concepts/zebra-facts.md", "Zebra Facts"),
                      ("projects/acmeish/zebra-other.md", "Zebra Other")):
        _page(tmp_path, rel, f"---\ntitle: {name}\nsummary: zebra stripes\n---\nzebra stripes\n")
    everything = client.get("/v1/search", params={"q": "zebra"}).json()
    assert everything["scope"] == {"path_prefix": None, "searched": 3, "indexed": 3}
    assert len(everything["candidates"]) == 3

    scoped = client.get("/v1/search", params={"q": "zebra", "path_prefix": "/projects/acme/"}).json()
    assert scoped["scope"] == {"path_prefix": "projects/acme", "searched": 1, "indexed": 3}
    assert [c["page"] for c in scoped["candidates"]] == ["projects/acme/zebra-plan.md"]  # not projects/acmeish

    empty = client.get("/v1/search", params={"q": "zebra", "path_prefix": "nowhere"}).json()
    assert empty["candidates"] == [] and empty["scope"]["searched"] == 0
