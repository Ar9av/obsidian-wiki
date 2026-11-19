"""Per-client rate limiting and failed-auth lockout for the memory server.

Plain ASGI middleware, stdlib only, state in memory: one process serves one
vault, so there is nothing to share between workers, and a restart forgetting
the counters is fine.

The lockout counts **401 responses to a presented credential**, not key
comparisons, so it covers every way a secret is checked — bearer keys on `/v1`
and `/mcp`, OAuth access tokens, and the key typed into the OAuth consent page
— without each of them having to report back. A 401 to a request that carried
no credential at all is not a guess: MCP clients send exactly that to discover
OAuth, so it isn't counted. Once a client is locked out it gets 429 without its credentials
being looked at, so a correct guess during the lockout tells it nothing.

The client is `scope["client"]`. Behind a reverse proxy that is the proxy, so
the server passes `WIKI_TRUSTED_PROXIES` to uvicorn, which rewrites the client
from `X-Forwarded-For` for trusted peers only.
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from typing import Callable, Deque, Dict, Iterable

#: Never limited: container health checks poll it, and it reveals nothing.
DEFAULT_EXEMPT = ("/health",)
_PRUNE_AT = 10_000
#: A handler that checks a secret outside the Authorization header (a login form)
#: sets this on its 401 so it counts; the Guard removes it before it leaves.
FAILED_HEADER = b"x-wiki-auth-failed"


class Guard:
    def __init__(
        self,
        app,
        *,
        rate_limit: int = 600,
        lockout_limit: int = 10,
        lockout_seconds: int = 300,
        exempt: Iterable[str] = DEFAULT_EXEMPT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.rate_limit = max(0, rate_limit)  # requests per client per minute; 0 = off
        self.lockout_limit = max(0, lockout_limit)  # 401s per window before lockout; 0 = off
        self.lockout_seconds = max(1, lockout_seconds)
        self.exempt = frozenset(exempt)
        self.clock = clock
        self._hits: Dict[str, Deque[float]] = {}
        self._fails: Dict[str, Deque[float]] = {}
        self._locked_until: Dict[str, float] = {}

    # --- bookkeeping -------------------------------------------------------

    @staticmethod
    def _trim(events: Deque[float], horizon: float) -> None:
        while events and events[0] <= horizon:
            events.popleft()

    def _prune(self, now: float) -> None:
        """Drop idle clients so a scan from many addresses can't grow memory forever."""
        for table, window in ((self._hits, 60.0), (self._fails, float(self.lockout_seconds))):
            if len(table) > _PRUNE_AT:
                for ip in [ip for ip, ev in table.items() if not ev or ev[-1] <= now - window]:
                    del table[ip]
        if len(self._locked_until) > _PRUNE_AT:
            for ip in [ip for ip, until in self._locked_until.items() if until <= now]:
                del self._locked_until[ip]

    def retry_after(self, ip: str, now: float) -> int:
        """Seconds the client must wait, or 0 if the request may proceed (and is counted)."""
        until = self._locked_until.get(ip, 0.0)
        if until > now:
            return math.ceil(until - now)
        if self.rate_limit:
            hits = self._hits.setdefault(ip, deque())
            self._trim(hits, now - 60.0)
            if len(hits) >= self.rate_limit:
                return max(1, math.ceil(hits[0] + 60.0 - now))
            hits.append(now)
        return 0

    def record_failure(self, ip: str, now: float) -> None:
        if not self.lockout_limit:
            return
        fails = self._fails.setdefault(ip, deque())
        self._trim(fails, now - self.lockout_seconds)
        fails.append(now)
        if len(fails) >= self.lockout_limit:
            self._locked_until[ip] = now + self.lockout_seconds
            fails.clear()

    # --- ASGI --------------------------------------------------------------

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in self.exempt:
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        now = self.clock()
        if len(self._hits) > _PRUNE_AT or len(self._fails) > _PRUNE_AT:
            self._prune(now)

        wait = self.retry_after(ip, now)
        if wait:
            locked = self._locked_until.get(ip, 0.0) > now
            detail = (
                "too many failed authentication attempts; try again later"
                if locked else "rate limit exceeded; slow down"
            )
            body = json.dumps({"detail": detail}).encode()
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"retry-after", str(wait).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        presented = any(name == b"authorization" for name, _ in scope.get("headers", ()))

        async def observe(message):
            if message["type"] == "http.response.start" and message["status"] == 401:
                headers = list(message.get("headers", ()))
                marked = any(name.lower() == FAILED_HEADER for name, _ in headers)
                if presented or marked:
                    self.record_failure(ip, self.clock())
                if marked:
                    message = {**message, "headers": [h for h in headers if h[0].lower() != FAILED_HEADER]}
            await send(message)

        await self.app(scope, receive, observe)
