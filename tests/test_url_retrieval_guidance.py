"""Instruction contracts only; no provider/model execution is claimed."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_concrete_extraction_flow_and_auth_boundary():
    text = (ROOT / 'skills/wiki-ingest/references/url-sources.md').read_text(encoding='utf-8')
    for command in ('defuddle parse <url> --markdown', 'firecrawl scrape', 'scripts/jina_reader.py'):
        assert command in text
    assert 'curl -sf' not in text
    for concept in ('private or intranet', 'stub: true', 'JINA_API_KEY', 'approval'):
        assert concept in text
    assert '${JINA_API_KEY' not in text
    assert 'MCP' not in text

def test_no_mcp_first_or_normalization_framework():
    skill = ROOT / 'skills/wiki-ingest'
    assert not (skill / 'references/retrieval.md').exists()
    assert sorted(p.relative_to(skill).as_posix() for p in skill.rglob('*.py')) == ['scripts/jina_reader.py']
    text = (skill / 'SKILL.md').read_text(encoding='utf-8')
    assert 'defuddle' in text and 'firecrawl' in text
    assert 'references/retrieval.md' not in text

def test_config_does_not_silently_retire_auth():
    config = (ROOT / 'docs/configuration.md').read_text(encoding='utf-8')
    assert 'JINA_API_KEY' in config and 'approval' in config
    assert 'JINA_API_KEY=' in (ROOT / '.env.example').read_text(encoding='utf-8')
