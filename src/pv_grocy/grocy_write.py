# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""The only code that changes Grocy (ADR-0002). Imported only when PV_GROCY_WRITE=enabled.

Retry rule (ADR-0003): a write is retried only when it provably never reached Grocy (the
connection could not be opened). Once a request may have been sent, a timeout, dropped
connection or 5xx raises WriteOutcomeUnknown and is never repeated, so one tool call can
never book stock twice.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .errors import GrocyUnavailable, WriteOutcomeUnknown
from .grocy import RETRY_BACKOFF_SECONDS, is_side_effect_path, raise_for_client_error

log = logging.getLogger(__name__)

# Raised before any byte of the request is sent.
NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
CONNECT_RETRIES = 2
UNKNOWN = "Grocy did not confirm this change, so it may or may not have been applied"


class GrocyWriter:
    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(CONNECT_RETRIES + 1):
            try:
                resp = await self._http.request(method, path, **kwargs)
            except NOT_SENT as exc:
                if attempt < CONNECT_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                    continue
                log.warning("Grocy unreachable for a write: %s", type(exc).__name__)
                raise GrocyUnavailable(
                    "Grocy is unavailable right now; nothing was changed. Try again shortly"
                ) from exc
            except httpx.TransportError as exc:
                log.warning("write outcome unknown: %s", type(exc).__name__)
                raise WriteOutcomeUnknown(UNKNOWN) from exc
            if resp.status_code >= 500:
                log.warning("write outcome unknown: Grocy HTTP %s", resp.status_code)
                raise WriteOutcomeUnknown(UNKNOWN)
            raise_for_client_error(resp)
            return resp
        raise AssertionError("unreachable")

    @staticmethod
    def _json(resp: httpx.Response) -> Any:
        return resp.json() if resp.content else None

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._json(await self._send("POST", path, json=body or {}))

    async def put(self, path: str, body: dict[str, Any]) -> Any:
        return self._json(await self._send("PUT", path, json=body))

    async def delete(self, path: str) -> None:
        await self._send("DELETE", path)

    async def put_bytes(self, path: str, content: bytes) -> None:
        await self._send(
            "PUT", path, content=content, headers={"Content-Type": "application/octet-stream"}
        )

    async def print_trigger(self, path: str) -> Any:
        """The print endpoints are GETs with a side effect, so they live here."""
        if not is_side_effect_path(path):
            raise AssertionError(f"not a print endpoint: {path}")
        return self._json(await self._send("GET", path))
