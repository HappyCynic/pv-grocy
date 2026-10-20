# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from pv_grocy.auth import Caller, bind_caller
from pv_grocy.config import Access, Config, parse_config
from pv_grocy.server import Runtime, build_server

from .fakegrocy import API_KEY, FakeGrocy

TOKENS = {"reader": "token-reader", "writer": "token-writer", "admin": "token-admin"}
LEVELS = {"reader": "read", "writer": "write", "admin": "full"}


def sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def make_config(write: bool = True, max_writes: int = 60, **extra_env: str) -> Config:
    tokens = [
        {
            "label": label,
            "sha256": sha(tok),
            "access": LEVELS[label] if write else "read",
            "max_writes_per_hour": max_writes,
        }
        for label, tok in TOKENS.items()
    ]
    env = {
        "PV_GROCY_API_KEY": API_KEY,
        **({"PV_GROCY_WRITE": "enabled"} if write else {}),
        **extra_env,
    }
    return parse_config({"grocy": {"url": "http://grocy.test"}, "tokens": tokens}, env)


@pytest.fixture
def fake() -> FakeGrocy:
    return FakeGrocy()


class Harness:
    """Calls tools in-process as a given token (default: admin), like an MCP client."""

    def __init__(self, runtime: Runtime):
        self.runtime = runtime
        self.mcp = build_server(runtime)

    def caller(self, label: str) -> Caller:
        t = next(t for t in self.runtime.config.tokens if t.label == label)
        return Caller(t.label, t.access, t.max_writes_per_hour, token_key=t.sha256)

    async def call(self, tool: str, as_: str = "admin", **args: Any) -> dict[str, Any]:
        token = bind_caller(self.caller(as_))
        try:
            result = await self.mcp.call_tool(tool, args)
        finally:
            from pv_grocy import auth

            auth._current.reset(token)
        assert not result.is_error, result.content
        data = result.structured_content
        assert isinstance(data, dict)
        return data

    async def error(self, tool: str, as_: str = "admin", **args: Any) -> str:
        with pytest.raises(ToolError) as info:
            await self.call(tool, as_, **args)
        return str(info.value)

    async def tool_names(self) -> set[str]:
        return {t.name for t in await self.mcp.list_tools()}


@pytest.fixture
async def make_harness(fake: FakeGrocy) -> AsyncIterator[Callable[..., Any]]:
    runtimes: list[Runtime] = []

    async def make(**kwargs: Any) -> Harness:
        runtime = Runtime(make_config(**kwargs), transport=fake.transport())
        await runtime.start()
        runtimes.append(runtime)
        return Harness(runtime)

    yield make
    for r in runtimes:
        await r.stop()


@pytest.fixture
async def h(make_harness: Callable[..., Any]) -> Harness:
    harness: Harness = await make_harness()
    return harness


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries back off with asyncio.sleep; make them instant."""

    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("pv_grocy.grocy.asyncio.sleep", instant)
    monkeypatch.setattr("pv_grocy.grocy_write.asyncio.sleep", instant)


__all__ = ["Access", "FakeGrocy", "Harness", "TOKENS", "make_config", "sha"]
