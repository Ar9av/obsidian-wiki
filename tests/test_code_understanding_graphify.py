"""Graphify backend: reads graphify-out/graph.json, never runs graphify."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from obsidian_wiki.code_understanding import ProviderError, code_understand

# Shape copied from Graphify's own worked/httpx/graph.json (node-link, "links").
GRAPH = {
    "directed": True,
    "multigraph": False,
    "graph": {},
    "nodes": [
        {"id": "client", "label": "client.py", "file_type": "code", "source_file": "client.py", "source_location": "L1", "community": 1},
        {"id": "client_client", "label": "Client", "file_type": "code", "source_file": "client.py", "source_location": "L31", "community": 2},
        {"id": "models_url", "label": "URL", "file_type": "code", "source_file": "models.py", "source_location": "L10", "community": 0},
        {"id": "models_headers", "label": "Headers", "file_type": "code", "source_file": "models.py", "source_location": "L40", "community": 0},
    ],
    "links": [
        {"source": "client", "target": "client_client", "relation": "contains", "confidence": "EXTRACTED"},
        {"source": "client_client", "target": "models_url", "relation": "uses", "confidence": "INFERRED"},
        {"source": "client_client", "target": "models_headers", "relation": "calls", "confidence": "EXTRACTED"},
    ],
}


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    original = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "codegraph" else original(name))
    (tmp_path / "client.py").write_text("class Client: ...\n", encoding="utf-8")
    (tmp_path / "models.py").write_text("class URL: ...\n", encoding="utf-8")
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text(json.dumps(GRAPH), encoding="utf-8")
    return tmp_path


def test_auto_picks_graphify_when_its_graph_exists(project: Path) -> None:
    result = code_understand(project, changed=["client.py"], env={})
    assert result["backend"] == "graphify"
    by_symbol = {item["symbol"]: item for item in result["focus_map"]}
    assert by_symbol["Client"]["evidence"] == "changed-file"
    assert by_symbol["Client"]["lines"] == [31]
    # Extracted edges rank above inferred ones, and keep graphify's confidence.
    assert by_symbol["Headers"]["evidence"] == "graphify-extracted"
    assert by_symbol["URL"]["evidence"] == "graphify-inferred"
    assert by_symbol["Headers"]["rank"] < by_symbol["URL"]["rank"]
    assert by_symbol["URL"]["relation"] == "uses-Client"
    assert "models.py" in result["files"]


def test_explicit_graphify_without_a_graph_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(ProviderError, match="graphify-out/graph.json"):
        code_understand(tmp_path, backend_flag="graphify", changed=[], env={})
