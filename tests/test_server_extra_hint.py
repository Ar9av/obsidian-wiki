import sys

from obsidian_wiki import cli


def test_hint_targets_the_running_install(monkeypatch):
    monkeypatch.setattr(sys, "prefix", "/home/u/.local/pipx/venvs/obsidian-wiki")
    assert cli._server_extra_hint().startswith("pipx install --force")
    monkeypatch.setattr(sys, "prefix", "/home/u/.local/share/uv/tools/obsidian-wiki")
    assert cli._server_extra_hint().startswith("uv tool install --force")
    monkeypatch.setattr(sys, "prefix", "/some/venv")
    assert cli._server_extra_hint().startswith(f"{sys.executable} -m pip install")
