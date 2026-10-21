"""A new vault should look organised the first time it is opened in Obsidian."""

from __future__ import annotations

import json
from pathlib import Path

from obsidian_wiki.cli import CATEGORY_COLORS, FOLDER_COLORS_SNIPPET, scaffold_vault


def test_new_vault_gets_colored_folders_and_a_clean_graph(tmp_path: Path) -> None:
    vault = tmp_path / "brain"
    scaffold_vault(vault)
    obsidian = vault / ".obsidian"

    appearance = json.loads((obsidian / "appearance.json").read_text(encoding="utf-8"))
    assert FOLDER_COLORS_SNIPPET in appearance["enabledCssSnippets"]
    css = (obsidian / "snippets" / f"{FOLDER_COLORS_SNIPPET}.css").read_text(encoding="utf-8")
    for name, color in CATEGORY_COLORS.items():
        assert f'data-path^="{name}"] {{ color: {color}; }}' in css

    graph = json.loads((obsidian / "graph.json").read_text(encoding="utf-8"))
    assert {group["query"] for group in graph["colorGroups"]} == {f"path:{n}" for n in CATEGORY_COLORS}
    for folder in ("_raw", "_archives", "_staging", "_meta"):
        assert f"-path:{folder}" in graph["search"]


def test_existing_obsidian_settings_are_never_overwritten(tmp_path: Path) -> None:
    vault = tmp_path / "brain"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "graph.json").write_text('{"mine": true}\n', encoding="utf-8")
    (vault / ".obsidian" / "appearance.json").write_text('{"theme": "moonstone"}\n', encoding="utf-8")
    scaffold_vault(vault)
    assert (vault / ".obsidian" / "graph.json").read_text(encoding="utf-8") == '{"mine": true}\n'
    assert (vault / ".obsidian" / "appearance.json").read_text(encoding="utf-8") == '{"theme": "moonstone"}\n'
