"""The self-hosting templates and the MCP Registry entry stay consistent with the code."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_JSON = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
NAME = SERVER_JSON["name"]


def test_registry_ownership_markers_match_the_server_name():
    # The registry checks the PyPI README and the image label against server.json.
    assert f"<!-- mcp-name: {NAME} -->" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert f'io.modelcontextprotocol.server.name="{NAME}"' in (ROOT / "Dockerfile").read_text(encoding="utf-8")
    # README_TW is a translation of README and keeps the same marker.
    assert f"<!-- mcp-name: {NAME} -->" in (ROOT / "README_TW.md").read_text(encoding="utf-8")


def test_registry_packages_point_at_what_we_publish():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    packages = {p["registryType"]: p for p in SERVER_JSON["packages"]}
    assert packages["pypi"]["identifier"] == re.search(r'^name = "([^"]+)"', pyproject, re.M).group(1)
    assert packages["pypi"]["packageArguments"] == [{"type": "positional", "value": "mcp"}]
    assert packages["oci"]["identifier"].startswith("ghcr.io/ar9av/obsidian-wiki:")
    # The uvx --with list must cover the [server] extra that `obsidian-wiki mcp` imports.
    withs = {a["value"].split(">=")[0] for a in packages["pypi"]["runtimeArguments"]}
    assert {"fastapi", "mcp"} <= withs
    assert SERVER_JSON["remotes"][0]["url"].endswith("/mcp/")


def test_paas_templates_use_the_image_volume_and_health_check():
    if sys.version_info >= (3, 11):
        import tomllib

        fly = tomllib.loads((ROOT / "deploy" / "fly.toml").read_text(encoding="utf-8"))
        assert fly["build"]["image"].startswith("ghcr.io/ar9av/obsidian-wiki")
        assert fly["mounts"][0]["destination"] == "/vault"
        assert fly["http_service"]["checks"][0]["path"] == "/health"
    railway = json.loads((ROOT / "deploy" / "railway.json").read_text(encoding="utf-8"))
    assert railway["deploy"]["requiredMountPath"] == "/vault"
    assert railway["deploy"]["healthcheckPath"] == "/health"
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "mountPath: /vault" in render and "healthCheckPath: /health" in render
    assert "generateValue: true" in render  # the key is generated, never committed


def test_dockerfile_leaves_port_to_the_platform():
    """PaaS hosts assign PORT; a baked-in WIKI_PORT would override it."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert not re.search(r"^ENV .*WIKI_PORT=", dockerfile, re.M)
    assert "os.environ.get('PORT')" in dockerfile
