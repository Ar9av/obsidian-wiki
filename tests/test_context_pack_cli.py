"""Tests for the context-pack CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def run_cli(
    home: Path, *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    if cwd is None:
        # Default to the fake HOME, not the repo: config resolution walks up
        # from cwd looking for a `.env`, and a developer's own .env at the repo
        # root would otherwise override the fixture config.
        home.mkdir(parents=True, exist_ok=True)
        cwd = home
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "auth.md").write_text(
        "# Authentication\n\nUse short-lived access tokens.\n",
        encoding="utf-8",
    )
    return vault


def test_context_pack_uses_configured_vault(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = make_vault(tmp_path)
    config = home / ".obsidian-wiki" / "config"
    config.parent.mkdir(parents=True)
    config.write_text(f'OBSIDIAN_VAULT_PATH="{vault}"\n', encoding="utf-8")

    proc = run_cli(home, "context-pack", "authentication", "--budget", "512")

    assert proc.returncode == 0
    assert "# Agent Context: authentication" in proc.stdout
    assert "auth.md" in proc.stdout


def test_context_pack_prefers_nearest_local_env_vault(tmp_path: Path) -> None:
    home = tmp_path / "home"
    global_vault = tmp_path / "global-vault"
    local_vault = tmp_path / "local-vault"
    global_vault.mkdir()
    local_vault.mkdir()
    (global_vault / "global.md").write_text("# Authentication\n\nGlobal token policy.\n", encoding="utf-8")
    (local_vault / "local.md").write_text("# Authentication\n\nLocal token policy.\n", encoding="utf-8")
    config = home / ".obsidian-wiki" / "config"
    config.parent.mkdir(parents=True)
    config.write_text(f'OBSIDIAN_VAULT_PATH="{global_vault}"\n', encoding="utf-8")
    project = home / "project"
    nested_dir = project / "nested"
    nested_dir.mkdir(parents=True)
    (project / ".env").write_text(f'OBSIDIAN_VAULT_PATH="{local_vault}"\n', encoding="utf-8")

    proc = run_cli(home, "context-pack", "authentication", cwd=nested_dir)

    assert proc.returncode == 0
    assert "local.md" in proc.stdout
    assert "global.md" not in proc.stdout


def test_context_pack_stops_at_empty_nearest_local_vault_config(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    global_vault = tmp_path / "global-vault"
    global_vault.mkdir()
    (global_vault / "global.md").write_text(
        "# Authentication\n\nGlobal token policy.\n",
        encoding="utf-8",
    )
    config = home / ".obsidian-wiki" / "config"
    config.parent.mkdir(parents=True)
    config.write_text(
        f'OBSIDIAN_VAULT_PATH="{global_vault}"\n',
        encoding="utf-8",
    )
    project = home / "project"
    nested_dir = project / "nested"
    nested_dir.mkdir(parents=True)
    (project / ".env").write_text(
        "OBSIDIAN_VAULT_PATH=\n",
        encoding="utf-8",
    )

    proc = run_cli(home, "context-pack", "authentication", cwd=nested_dir)

    assert proc.returncode == 1
    assert "vault not configured" in proc.stderr
    assert "global.md" not in proc.stdout


def test_context_pack_explicit_vault_wins_over_local_and_global_config(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    explicit_vault = tmp_path / "explicit-vault"
    local_vault = tmp_path / "local-vault"
    global_vault = tmp_path / "global-vault"
    for vault, filename, detail in (
        (explicit_vault, "explicit.md", "Explicit token policy."),
        (local_vault, "local.md", "Local token policy."),
        (global_vault, "global.md", "Global token policy."),
    ):
        vault.mkdir()
        (vault / filename).write_text(
            f"# Authentication\n\n{detail}\n",
            encoding="utf-8",
        )
    config = home / ".obsidian-wiki" / "config"
    config.parent.mkdir(parents=True)
    config.write_text(
        f'OBSIDIAN_VAULT_PATH="{global_vault}"\n',
        encoding="utf-8",
    )
    project = home / "project"
    project.mkdir(parents=True)
    (project / ".env").write_text(
        f'OBSIDIAN_VAULT_PATH="{local_vault}"\n',
        encoding="utf-8",
    )

    proc = run_cli(
        home,
        "context-pack",
        "authentication",
        "--vault",
        str(explicit_vault),
        cwd=project,
    )

    assert proc.returncode == 0
    assert "explicit.md" in proc.stdout
    assert "local.md" not in proc.stdout
    assert "global.md" not in proc.stdout


def test_context_pack_empty_explicit_vault_never_falls_through_to_config(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    local_vault = tmp_path / "local-vault"
    global_vault = tmp_path / "global-vault"
    for vault, filename in (
        (local_vault, "local.md"),
        (global_vault, "global.md"),
    ):
        vault.mkdir()
        (vault / filename).write_text(
            "# Authentication\n\nConfigured token policy.\n",
            encoding="utf-8",
        )
    config = home / ".obsidian-wiki" / "config"
    config.parent.mkdir(parents=True)
    config.write_text(
        f'OBSIDIAN_VAULT_PATH="{global_vault}"\n',
        encoding="utf-8",
    )
    project = home / "project"
    project.mkdir(parents=True)
    (project / ".env").write_text(
        f'OBSIDIAN_VAULT_PATH="{local_vault}"\n',
        encoding="utf-8",
    )

    proc = run_cli(
        home,
        "context-pack",
        "authentication",
        "--vault",
        "",
        cwd=project,
    )

    assert proc.returncode == 1
    assert "vault not configured" in proc.stderr
    assert "local.md" not in proc.stdout
    assert "global.md" not in proc.stdout


def test_context_alias_and_explicit_vault_emit_json(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = make_vault(tmp_path)

    proc = run_cli(
        home,
        "context",
        "authentication",
        "--vault",
        str(vault),
        "--json",
        "--pretty",
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["schema_version"] == 1
    assert data["content_trust"] == "untrusted_reference_data"
    assert data["estimated_tokens"] <= data["budget_tokens"]
    assert data["pages"][0]["path"] == "auth.md"


def test_recent_mode_does_not_require_topic(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = make_vault(tmp_path)

    proc = run_cli(home, "context-pack", "--vault", str(vault), "--recent")

    assert proc.returncode == 0
    assert "# Agent Context: Recent Activity" in proc.stdout


def test_topic_is_required_without_recent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = make_vault(tmp_path)

    proc = run_cli(home, "context-pack", "--vault", str(vault))

    assert proc.returncode == 1
    assert "topic is required" in proc.stderr


def test_context_pack_requires_a_configured_vault(tmp_path: Path) -> None:
    proc = run_cli(tmp_path / "home", "context-pack", "authentication")

    assert proc.returncode == 1
    assert "vault not configured" in proc.stderr
