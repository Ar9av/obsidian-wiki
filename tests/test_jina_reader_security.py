"""Offline transport/error contracts; never contact Jina or real DNS."""
import importlib.util
import io
from pathlib import Path
import socket
from urllib.error import HTTPError, URLError
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/wiki-ingest/scripts/jina_reader.py'
LEGACY = Path(__file__).resolve().parents[1] / 'scripts/jina_reader.py'
KEY = 'DUMMY_AUTH_MARKER_123'

def load():
    spec = importlib.util.spec_from_file_location('reader_security', SCRIPT if SCRIPT.exists() else LEGACY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class Response:
    def __init__(self, body=b'markdown', failure=None):
        self.body, self.failure, self.closed = body, failure, False
    def read(self, size):
        if self.failure:
            raise self.failure
        return self.body[:size]
    def close(self):
        self.closed = True

@pytest.fixture
def transport(monkeypatch):
    m = load()
    monkeypatch.delenv('JINA_API_KEY', raising=False)
    monkeypatch.setattr(m.socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, 1, 6, '', ('93.184.216.34', 443))])
    calls=[]
    response=Response()
    class Opener:
        def open(self, request, timeout):
            calls.append((request,timeout))
            return response
    monkeypatch.setattr(m, '_opener', lambda: Opener())
    return m,response,calls

@pytest.mark.parametrize('key',[None,'',KEY])
def test_auth_selection(transport,monkeypatch,capsys,key):
    m,r,calls=transport
    if key is not None: monkeypatch.setenv('JINA_API_KEY',key)
    assert m.main(['https://example.com/page?a=1&b=2'])==0
    req,t=calls[0]
    assert req.full_url=='https://r.jina.ai/https://example.com/page?a=1&b=2'
    assert req.get_header('Authorization') == ('Bearer '+key if key else None)
    assert r.closed
    out=capsys.readouterr()
    assert KEY not in out.out+out.err

@pytest.mark.parametrize('args',[[],['--unexpected',KEY],['https://example.com','--timeout','nan'],['https://example.com','--timeout','inf'],['https://example.com','--max-bytes','999999999']])
def test_invalid_arguments_no_traceback(transport,capsys,args):
    m,r,c=transport
    assert m.main(args)==2
    out=capsys.readouterr()
    assert out.err.strip() and 'Traceback' not in out.err and KEY not in out.out+out.err
    assert not c

@pytest.mark.parametrize('url',['https://example.com:bad/','https://[bad/','https://singlelabel/a','https://user:pass@example.com/','https://example.com/#frag','https://localhost/','https://127.0.0.1/'])
def test_url_rejection(transport,capsys,url):
    m,r,c=transport
    assert m.main([url])==3
    assert not c
    out=capsys.readouterr()
    assert out.err.strip() and url not in out.err

@pytest.mark.parametrize('key',['bad\nheader','space key','ékey'])
def test_invalid_key_does_not_fallback(transport,monkeypatch,capsys,key):
    m,r,c=transport
    monkeypatch.setenv('JINA_API_KEY',key)
    assert m.main(['https://example.com'])==4
    assert not c
    assert key not in capsys.readouterr().err

@pytest.mark.parametrize('failure',[OSError(KEY),TimeoutError(KEY),URLError(KEY)])
def test_read_failure_closed_and_nonrevealing(transport,capsys,failure):
    m,r,c=transport
    r.failure=failure
    assert m.main(['https://example.com'])==5
    assert r.closed
    out=capsys.readouterr()
    assert out.out=='' and KEY not in out.err and out.err.strip()

@pytest.mark.parametrize('code',[301,302,307,308,401,403,429,500])
def test_http_errors_closed_and_nonrevealing(transport,monkeypatch,capsys,code):
    m,r,c=transport
    body=io.BytesIO(KEY.encode())
    err=HTTPError('https://example.com/'+KEY,code,KEY,{},body)
    class Opener:
        def open(self,*a,**k): raise err
    monkeypatch.setattr(m,'_opener',lambda:Opener())
    assert m.main(['https://example.com'])==6
    assert body.closed
    out=capsys.readouterr()
    assert out.out=='' and KEY not in out.err and out.err.strip()

@pytest.mark.parametrize('body,code',[(b'',8),(b'\xff',7),(b'x'*1048577,9),(KEY.encode(),6)])
def test_response_failures_never_emit_partial(transport,monkeypatch,capsys,body,code):
    m,r,c=transport
    monkeypatch.setenv('JINA_API_KEY',KEY)
    r.body=body
    assert m.main(['https://example.com'])==code
    out=capsys.readouterr()
    assert out.out=='' and KEY not in out.err and r.closed

def test_redirect_handler_refuses_without_sensitive_exception(transport):
    m,r,c=transport
    with pytest.raises(Exception) as error:
        m._NoRedirect().redirect_request(None,None,302,KEY,{},'https://example.com/'+KEY)
    assert KEY not in str(error.value)

def test_public_alternate_port_preserved(transport):
    m, response, calls = transport
    assert m.main(['https://example.com:8443/page']) == 0
    assert calls[0][0].full_url == 'https://r.jina.ai/https://example.com:8443/page'


def test_mixed_dns_answer_rejected(transport,monkeypatch):
    m,r,c=transport
    monkeypatch.setattr(m.socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,1,6,'',('93.184.216.34',443)),(socket.AF_INET,1,6,'',('10.0.0.1',443))])
    assert m.main(['https://example.com'])==3
    assert not c
