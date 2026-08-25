"""`setup` must not destroy user-added config keys when it re-writes the file."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _setup(home: Path, vault: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("XDG_CONFIG_HOME", None)
    # Pin the import to this checkout — a separately installed obsidian_wiki
    # would otherwise shadow it depending on the working directory.
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "setup", "--vault", str(vault)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(home),
    )


def _config_dir(home: Path) -> Path:
    legacy = home / ".obsidian-wiki"
    return legacy if legacy.is_dir() else home / ".config" / "obsidian-wiki"


def _values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def test_rerunning_setup_keeps_user_added_keys(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config_dir = home / ".config" / "obsidian-wiki"
    config_dir.mkdir(parents=True)
    vault = tmp_path / "vault"
    vault.mkdir()
    config = config_dir / "config"
    config.write_text(
        "# my notes config\n"
        'OBSIDIAN_VAULT_PATH="/old/path"\n'
        'OBSIDIAN_LINK_FORMAT="markdown"\n'
        'QMD_WIKI_COLLECTION="mybrain"\n'
        'WIKI_SKIP_PROJECTS="secret-thing"\n',
        encoding="utf-8",
    )

    proc = _setup(home, vault)
    assert proc.returncode == 0, proc.stderr

    values = _values(config)
    # User keys survive.
    assert values["OBSIDIAN_LINK_FORMAT"] == "markdown"
    assert values["QMD_WIKI_COLLECTION"] == "mybrain"
    assert values["WIKI_SKIP_PROJECTS"] == "secret-thing"
    # Managed key is updated, not duplicated.
    assert values["OBSIDIAN_VAULT_PATH"] == str(vault)
    body = config.read_text()
    assert body.count("OBSIDIAN_VAULT_PATH=") == 1
    # Comments are kept.
    assert "# my notes config" in body


def test_setup_on_legacy_config_preserves_keys(tmp_path: Path) -> None:
    """The same guarantee must hold for the pre-XDG config location."""
    home = tmp_path / "home"
    legacy = home / ".obsidian-wiki"
    legacy.mkdir(parents=True)
    vault = tmp_path / "vault"
    vault.mkdir()
    config = legacy / "config"
    config.write_text('OBSIDIAN_VAULT_PATH="/old"\nOBSIDIAN_LINK_FORMAT="markdown"\n', encoding="utf-8")

    proc = _setup(home, vault)
    assert proc.returncode == 0, proc.stderr

    assert _config_dir(home) == legacy
    values = _values(config)
    assert values["OBSIDIAN_LINK_FORMAT"] == "markdown"
    assert values["OBSIDIAN_VAULT_PATH"] == str(vault)
    assert (legacy / "WRITING.md").exists()


def test_setup_writes_managed_keys_on_a_fresh_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()

    proc = _setup(home, vault)
    assert proc.returncode == 0, proc.stderr

    values = _values(_config_dir(home) / "config")
    assert values["OBSIDIAN_VAULT_PATH"] == str(vault)
    assert values["OBSIDIAN_WIKI_REPO"]
    assert values["OBSIDIAN_WIKI_VERSION"]


def test_setup_creates_global_writing_profile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()

    proc = _setup(home, vault)
    assert proc.returncode == 0, proc.stderr

    profile = _config_dir(home) / "WRITING.md"
    template = REPO_ROOT / ".skills" / "llm-wiki" / "references" / "WRITING.md"
    assert profile.read_text() == template.read_text()


def test_setup_preserves_existing_writing_profile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config_dir = home / ".config" / "obsidian-wiki"
    config_dir.mkdir(parents=True)
    profile = config_dir / "WRITING.md"
    profile.write_text("# My custom profile\n\nUse concise Traditional Chinese.\n")
    vault = tmp_path / "vault"
    vault.mkdir()

    proc = _setup(home, vault)
    assert proc.returncode == 0, proc.stderr
    assert profile.read_text() == "# My custom profile\n\nUse concise Traditional Chinese.\n"


def test_setup_collapses_duplicate_managed_keys(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config_dir = home / ".config" / "obsidian-wiki"
    config_dir.mkdir(parents=True)
    vault = tmp_path / "vault"
    vault.mkdir()
    config = config_dir / "config"
    config.write_text(
        'OBSIDIAN_VAULT_PATH="/one"\nOBSIDIAN_LINK_FORMAT="markdown"\nOBSIDIAN_VAULT_PATH="/two"\n',
        encoding="utf-8",
    )

    proc = _setup(home, vault)
    assert proc.returncode == 0, proc.stderr

    body = config.read_text()
    assert body.count("OBSIDIAN_VAULT_PATH=") == 1
    assert _values(config)["OBSIDIAN_VAULT_PATH"] == str(vault)
    assert _values(config)["OBSIDIAN_LINK_FORMAT"] == "markdown"
