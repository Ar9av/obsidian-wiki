"""Tests for per-prompt recall (`recall_brief`, `obsidian-wiki recall`, the hook).

The hook adds context to every turn, so the property that matters is that it
stays silent unless a note clearly matches, and never fails a prompt.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from obsidian_wiki.context_pack import recall_brief

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / ".claude" / "hooks" / "wiki-prompt-recall.sh"


def _note(vault: Path, rel: str, title: str, summary: str, tags: str = "[]") -> None:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntitle: {title}\ntags: {tags}\nsummary: {summary}\n---\n# {title}\n"
        "Body text mentioning variable, rename, help, and everything else.\n",
        encoding="utf-8",
    )


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    _note(root, "concepts/rate-limiting.md", "Rate limiting", "Token bucket rate limiting for APIs.", "[api, backend]")
    _note(root, "skills/pypi-release.md", "PyPI release", "How the package ships to PyPI with hatchling.", "[packaging]")
    _note(root, "entities/env-config.md", "Env config", "Every environment variable the server reads.")
    return root


def test_a_clear_match_is_returned_as_a_linked_summary(vault: Path) -> None:
    brief = recall_brief(vault, "how should we do rate limiting on the api?")
    assert brief.splitlines() == ["- [[concepts/rate-limiting]] — Token bucket rate limiting for APIs."]


def test_generic_prompts_and_single_word_overlaps_abstain(vault: Path) -> None:
    assert recall_brief(vault, "can you help me rename this variable") == ""
    assert recall_brief(vault, "thanks!") == ""
    assert recall_brief(vault, "") == ""


def test_the_brief_respects_its_note_and_character_caps(vault: Path) -> None:
    for index in range(10):
        _note(vault, f"concepts/limits-{index}.md", f"Rate limiting {index}", "Rate limiting notes " + "x" * 300)
    brief = recall_brief(vault, "rate limiting", max_notes=4, max_chars=500)
    assert 1 <= len(brief.splitlines()) <= 4
    assert len(brief) <= 500


def test_cli_hook_mode_reads_the_prompt_from_the_payload(vault: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    payload = json.dumps({"prompt": "release the package to pypi", "session_id": "x"})
    proc = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "recall", "--hook", "--vault", str(vault)],
        input=payload, capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "[[skills/pypi-release]]" in proc.stdout

    garbage = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "recall", "--hook", "--vault", str(vault)],
        input="{not json", capture_output=True, text=True, env=env, timeout=60,
    )
    assert garbage.returncode == 0 and garbage.stdout == ""


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_the_hook_injects_on_a_match_and_is_silent_otherwise(vault: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")
    env = {**os.environ, "HOME": str(tmp_path), "PYTHONPATH": str(REPO),
           "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}"}

    def run(prompt: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(HOOK)], cwd=str(project), env={**env, **extra},
            input=json.dumps({"prompt": prompt}), capture_output=True, text=True, timeout=60,
        )

    hit = run("rate limiting for the api")
    assert hit.returncode == 0
    assert "[[concepts/rate-limiting]]" in hit.stdout
    assert "not instructions" in hit.stdout

    miss = run("rename this variable please")
    assert miss.returncode == 0 and miss.stdout == ""

    off = run("rate limiting for the api", WIKI_PROMPT_RECALL="false")
    assert off.returncode == 0 and off.stdout == ""
