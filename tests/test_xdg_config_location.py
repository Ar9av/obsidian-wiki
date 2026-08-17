"""Global config directory resolution: XDG-first with legacy fallback."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    # Pin the import to this checkout — a separately installed obsidian_wiki
    # would otherwise shadow it depending on the working directory.
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env


def _resolve(home: Path, xdg_config_home: str | None = None) -> Path:
    """Resolve GLOBAL_CONFIG_DIR in a subprocess with the given HOME/XDG env."""
    env = _env(home)
    if xdg_config_home is None:
        env.pop("XDG_CONFIG_HOME", None)
    else:
        env["XDG_CONFIG_HOME"] = xdg_config_home
    proc = subprocess.run(
        [sys.executable, "-c", "from obsidian_wiki.cli import GLOBAL_CONFIG_DIR; print(GLOBAL_CONFIG_DIR)"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return Path(proc.stdout.strip())


def test_fresh_install_uses_xdg_default(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    assert _resolve(home) == home / ".config" / "obsidian-wiki"


def test_xdg_config_home_is_honored(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    xdg = tmp_path / "xdg"

    assert _resolve(home, str(xdg)) == xdg / "obsidian-wiki"


def test_existing_legacy_dir_keeps_working(tmp_path: Path) -> None:
    """An install that predates the XDG move must not be stranded."""
    home = tmp_path / "home"
    legacy = home / ".obsidian-wiki"
    legacy.mkdir(parents=True)
    (legacy / "config").write_text('OBSIDIAN_VAULT_PATH="/tmp/vault"\n', encoding="utf-8")

    assert _resolve(home) == legacy


def test_xdg_dir_wins_once_it_exists(tmp_path: Path) -> None:
    """After migrating, the XDG path takes over even if the legacy dir lingers."""
    home = tmp_path / "home"
    legacy = home / ".obsidian-wiki"
    legacy.mkdir(parents=True)
    xdg = home / ".config" / "obsidian-wiki"
    xdg.mkdir(parents=True)

    assert _resolve(home) == xdg


def test_empty_xdg_config_home_falls_back_to_default(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    assert _resolve(home, "") == home / ".config" / "obsidian-wiki"


def test_legacy_config_is_still_read_end_to_end(tmp_path: Path) -> None:
    """`info` must report the legacy config when that is the active location."""
    home = tmp_path / "home"
    legacy = home / ".obsidian-wiki"
    legacy.mkdir(parents=True)
    vault = tmp_path / "vault"
    vault.mkdir()
    (legacy / "config").write_text(f'OBSIDIAN_VAULT_PATH="{vault}"\n', encoding="utf-8")

    env = _env(home)
    env.pop("XDG_CONFIG_HOME", None)
    proc = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "info"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode == 0
    assert str(legacy / "config") in proc.stdout
    assert "(not written yet)" not in proc.stdout
