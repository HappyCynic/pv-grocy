# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Bearer token -> caller (ADR-0002).

Tokens are configured as SHA-256 hashes. The presented token is hashed and compared in
constant time against every configured hash, so lookup time does not depend on which (if
any) hash matched.
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
from dataclasses import dataclass, field

from starlette.types import ASGIApp, Receive, Scope, Send

from .config import MAX_WRITES_PER_HOUR, Access, Config


@dataclass(frozen=True)
class Caller:
    token_label: str
    access: Access = Access.READ
    max_writes_per_hour: int = MAX_WRITES_PER_HOUR
    # Keys the per-token write limit; the configured hash, so never shown in repr or logs.
    token_key: str = field(default="", repr=False)


_current: contextvars.ContextVar[Caller | None] = contextvars.ContextVar(
    "pv_grocy_caller", default=None
)


def current_caller() -> Caller:
    caller = _current.get()
    if caller is None:
        # Only reachable if a tool is invoked outside the authenticated HTTP path.
        raise PermissionError("no authenticated caller for this request")
    return caller


def bind_caller(caller: Caller) -> contextvars.Token[Caller | None]:
    """Test/CLI helper: bind a caller outside the HTTP middleware."""
    return _current.set(caller)


class TokenTable:
    def __init__(self, config: Config):
        self._entries = [
            (
                bytes.fromhex(t.sha256),
                Caller(t.label, t.access, t.max_writes_per_hour, token_key=t.sha256),
            )
            for t in config.tokens
        ]

    def resolve(self, token: str) -> Caller | None:
        digest = hashlib.sha256(token.encode()).digest()
        found = None
        for candidate, caller in self._entries:
            if hmac.compare_digest(digest, candidate):
                found = caller
        return found


def bearer(scope: Scope) -> str | None:
    values = [v for k, v in scope.get("headers") or [] if k == b"authorization"]
    if len(values) != 1:
        return None
    scheme, _, token = str(values[0].decode("latin-1")).partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


class BearerAuthMiddleware:
    """Rejects unauthenticated requests (except exempt paths) and binds the Caller.

    Pure ASGI, so streamed responses pass through unbuffered.
    """

    def __init__(self, app: ASGIApp, tokens: TokenTable, exempt_paths: frozenset[str]):
        self.app = app
        self.tokens = tokens
        self.exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            # Nothing but HTTP is served (no websockets): refuse before accepting.
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        if scope.get("path") in self.exempt_paths:
            await self.app(scope, receive, send)
            return
        token = bearer(scope)
        caller = self.tokens.resolve(token) if token else None
        if caller is None:
            body = json.dumps({"error": "unauthorized"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"www-authenticate", b'Bearer realm="pv-grocy"'),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        reset = _current.set(caller)
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(reset)
