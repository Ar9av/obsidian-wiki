"""Tests for the index subcommand."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from obsidian_wiki.index import build_index, rebuild_index
from obsidian_wiki.lint import _parse_page


def _page(
    vault: Path,
    relpath: str,
    *,
    title: str | None = None,
    category: str | None = None,
    summary: str | None = "Short summary.",
    tags: str | None = "[test]",
    frontmatter_lines: list[str] | None = None,
) -> Path:
    path = vault / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    rel = path.relative_to(vault)
    if category is None:
        category = rel.parts[0] if len(rel.parts) > 1 else "concepts"
    lines = [
        "---",
        f"title: {title or path.stem}",
        f"category: {category}",
    ]
    if tags is not None:
        lines.append(f"tags: {tags}")
    if frontmatter_lines:
        lines.extend(frontmatter_lines)
    lines.extend(
        [
            "sources: [manual]",
            "created: 2026-07-01",
            "updated: 2026-07-01",
        ]
    )
    if summary is not None:
        lines.append(f"summary: {summary}")
    lines.extend(["---", f"# {path.stem}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_index_renders_inline_and_block_list_tags(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    inline = _page(vault, "concepts/inline.md", tags="[ml, architecture]")
    block = _page(
        vault,
        "concepts/block.md",
        tags=None,
        frontmatter_lines=["tags:", "  - ml", "  - architecture"],
    )

    assert _parse_page(inline, vault)["tag_list"] == ["ml", "architecture"]
    assert _parse_page(block, vault)["tag_list"] == ["ml", "architecture"]


def test_index_uses_full_paths_and_frontmatter_titles(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "projects/alpha/shared.md", title="Alpha Shared", category="project")
    _page(vault, "projects/beta/shared.md", title="Beta Shared", category="project")

    text = build_index(vault)

    assert "[[projects/alpha/shared|Alpha Shared]]" in text
    assert "[[projects/beta/shared|Beta Shared]]" in text
    assert text.count("[[shared]]") == 0


def test_index_renders_root_relative_markdown_links(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/friendly-slug.md", title="Friendly Name")

    text = build_index(vault, link_format="markdown")

    assert "[Friendly Name](concepts/friendly-slug.md)" in text
    assert "[[" not in text


def test_index_preserves_noncanonical_category_case(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "AI/guide.md", title="Guide", category="AI")

    text = build_index(vault)

    assert "## AI" in text
    assert "## Ai" not in text


def test_index_renders_block_list_tags(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(
        vault,
        "concepts/block.md",
        tags=None,
        frontmatter_lines=["tags:", "  - ml", "  - architecture"],
    )

    text = build_index(vault)

    assert "[[concepts/block]] — Short summary. ( #ml #architecture)" in text


def _run(
    home: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    if extra_env:
        env.update(extra_env)
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
    assert "- [[concepts/alpha]] — Short summary. ( #test)" in text
    assert "- [[concepts/beta]] — Short summary. ( #ml #architecture)" in text
    assert "- [[projects/proj]]\n" in text
    # Canonical category order, with sorted entries inside each section.
    assert text.index("## Concepts") < text.index("## Entities") < text.index("## Projects")
    assert text.index("[[concepts/alpha]]") < text.index("[[concepts/beta]]")
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
    assert "+- [[entities/tool]]" in proc.stdout
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
    assert "[[concepts/alpha]]" in text
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
    assert "[[concepts/alpha]]" in (vault / "index.md").read_text(encoding="utf-8")


def test_index_cli_link_format_precedence(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", title="Alpha")
    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir(parents=True)
    (config_dir / "config").write_text(
        "OBSIDIAN_LINK_FORMAT=markdown\n",
        encoding="utf-8",
    )

    assert _run(home, "index", str(vault)).returncode == 0
    assert "[Alpha](concepts/alpha.md)" in (vault / "index.md").read_text()

    assert _run(
        home,
        "index",
        str(vault),
        extra_env={"OBSIDIAN_LINK_FORMAT": "wikilink"},
    ).returncode == 0
    assert "[[concepts/alpha|Alpha]]" in (vault / "index.md").read_text()

    assert _run(
        home,
        "index",
        str(vault),
        "--link-format",
        "markdown",
        extra_env={"OBSIDIAN_LINK_FORMAT": "wikilink"},
    ).returncode == 0
    assert "[Alpha](concepts/alpha.md)" in (vault / "index.md").read_text()


def test_index_cli_rejects_invalid_configured_link_format(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")

    proc = _run(
        tmp_path / "home",
        "index",
        str(vault),
        extra_env={"OBSIDIAN_LINK_FORMAT": "invalid"},
    )

    assert proc.returncode == 1
    assert "invalid OBSIDIAN_LINK_FORMAT" in proc.stderr
    assert not (vault / "index.md").exists()
