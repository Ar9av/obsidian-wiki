"""Every vault walker and frontmatter reader agrees (#238).

Before obsidian_wiki/vault.py each module had its own walker and regex, and
context-pack/memory ignored .okignore. These pin that they now see the same
vault.
"""

from __future__ import annotations

from pathlib import Path

from obsidian_wiki.context_pack import load_pages
from obsidian_wiki.graph_analysis import iter_pages
from obsidian_wiki.lint import lint_vault
from obsidian_wiki.memory import scan_pages
from obsidian_wiki.trust import iter_trust_pages
from obsidian_wiki.vault import split_frontmatter

PAGE = (
    "---\ntitle: T\ncategory: concepts\ntags: [a]\nsources: []\n"
    "created: 2026-01-01\nupdated: 2026-01-01\nsummary: s\n---\n\nbody\n"
)


def _write(vault: Path, rel: str, text: str = PAGE) -> None:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def test_split_frontmatter_handles_crlf() -> None:
    assert split_frontmatter(PAGE.replace("\n", "\r\n"))[0].startswith("title: T")
    assert split_frontmatter("no frontmatter") == ("", "no frontmatter")


def test_every_walker_honors_okignore_and_hidden_dirs(tmp_path: Path) -> None:
    _write(tmp_path, "concepts/kept.md")
    _write(tmp_path, "_excluded/secret.md")
    _write(tmp_path, ".trash/old.md")
    _write(tmp_path, "venv/lib/readme.md")
    (tmp_path / ".okignore").write_text("_excluded/\n", encoding="utf-8")

    want = ["concepts/kept.md"]
    rel = lambda paths: sorted(p.relative_to(tmp_path).as_posix() for p in paths)  # noqa: E731
    assert rel(iter_pages(tmp_path)) == want
    assert rel(iter_trust_pages(tmp_path)) == want
    assert sorted(p.path for p in load_pages(tmp_path)) == want
    assert sorted(p.path for p in scan_pages(tmp_path)) == want
    assert lint_vault(tmp_path)["stats"]["pages"] == 1
