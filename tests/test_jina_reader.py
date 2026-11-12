import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills' / 'wiki-ingest' / 'scripts' / 'jina_reader.py'


def load_module():
    spec = importlib.util.spec_from_file_location('jina_reader', SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DummyResponse:
    def __init__(self, body=b'hello\n'):
        self.body = body
        self.closed = False
        self.read_args = []
    def read(self, n=-1):
        self.read_args.append(n)
        return self.body
    def close(self):
        self.closed = True


class DummyOpener:
    def __init__(self, response=None, exc=None):
        self.response = response or DummyResponse()
        self.exc = exc
        self.requests = []
    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        if self.exc:
            raise self.exc
        return self.response


@pytest.mark.parametrize('url', [
    'https://example.com/article',
    'http://example.com/article?x=1',
])
def test_fetch_keyless_success_and_request_shape(monkeypatch, url):
    mod = load_module()
    response = DummyResponse(b'hello world\n')
    opener = DummyOpener(response=response)
    monkeypatch.setattr(mod, '_opener', lambda: opener)
    monkeypatch.setattr(mod.socket, 'getaddrinfo', lambda *args, **kwargs: [(socket.AF_INET, None, None, None, ('93.184.216.34', 0))])
    result = mod.fetch(url, key=None, timeout=1, max_bytes=100)
    assert result.text == 'hello world\n'
    assert response.closed is True
    request, timeout = opener.requests[0]
    assert request.full_url == 'https://r.jina.ai/' + url
    assert request.headers['X-return-format'] == 'markdown'
    assert 'Authorization' not in request.headers
    assert timeout == 1


def test_fetch_with_key_adds_auth_and_never_echoes(monkeypatch):
    mod = load_module()
    opener = DummyOpener(response=DummyResponse(b'DUMMY_SECRET'))
    monkeypatch.setattr(mod, '_opener', lambda: opener)
    monkeypatch.setattr(mod.socket, 'getaddrinfo', lambda *args, **kwargs: [(socket.AF_INET, None, None, None, ('93.184.216.34', 0))])
    with pytest.raises(mod.JinaReaderHTTPError):
        mod.fetch('https://example.com/page', key='DUMMY_SECRET')
    request, _ = opener.requests[0]
    assert request.headers['Authorization'] == 'Bearer DUMMY_SECRET'


def test_rejects_private_dns_answers(monkeypatch):
    mod = load_module()
    monkeypatch.setattr(mod.socket, 'getaddrinfo', lambda *args, **kwargs: [(socket.AF_INET, None, None, None, ('127.0.0.1', 0))])
    with pytest.raises(mod.JinaReaderURLError):
        mod.fetch('https://example.com/page', key=None)


@pytest.mark.parametrize('bad', ['https://user@example.com', 'https://example.com/#frag', 'https://localhost/test'])
def test_validate_url_rejects_bad_inputs(bad):
    mod = load_module()
    with pytest.raises(mod.JinaReaderURLError):
        mod._validate_url(bad)


def test_main_confidentiality_on_invalid_url(tmp_path):
    env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT') if k in os.environ}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), TMPDIR=str(tmp_path), TEMP=str(tmp_path), TMP=str(tmp_path))
    env['JINA_API_KEY'] = 'SHOULD_NOT_LEAK'
    proc = subprocess.run([sys.executable, str(SCRIPT), 'https://localhost/test'], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert 'SHOULD_NOT_LEAK' not in proc.stdout + proc.stderr
    assert 'invalid' not in proc.stderr.lower() or proc.stderr.strip() == ''
