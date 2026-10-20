# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""The HTTP surface: auth, health, per-token tool lists, instructions, audit log."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from starlette.testclient import TestClient

from pv_grocy.server import INSTRUCTIONS, Runtime, create_app

from .conftest import TOKENS, make_config
from .fakegrocy import FakeGrocy

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "mcp-protocol-version": "2025-06-18",
}


@pytest.fixture
def client(fake: FakeGrocy) -> Iterator[TestClient]:
    with TestClient(create_app(Runtime(make_config(), transport=fake.transport()))) as c:
        yield c


@pytest.fixture
def ro_client(fake: FakeGrocy) -> Iterator[TestClient]:
    with TestClient(create_app(Runtime(make_config(write=False), transport=fake.transport()))) as c:
        yield c


def rpc(
    c: TestClient, method: str, params: dict[str, Any] | None = None, token: str | None = None
) -> Any:
    headers = MCP_HEADERS | ({"Authorization": f"Bearer {token}"} if token else {})
    resp = c.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def initialize(c: TestClient, token: str) -> dict[str, Any]:
    return rpc(
        c,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"},
        },
        token,
    )["result"]


def tools(c: TestClient, token: str) -> set[str]:
    return {t["name"] for t in rpc(c, "tools/list", token=token)["result"]["tools"]}


@pytest.mark.parametrize(
    "header", [None, "Bearer nope", "Basic dXNlcjpwYXNz", "token-reader", "Bearer "]
)
def test_missing_or_unknown_bearer_is_401(client: TestClient, header: str | None) -> None:
    resp = client.post(
        "/mcp", headers=MCP_HEADERS | ({"Authorization": header} if header else {}), json={}
    )
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == 'Bearer realm="pv-grocy"'
    assert resp.json() == {"error": "unauthorized"}


def test_every_other_path_needs_auth(client: TestClient) -> None:
    assert client.get("/").status_code == 401
    assert client.get("/healthz/x").status_code == 401


def test_healthz_is_open_and_minimal(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


def test_deep_health(client: TestClient, fake: FakeGrocy) -> None:
    assert client.get("/healthz?deep=1").json() == {"status": "ok", "grocy_version": "4.7.1"}
    fake.fail("GET", "/system/info", "connect")
    fake.fail("GET", "/system/info", "connect")
    fake.fail("GET", "/system/info", "connect")
    resp = client.get("/healthz?deep=1")
    assert resp.status_code == 503 and resp.json()["error"] == "grocy_unreachable"


def test_deep_health_wrong_key_and_old_grocy(
    fake: FakeGrocy, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = make_config()
    wrong = Runtime(type(cfg)(**{**cfg.__dict__, "api_key": "wrong"}), transport=fake.transport())
    with TestClient(create_app(wrong)) as c:
        resp = c.get("/healthz?deep=1")
        assert resp.status_code == 503 and resp.json()["error"] == "grocy_api_key_rejected"
    real = fake.route
    monkeypatch.setattr(
        fake,
        "route",
        lambda m, p, *a: (
            {"grocy_version": {"Version": "4.3.0"}} if p == "/system/info" else real(m, p, *a)
        ),
    )
    with TestClient(create_app(Runtime(cfg, transport=fake.transport()))) as c:
        resp = c.get("/healthz?deep=1")
        assert resp.status_code == 503 and resp.json()["grocy_version"] == "4.3.0"


def test_each_level_lists_only_its_tools(client: TestClient) -> None:
    read, write, full = (tools(client, TOKENS[k]) for k in ("reader", "writer", "admin"))
    assert read < write < full
    assert "stock_add" not in read and "stock_overview" in read
    assert "stock_add" in write and "task_delete" not in write and "entity_delete" not in write
    assert {
        "task_delete",
        "entity_delete",
        "shopping_list_clear",
        "file_upload",
        "file_delete",
        "entity_create",
        "entity_update",
        "calendar_sharing_link",
    } == full - write


def test_read_only_deployment_has_no_write_tools(ro_client: TestClient) -> None:
    names = tools(ro_client, TOKENS["admin"])  # every token is read-only without the switch
    assert len(names) == 32
    assert not any(
        n.endswith(("_add", "_apply", "_delete", "_undo", "_create"))
        for n in names
        if not n.startswith(("workflow_match",))
    )


def test_ungranted_tool_fails_like_an_unknown_one(client: TestClient, fake: FakeGrocy) -> None:
    before = len(fake.requests)
    granted = rpc(
        client,
        "tools/call",
        {"name": "stock_add", "arguments": {"product": 1, "amount": 1}},
        TOKENS["reader"],
    )
    unknown = rpc(client, "tools/call", {"name": "no_such_tool", "arguments": {}}, TOKENS["reader"])
    assert granted["result"]["isError"] and unknown["result"]["isError"]
    text = granted["result"]["content"][0]["text"]
    assert text == unknown["result"]["content"][0]["text"].replace("no_such_tool", "stock_add")
    assert len(fake.requests) == before  # nothing reached Grocy


def test_instructions_per_level(client: TestClient) -> None:
    for label, level in (("reader", 0), ("writer", 1), ("admin", 2)):
        assert initialize(client, TOKENS[label])["instructions"] == INSTRUCTIONS[level]  # type: ignore[index]
    assert "Nothing here can change Grocy" in INSTRUCTIONS[0]  # type: ignore[index]


def test_tool_call_end_to_end_with_envelope(client: TestClient) -> None:
    result = rpc(client, "tools/call", {"name": "system_info", "arguments": {}}, TOKENS["reader"])[
        "result"
    ]
    data = result["structuredContent"]
    assert data["grocy_version"] == "4.7.1"
    assert data["content_trust"] == "untrusted" and data["provenance"]["source"] == "grocy"
    assert "os" not in data and "secret-host" not in json.dumps(result)


def test_audit_line_per_call_without_content(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO", logger="pv_grocy.audit"):
        rpc(
            client,
            "tools/call",
            {
                "name": "shopping_list_add",
                "arguments": {"note": "secret surprise gift", "amount": 2},
            },
            TOKENS["writer"],
        )
    (line,) = [json.loads(r.getMessage()) for r in caplog.records if r.name == "pv_grocy.audit"]
    assert line["tool"] == "shopping_list_add" and line["token_label"] == "writer" and line["write"]
    assert line["outcome"] == "ok" and line["args"] == {
        "note": "<20 chars>",
        "amount": 2.0,
        "shopping_list": 1,
    }
    assert "secret" not in caplog.text


def test_write_modules_are_imported_only_when_switched_on(tmp_path: Any) -> None:
    code = (
        "import sys\n"
        "from tests.conftest import make_config\n"
        "from pv_grocy.server import Runtime, build_server\n"
        "build_server(Runtime(make_config(write=False)))\n"
        "bad = [m for m in sys.modules\n"
        "       if m.startswith(('pv_grocy.writes', 'pv_grocy.grocy_write'))]\n"
        "assert not bad, bad\n"
        "build_server(Runtime(make_config(write=True)))\n"
        "assert 'pv_grocy.writes.stock' in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
