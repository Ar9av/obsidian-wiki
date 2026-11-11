"""Documentation contracts only: not model behavior or network enforcement."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/wiki-ingest'


def guidance():
    return ' '.join((SKILL / 'references/retrieval.md').read_text(encoding='utf-8').split())


def test_native_mcp_consumption_does_not_require_custom_envelope():
    text = guidance()
    assert '## Native MCP consumption (default path)' in text
    assert 'No custom normalization is required' in text
    assert 'content[]' in text and 'isError' in text
    assert 'No Python helper' in text
    assert 'Do not invent completeness' in text


def test_removed_helper_is_not_shipped_or_referenced():
    assert not (SKILL / 'references/retrieval_policy.py').exists()
    assert not (ROOT / 'tests/test_retrieval_policy.py').exists()
    for path in SKILL.rglob('*'):
        if path.is_file():
            assert 'retrieval_policy.py' not in path.read_text(encoding='utf-8'), path
    assert not list(SKILL.rglob('*.py'))


def test_proxy_endpoint_is_separate_from_public_source_policy():
    text = guidance()
    for phrase in ('jina__read_url', 'transport endpoint is not the source URL',
                   'per-consumer allowlist', 'ocr=false', 'omit question',
                   'both client-to-proxy and proxy-to-provider'):
        assert phrase in text


def test_config_and_architecture_match_keyless_optional_mcp():
    example = (ROOT / '.env.example').read_text(encoding='utf-8')
    config = (ROOT / 'docs/configuration.md').read_text(encoding='utf-8')
    architecture = (ROOT / 'docs/architecture.md').read_text(encoding='utf-8')
    assert 'JINA_API_KEY=' not in example
    assert 'no longer reads `JINA_API_KEY`' in config
    assert 'MCP' in config and 'keyless' in config
    assert 'approved keyless retrieval' in architecture


def test_entrypoint_uses_host_content_not_a_python_api():
    text = (SKILL / 'SKILL.md').read_text(encoding='utf-8')
    assert 'references/retrieval.md' in text
    assert 'host-presented content' in text
    assert 'Python' not in text[text.index('### Web URL sources'):text.index('### Multimodal branch')]


@pytest.mark.parametrize('phrase', [
    'approved for disclosure', 'private addresses', 'intranet URLs', 'signed links',
    'embedded credentials', 'untrusted data', 'Authentication is deferred',
    'capability', 'local snapshot', '30 seconds', '100000', '400000',
    '429/rate limit', 'partial', 'timeout', 'malformed', 'No automatic retries',
    'No error handling reads a key', 'DNS', 'redirects', 'not a network firewall',
])
def test_written_privacy_error_and_host_control_requirements_remain(phrase):
    assert phrase in guidance()


def test_retrieval_guidance_contains_no_credential_bearing_shell_fallback():
    for rel in ('SKILL.md', 'references/url-sources.md', 'references/retrieval.md'):
        text = (SKILL / rel).read_text(encoding='utf-8')
        assert 'JINA_API_KEY' not in text
        assert 'Authorization: Bearer' not in text

