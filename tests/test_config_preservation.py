from __future__ import annotations

from pathlib import Path

import obsidian_wiki.cli as cli


def test_write_config_preserves_existing_custom_values(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / ".obsidian-wiki"
    config = config_dir / "config"
    config_dir.mkdir()
    config.write_text(
        'OBSIDIAN_EXTERNAL_FILE_MODE="link"\n'
        'OBSIDIAN_ALLOWED_LIFECYCLES="active,reviewed"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "GLOBAL_CONFIG_DIR", config_dir)
    monkeypatch.setattr(cli, "GLOBAL_CONFIG", config)

    cli.write_config(str(tmp_path / "vault"))

    written = config.read_text(encoding="utf-8")
    assert 'OBSIDIAN_VAULT_PATH="' in written
    assert 'OBSIDIAN_WIKI_REPO="' in written
    assert 'OBSIDIAN_WIKI_VERSION="' in written
    assert 'OBSIDIAN_EXTERNAL_FILE_MODE="link"' in written
    assert 'OBSIDIAN_ALLOWED_LIFECYCLES="active,reviewed"' in written
