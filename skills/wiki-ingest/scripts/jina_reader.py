"""Bounded, fixed-origin Jina Reader transport; stdlib only, Python 3.9+.

Only this process reads JINA_API_KEY. Never pass credentials as CLI arguments.
Local URL checks do not certify the provider's downstream network/privacy policy.
"""
import argparse
import ipaddress
import math
import os
import socket
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

MAX_DEFAULT_BYTES = 1048576
DEFAULT_TIMEOUT = 20.0

class JinaReaderError(Exception):
    code = 5
class JinaReaderArgumentError(JinaReaderError):
    code = 2
class JinaReaderURLError(JinaReaderError):
    code = 3
class JinaReaderKeyError(JinaReaderError):
    code = 4
class JinaReaderHTTPError(JinaReaderError):
    code = 6
class JinaReaderDecodeError(JinaReaderError):
    code = 7
class JinaReaderEmptyError(JinaReaderError):
    code = 8
class JinaReaderTruncatedError(JinaReaderError):
    code = 9

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        raise HTTPError(req.full_url if req else '', code, 'redirect refused', hdrs, fp)

class FetchResult:
    def __init__(self, text):
        self.text = text
        self.truncated = False

def _validate_key(key):
    if not key:
        return None
    if len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise JinaReaderKeyError()
    return key

def _validate_url(url):
    if not url or len(url) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in url) or '\\' in url:
        raise JinaReaderURLError()
    try:
        p = urlsplit(url)
        host = p.hostname or ''
        port = p.port
        if p.scheme not in ('https', 'http') or not host or '@' in p.netloc or p.fragment:
            raise ValueError()
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
        normalized = host.lower().rstrip('.')
        if '%' in host or '.' not in normalized and ':' not in normalized:
            raise ValueError()
        if normalized.endswith(('.localhost', '.local', '.internal', '.test', '.invalid')):
            raise ValueError()
        try:
            address = ipaddress.ip_address(normalized)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError()
        return urlunsplit((p.scheme, p.netloc, p.path or '/', p.query, ''))
    except ValueError:
        raise JinaReaderURLError() from None

def _resolve_public_host(host):
    try:
        answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        if not answers or any(not ipaddress.ip_address(a[4][0]).is_global for a in answers):
            raise JinaReaderURLError()
    except (OSError, ValueError):
        raise JinaReaderURLError() from None

def _opener():
    return build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())

def fetch(url, *, timeout=DEFAULT_TIMEOUT, max_bytes=MAX_DEFAULT_BYTES, key=None):
    if not math.isfinite(timeout) or not 0 < timeout <= 30 or not 0 < max_bytes <= MAX_DEFAULT_BYTES:
        raise JinaReaderArgumentError()
    key = _validate_key(os.environ.get('JINA_API_KEY') if key is None else key)
    url = _validate_url(url)
    _resolve_public_host(urlsplit(url).hostname)
    headers = {'X-Return-Format': 'markdown', 'Accept-Encoding': 'identity'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    request = Request('https://r.jina.ai/' + url, headers=headers, method='GET')
    response = None
    try:
        response = _opener().open(request, timeout=timeout)
        raw = response.read(max_bytes + 1)
    except HTTPError as error:
        error.close()
        raise JinaReaderHTTPError() from None
    except (URLError, OSError, ValueError):
        raise JinaReaderError() from None
    finally:
        if response is not None:
            response.close()
    if len(raw) > max_bytes:
        raise JinaReaderTruncatedError()
    try:
        text = raw.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        raise JinaReaderDecodeError() from None
    if key and key in text:
        raise JinaReaderHTTPError()
    if not text.strip():
        raise JinaReaderEmptyError()
    return FetchResult(text)

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise JinaReaderArgumentError()

ERRORS = {2:'invalid arguments', 3:'URL rejected or unavailable', 4:'invalid credential configuration',
          5:'network request failed', 6:'HTTP request refused, limited, or unsafe response',
          7:'response is not UTF-8 text', 8:'empty response', 9:'response exceeds byte limit'}

def main(argv=None):
    parser = _Parser(prog='jina_reader')
    parser.add_argument('url')
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument('--max-bytes', type=int, default=MAX_DEFAULT_BYTES)
    try:
        args = parser.parse_args(argv)
        result = fetch(args.url, timeout=args.timeout, max_bytes=args.max_bytes)
    except JinaReaderError as error:
        print('jina_reader: ' + ERRORS[error.code], file=sys.stderr)
        return error.code
    try:
        sys.stdout.write(result.text)
        if not result.text.endswith('\n'):
            sys.stdout.write('\n')
    except (OSError, UnicodeError):
        print('jina_reader: output failed', file=sys.stderr)
        return 5
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
