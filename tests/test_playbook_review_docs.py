"""wiki-playbook-review only ever stages, and stays wired to the commands it calls."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "skills" / "wiki-playbook-review" / "SKILL.md").read_text(encoding="utf-8")


def test_frontmatter_names_the_skill() -> None:
    assert SKILL.startswith("---\nname: wiki-playbook-review\n")


def test_review_stages_and_never_writes_live_pages() -> None:
    assert "obsidian-wiki playbooks --since 7d --json" in SKILL
    assert "_staging/<playbook path>" in SKILL
    assert "**Never write the live page.**" in SKILL
    assert "/wiki-stage-commit" in SKILL


def test_stage_commit_accepts_playbook_revisions_without_the_flag() -> None:
    body = (ROOT / "skills" / "wiki-stage-commit" / "SKILL.md").read_text(encoding="utf-8")
    assert "wiki-playbook-review` always stages" in body


def test_routed_and_documented() -> None:
    assert "`wiki-playbook-review`" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "`wiki-playbook-review`" in (ROOT / "docs" / "skills.md").read_text(encoding="utf-8")
    assert "## Playbook evidence" in (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
