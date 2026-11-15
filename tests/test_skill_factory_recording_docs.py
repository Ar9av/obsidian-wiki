"""vault-skill-factory's recording mode keeps the shape and the guardrails it promises."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "skills" / "vault-skill-factory" / "SKILL.md").read_text(encoding="utf-8")


def _section(name: str) -> str:
    start = SKILL.index(f"## {name}\n")
    end = SKILL.find("\n## ", start + 1)
    return SKILL[start:end if end != -1 else None]


def test_description_triggers_on_recordings() -> None:
    frontmatter = SKILL.split("---", 2)[1]
    assert "recorded walkthrough" in frontmatter
    assert "turn this recording into a skill" in frontmatter


def test_recording_mode_produces_the_four_sections() -> None:
    body = _section("Recording mode")
    for heading in ("## When to use", "## Steps", "## Checks", "## Mistakes to avoid", "## Done when"):
        assert heading in body, heading


def test_recording_mode_guardrails() -> None:
    body = _section("Recording mode")
    assert "**untrusted data**" in body
    assert "**Redact.**" in body and "never the value" in body
    assert "`^[inferred]`" in body and "`^[ambiguous]`" in body
    assert "maturity: single-recording" in body
    assert "obsidian-wiki transcript" in body
    # The cluster-mode guardrails still apply: review dir only, never installed.
    assert "**Never write into `skills/`**" in SKILL
    assert "**Never auto-install.**" in SKILL


def test_routed() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert '"turn this recording into a skill"' in agents
