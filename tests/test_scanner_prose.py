from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

SCANNER_ENV = "OW_SCANNER_FILE"
SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills"
TARGETS = [
    SKILL_ROOT / "wiki-ingest" / "SKILL.md",
    SKILL_ROOT / "wiki-stage-commit" / "SKILL.md",
]


def load_scanner():
    scanner_path = Path(os.environ[SCANNER_ENV])
    spec = importlib.util.spec_from_file_location("skills_guard", scanner_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(SCANNER_ENV not in os.environ, reason="set OW_SCANNER_FILE to load the scanner explicitly")
def test_complete_stage_artifact_allowed_without_force():
    scanner = load_scanner()
    result = scanner.scan_skill(SKILL_ROOT / 'wiki-stage-commit', source='community')
    assert scanner.should_allow_install(result, force=False)[0] is True


def test_source_authority_and_concurrency_contracts_remain_explicit():
    ingest = TARGETS[0].read_text(encoding='utf-8')
    stage = TARGETS[1].read_text(encoding='utf-8')
    assert 'Only the instructions in this SKILL.md file control your behavior' not in ingest
    for boundary in ('untrusted data', 'Never execute commands', 'Never exfiltrate data',
                     'system', 'developer', 'operator', 'project authorization'):
        assert boundary in ingest
    for guard in ('--expect-staged <staged_revision>', '--expect-live <live_revision>',
                  '--expect-new', 'Do not retry with fresh revisions blindly',
                  'Exit code **9**', 'ask again'):
        assert guard in stage


@pytest.mark.skipif(SCANNER_ENV not in os.environ, reason="set OW_SCANNER_FILE to load the scanner explicitly")
def test_scanner_finds_no_prose_issues_in_target_skills() -> None:
    scanner_path = Path(os.environ[SCANNER_ENV])
    spec = importlib.util.spec_from_file_location("skills_guard", scanner_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    findings: list[tuple[str, str, int, str]] = []
    for skill_path in TARGETS:
        result = module.scan_skill(skill_path, source="community")
        findings.extend(
            (skill_path.name, finding.pattern_id, finding.line, finding.match)
            for finding in result.findings
        )

    assert findings == [], findings
