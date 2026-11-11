from __future__ import annotations

import json
from pathlib import Path

import pytest

import obsidian_wiki.cli as cli
from obsidian_wiki import update_check


@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("2026.11.4", "2026.11.3", True),
        ("2026.11.4", "2026.11.4.dev4+gfc5e714", True),  # release beats its own dev build
        ("2026.11.3", "2026.11.4.dev4+gfc5e714", False),  # dev build ahead of last release
        ("2026.11.4", "2026.11.4", False),
        ("2026.12.0", "2026.11.10", True),  # numeric, not string, comparison
        ("", "2026.11.4", False),
    ],
)
def test_is_newer(latest: str, current: str, expected: bool) -> None:
    assert update_check.is_newer(latest, current) is expected


def test_latest_version_caches_for_a_day_and_survives_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "update-check.json"
    calls = []

    def fetch() -> str:
        calls.append(1)
        return "2026.12.1"

    monkeypatch.setattr(update_check, "_fetch_latest", fetch)
    assert update_check.latest_version(cache, now=1000.0) == "2026.12.1"
    assert update_check.latest_version(cache, now=1000.0 + 3600) == "2026.12.1"
    assert len(calls) == 1  # second call served from cache

    def offline() -> str:
        raise OSError("no network")

    monkeypatch.setattr(update_check, "_fetch_latest", offline)
    later = 1000.0 + update_check.CHECK_INTERVAL + 1
    assert update_check.latest_version(cache, now=later) == "2026.12.1"  # keeps last known
    assert json.loads(cache.read_text())["checked_at"] == later  # attempt recorded, no retry storm


def test_notice_respects_opt_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(update_check, "_fetch_latest", lambda: "2099.1.1")
    cache = tmp_path / "c.json"
    assert "2099.1.1" in update_check.notice("2026.11.3", cache)
    monkeypatch.setenv("OBSIDIAN_WIKI_NO_UPDATE_CHECK", "1")
    assert update_check.notice("2026.11.3", cache) == ""


def _skill(root: Path, name: str) -> None:
    (root / name).mkdir(parents=True)
    (root / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")


def test_upgrade_refreshes_only_agents_setup_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    src = tmp_path / "bundled"
    _skill(src, "wiki-old")
    _skill(src, "wiki-new")  # shipped in the upgrade
    home = tmp_path / "home"
    claude = home / ".claude" / "skills"
    claude.mkdir(parents=True)
    (claude / "wiki-old").symlink_to(src / "wiki-old", target_is_directory=True)
    (claude / "my-own-skill").mkdir()  # user's, must survive
    codex = home / ".codex" / "skills"
    codex.mkdir(parents=True)  # exists but never set up: must stay empty

    config = tmp_path / "config"
    config.write_text('OBSIDIAN_VAULT_PATH="/v"\nOBSIDIAN_WIKI_VERSION="2026.11.2"\nEXTRA="keep"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "skills_dir", lambda: src)
    monkeypatch.setattr(cli, "HOME", home)
    monkeypatch.setattr(cli, "GLOBAL_CONFIG", config)
    monkeypatch.setattr(cli, "GLOBAL_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cli, "__version__", "2026.11.3")
    monkeypatch.setattr(cli, "_SYMLINK_FALLBACK", False)

    cli._check_stale()

    assert (claude / "wiki-new").is_symlink()
    assert (claude / "my-own-skill").is_dir()
    assert list(codex.iterdir()) == []
    text = config.read_text()
    assert 'OBSIDIAN_WIKI_VERSION="2026.11.3"' in text and 'EXTRA="keep"' in text
    out = capsys.readouterr()
    assert out.out == ""  # stdout stays clean for --json callers
    assert "refreshed skills in 1 agent dir(s)" in out.err

