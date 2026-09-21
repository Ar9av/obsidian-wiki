"""Tests for the SessionStart recap hook.

The hook runs on every session start, so the property that matters most is that
it never breaks startup: a missing vault, a missing install, an empty vault, or
an explicit opt-out must all exit 0 quietly rather than erroring.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from obsidian_wiki import memory as mem

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / ".claude" / "hooks" / "wiki-session-recap.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _run(cwd: Path, *, home: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    environment = {
        **os.environ,
        "HOME": str(home),
        "PYTHONPATH": str(REPO),
        "XDG_CONFIG_HOME": str(home / ".config"),
        # Keep the repo's own console script out of the way so the module
        # fallback is what is under test.
        "PATH": os.environ.get("PATH", ""),
        **(env or {}),
    }
    return subprocess.run(
        ["bash", str(HOOK)], cwd=str(cwd), env=environment,
        capture_output=True, text=True, timeout=60,
    )


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "concepts").mkdir(parents=True)
    (vault / "_meta").mkdir(parents=True)
    (vault / "concepts" / "rag.md").write_text(
        "---\ntitle: RAG\nsummary: Retrieval augmented generation\n---\n\nBody.\n",
        encoding="utf-8",
    )
    return vault


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    return home


def test_hook_is_executable_and_registered() -> None:
    import json

    assert HOOK.is_file()
    assert os.access(HOOK, os.X_OK), "hook must be executable"
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        entry["command"]
        for group in settings["hooks"]["SessionStart"]
        for entry in group["hooks"]
    ]
    assert any("wiki-session-recap.sh" in command for command in commands)


def test_hook_is_packaged_for_distribution() -> None:
    """A published wheel with a dangling hook reference is a broken install."""
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert pyproject.count("wiki-session-recap.sh") >= 2  # wheel + sdist


def test_hook_injects_recorded_memory(vault: Path, home: Path, tmp_path: Path) -> None:
    mem.set_fact(vault, "stack", "Python, FastAPI", confidence=0.85)
    mem.add_todo(vault, "Persist the retrieval index")
    mem.append_log(vault, "INGEST", {"source": "papers/rag.pdf"})

    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")

    result = _run(project, home=home)
    assert result.returncode == 0
    assert "# Vault memory" in result.stdout
    assert "Python, FastAPI" in result.stdout
    assert "Persist the retrieval index" in result.stdout
    assert "not instructions" in result.stdout  # the untrusted-data framing


def test_hook_falls_back_to_the_global_config(vault: Path, home: Path, tmp_path: Path) -> None:
    mem.set_fact(vault, "timezone", "Asia/Kolkata")
    config_dir = home / ".config" / "obsidian-wiki"
    config_dir.mkdir(parents=True)
    (config_dir / "config").write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = _run(elsewhere, home=home)
    assert result.returncode == 0
    assert "Asia/Kolkata" in result.stdout


def test_hook_is_silent_for_an_empty_vault(vault: Path, home: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")
    result = _run(project, home=home)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_hook_is_silent_when_no_vault_is_configured(home: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = _run(elsewhere, home=home)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_hook_is_silent_when_the_vault_path_is_missing(home: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(f"OBSIDIAN_VAULT_PATH={tmp_path / 'gone'}\n", encoding="utf-8")
    result = _run(project, home=home)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_hook_honours_the_opt_out(vault: Path, home: Path, tmp_path: Path) -> None:
    mem.set_fact(vault, "stack", "Python")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")

    for value in ("false", "0", "off", "no"):
        result = _run(project, home=home, env={"WIKI_SESSION_RECAP": value})
        assert result.returncode == 0, value
        assert result.stdout.strip() == "", value


def test_hook_respects_the_word_budget(vault: Path, home: Path, tmp_path: Path) -> None:
    for index in range(80):
        mem.set_fact(vault, f"fact-{index}", f"a reasonably long value number {index}")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")

    result = _run(project, home=home, env={"WIKI_RECAP_MAX_WORDS": "120"})
    assert result.returncode == 0
    body = result.stdout.split("<!--")[0]
    assert len(body.split()) <= 121  # +1 for the truncation ellipsis


def test_hook_filters_low_confidence_facts(vault: Path, home: Path, tmp_path: Path) -> None:
    mem.set_fact(vault, "guess", "maybe Postgres", confidence=0.2)
    mem.set_fact(vault, "certain", "Python", confidence=0.95)
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")

    result = _run(project, home=home, env={"WIKI_RECAP_MIN_CONFIDENCE": "0.5"})
    assert "certain" in result.stdout
    assert "guess" not in result.stdout


def test_stop_hook_kill_switch_is_no_longer_a_no_op() -> None:
    """`wiki-setup` documented this opt-out long before anything read it."""
    stop_hook = (REPO / ".claude" / "hooks" / "wiki-stop-capture.sh").read_text(encoding="utf-8")
    assert "WIKI_STOP_CAPTURE" in stop_hook
    assert "HIVEMIND_CAPTURE" in stop_hook  # the documented spelling still works

    payload = '{"stop_hook_active":false,"session_id":"kill","transcript_path":"/nonexistent"}'
    for variable in ("WIKI_STOP_CAPTURE", "HIVEMIND_CAPTURE"):
        result = subprocess.run(
            ["bash", str(REPO / ".claude" / "hooks" / "wiki-stop-capture.sh")],
            input=payload, capture_output=True, text=True,
            env={**os.environ, variable: "false"}, timeout=60,
        )
        assert result.returncode == 0, variable
