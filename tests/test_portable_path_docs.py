"""Structural doc checks for the portable source key contract (v2).

The contract lives in ``.skills/llm-wiki/SKILL.md``. Only structural facts are
pinned here — that the contract section exists, that the CLI surface it adds is
documented, and that the manifest example is genuinely portable. Wording is not
asserted: prose can be rephrased without breaking the contract.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / ".skills"


def test_skill_files_exist() -> None:
    files = sorted(SKILLS_DIR.rglob("*.md"))
    assert files, "no skill markdown found — wrong path?"
    assert any(path.name == "SKILL.md" for path in files)


def test_llm_wiki_defines_the_contract() -> None:
    body = (SKILLS_DIR / "llm-wiki" / "SKILL.md").read_text(encoding="utf-8")
    assert "Source key contract" in body
    for marker in ("vault-relative", "pseudo-key", "machine-portable"):
        assert marker in body, f"contract is missing the {marker!r} rule"


def test_cli_docs_document_the_new_surface() -> None:
    """AGENTS.md requires docs/ to track new CLI surface."""
    cli = (REPO_ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    assert "--key" in cli, "docs/cli.md does not document cache-update --key"
    assert "manifest.py" in cli and "migrate" in cli, (
        "docs/cli.md does not document scripts/manifest.py migrate"
    )
    assert "--from-root" in cli, "docs/cli.md does not document migrate --from-root"


def test_wiki_status_manifest_example_keys_are_portable() -> None:
    body = (SKILLS_DIR / "wiki-status" / "SKILL.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", body, re.S)
    manifest_blocks = [block for block in blocks if '"sources"' in block]
    assert manifest_blocks, "wiki-status manifest example JSON not found"
    sources = json.loads(manifest_blocks[0])["sources"]
    for key in sources:
        assert not key.startswith("/"), f"manifest example key is absolute: {key}"


def test_project_identity_field_is_consistent() -> None:
    """Project identity is an interface, not prose.

    All four skills that touch the `projects` block must agree on the portable
    field, and none may record the legacy machine-specific path as the identity.
    This guards the drift class where a reader is reverted while its writer is
    not — a wording-agnostic check on field names.
    """
    for skill in ("llm-wiki", "wiki-update", "wiki-status", "wiki-query"):
        body = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
        for field in ("source_repo", "source_cwd_hint"):
            assert field in body, (
                f"{skill} does not reference {field}; the project identity "
                f"interface has drifted across skills"
            )
        for legacy_assignment in ('"source_cwd":', "source_cwd="):
            assert legacy_assignment not in body, (
                f"{skill} records the legacy machine-specific project path "
                f"({legacy_assignment}); use source_repo + source_cwd_hint"
            )
