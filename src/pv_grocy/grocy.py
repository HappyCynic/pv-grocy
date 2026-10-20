# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Read-only Grocy REST client.

Sends only GET, and never to a path that has a side effect (the label and thermal print
endpoints are GETs that print). Everything that changes Grocy is in grocy_write.py, which
is imported only when writes are switched on (ADR-0002). GETs are retried on connection
errors and 502/503/504, since repeating one changes nothing (ADR-0003).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from .config import Config
from .errors import GrocyAuthFailed, GrocyRejected, GrocyUnavailable, ToolInputError

log = logging.getLogger(__name__)

RETRY_STATUS = frozenset({502, 503, 504})
READ_RETRIES = 2
RETRY_BACKOFF_SECONDS = (0.5, 1.0)
GROCY_MESSAGE_MAX_CHARS = 300

Params = Mapping[str, str | int | Sequence[str]]


def make_http_client(
    config: Config, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """One pooled client for the process. Redirects are not followed, so the API key is
    only ever sent to the configured Grocy."""
    return httpx.AsyncClient(
        base_url=config.grocy_url + "/api",
        headers={"GROCY-API-KEY": config.api_key, "Accept": "application/json"},
        timeout=httpx.Timeout(config.timeout_seconds, connect=10.0),
        follow_redirects=False,
        transport=transport,
    )


def is_side_effect_path(path: str) -> bool:
    """GET endpoints that print (they belong to the write path)."""
    return path.rstrip("/").endswith("/printlabel") or path.startswith("/print/")


def grocy_message(resp: httpx.Response) -> str:
    """Grocy's own `error_message`, capped; never its `error_details` (a stack trace)."""
    try:
        body = resp.json()
    except ValueError:
        body = None
    text = body.get("error_message") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        return f"Grocy refused the request (HTTP {resp.status_code})"
    text = " ".join(text.split())
    if text.startswith("SQLSTATE"):
        # "SQLSTATE[HY000]: General error: 1 table x has no column named y": keep the tail.
        text = re.sub(r"^\d+ ", "", text.rsplit(": ", 1)[-1])
    if len(text) > GROCY_MESSAGE_MAX_CHARS:
        text = text[: GROCY_MESSAGE_MAX_CHARS - 1] + "…"
    return f"Grocy: {text}"


def raise_for_client_error(resp: httpx.Response, not_found: str = "not found in Grocy") -> None:
    """4xx handling shared by reads and writes."""
    status = resp.status_code
    if status in (401, 403):
        log.error("Grocy rejected the API key (HTTP %s); check PV_GROCY_API_KEY", status)
        raise GrocyAuthFailed("Grocy rejected pv-grocy's API key; the operator must fix it")
    if status == 404:
        raise ToolInputError(not_found)
    if 400 <= status < 500:
        raise GrocyRejected(grocy_message(resp))


class GrocyReader:
    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def _get(self, path: str, params: Params | None = None) -> httpx.Response:
        if is_side_effect_path(path):
            raise AssertionError(f"read client must not call a print endpoint: {path}")
        for attempt in range(READ_RETRIES + 1):
            try:
                resp = await self._http.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt < READ_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                    continue
                log.warning("Grocy unreachable: %s", type(exc).__name__)
                raise GrocyUnavailable("Grocy is unavailable right now; try again shortly") from exc
            if resp.status_code in RETRY_STATUS and attempt < READ_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue
            if resp.status_code >= 500:
                log.warning("Grocy server error on read: HTTP %s", resp.status_code)
                raise GrocyUnavailable("Grocy is unavailable right now; try again shortly")
            raise_for_client_error(resp)
            return resp
        raise AssertionError("unreachable")

    async def get(self, path: str, params: Params | None = None) -> Any:
        resp = await self._get(path, params)
        return resp.json() if resp.content else None

    async def get_text(self, path: str, params: Params | None = None) -> str:
        return (await self._get(path, params)).text

    async def get_bytes(
        self, path: str, max_bytes: int, params: Params | None = None
    ) -> tuple[bytes, str]:
        resp = await self._get(path, params)
        if len(resp.content) > max_bytes:
            raise ToolInputError(f"file is larger than {max_bytes} bytes")
        return resp.content, resp.headers.get("content-type", "application/octet-stream")

    async def objects(
        self,
        entity: str,
        *,
        query: Sequence[str] = (),
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int | Sequence[str]] = {}
        if query:
            params["query[]"] = list(query)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        result = await self.get(f"/objects/{entity}", params or None)
        return result if isinstance(result, list) else []

    async def object(self, entity: str, obj_id: int) -> dict[str, Any]:
        """One row; ToolInputError if it does not exist."""
        try:
            resp = await self._get(f"/objects/{entity}/{obj_id}")
        except ToolInputError:
            raise ToolInputError(f"no {entity} with id {obj_id}") from None
        data = resp.json() if resp.content else None
        if not isinstance(data, dict) or not data:
            raise ToolInputError(f"no {entity} with id {obj_id}")
        return data
