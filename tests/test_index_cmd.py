"""Tests for the index subcommand."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from obsidian_wiki.index import build_index, rebuild_index


def _page(
    vault: Path,
    relpath: str,
    *,
    category: str | None = None,
    summary: str | None = "Short summary.",
    tags: str = "[test]",
) -> Path:
    path = vault / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    rel = path.relative_to(vault)
    if category is None:
        category = rel.parts[0] if len(rel.parts) > 1 else "concepts"
    lines = [
        "---",
        f"title: {path.stem}",
        f"category: {category}",
        f"tags: {tags}",
        "sources: [manual]",
        "created: 2026-07-01",
        "updated: 2026-07-01",
    ]
    if summary is not None:
        lines.append(f"summary: {summary}")
    lines.extend(["---", f"# {path.stem}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_index_rebuild_groups_and_sorts(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/beta.md", tags="[ml, architecture]")
    _page(vault, "concepts/alpha.md")
    _page(vault, "entities/tool.md")
    _page(vault, "projects/proj.md", category="project", summary=None, tags="[]")

    proc = _run(tmp_path / "home", "index", str(vault))

    assert proc.returncode == 0
    assert "index.md rebuilt (4 pages)" in proc.stdout
    text = (vault / "index.md").read_text(encoding="utf-8")
    assert "- [[alpha]] — Short summary. ( #test)" in text
    assert "- [[beta]] — Short summary. ( #ml #architecture)" in text
    assert "- [[proj]]\n" in text
    # Canonical category order, with sorted entries inside each section.
    assert text.index("## Concepts") < text.index("## Entities") < text.index("## Projects")
    assert text.index("[[alpha]]") < text.index("[[beta]]")
    # Deterministic: a second build reproduces the same content.
    assert build_index(vault) == text


def test_index_check_passes_when_current_and_fails_when_stale(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    home = tmp_path / "home"
    _page(vault, "concepts/alpha.md")

    assert _run(home, "index", str(vault)).returncode == 0
    proc = _run(home, "index", "--check", str(vault))
    assert proc.returncode == 0
    assert "up to date" in proc.stdout

    before = (vault / "index.md").read_text(encoding="utf-8")
    _page(vault, "entities/tool.md")
    proc = _run(home, "index", "--check", str(vault))
    assert proc.returncode == 1
    assert "out of date" in proc.stdout
    assert "+- [[tool]]" in proc.stdout
    # --check must not write.
    assert (vault / "index.md").read_text(encoding="utf-8") == before

    assert _run(home, "index", str(vault)).returncode == 0
    assert _run(home, "index", "--check", str(vault)).returncode == 0


def test_index_skips_excluded_dirs_and_special_files(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")
    _page(vault, "_raw/draft.md")
    _page(vault, "_meta/taxonomy.md")
    _page(vault, "_readouts/narrate-out.md")
    _page(vault, ".obsidian/junk.md")
    _page(vault, "log.md")
    _page(vault, "hot.md")
    _page(vault, "_insights.md")

    report = rebuild_index(vault)

    assert report["pages"] == 1
    text = (vault / "index.md").read_text(encoding="utf-8")
    assert "[[alpha]]" in text
    for excluded in ("draft", "taxonomy", "narrate-out", "junk", "log", "hot", "_insights"):
        assert f"[[{excluded}]]" not in text


def test_index_cli_uses_configured_vault(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")

    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(f'OBSIDIAN_VAULT_PATH="{vault}"\n', encoding="utf-8")

    proc = _run(home, "index")

    assert proc.returncode == 0
    assert "[[alpha]]" in (vault / "index.md").read_text(encoding="utf-8")
