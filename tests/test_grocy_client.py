# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Retry and error rules (ADR-0003): reads retry, writes never repeat once sent."""

from __future__ import annotations

import pytest

from .conftest import Harness
from .fakegrocy import FakeGrocy

pytestmark = pytest.mark.usefixtures("no_sleep")


async def test_reads_retry_connection_errors_and_503(h: Harness, fake: FakeGrocy) -> None:
    fake.fail("GET", "/system/info", "connect")
    fake.fail("GET", "/system/info", "503")
    assert (await h.call("system_info"))["grocy_version"] == "4.7.1"
    assert fake.count("GET", "/system/info") == 2  # the 503 and the success; connect never arrived


async def test_reads_give_up_after_retries(h: Harness, fake: FakeGrocy) -> None:
    for _ in range(3):
        fake.fail("GET", "/system/info", "read_timeout")
    assert "Grocy is unavailable" in await h.error("system_info")


async def test_a_write_that_timed_out_is_never_repeated(h: Harness, fake: FakeGrocy) -> None:
    fake.fail("POST", "/stock/products/1/add", "read_timeout")
    msg = await h.error("stock_add", product="Milk", amount=1)
    assert msg.endswith(
        "Grocy did not confirm this change, so it may or may not have been applied; "
        "check stock_journal before trying again"
    )
    assert fake.count("POST", "/stock/products/1/add") == 1
    # It was in fact applied once (the fake applies it, then times out): exactly one booking.
    assert len([r for r in fake.db["stock_log"] if r["transaction_type"] == "purchase"]) == 1


@pytest.mark.parametrize("status", ["500", "502", "503", "504"])
async def test_a_write_answered_with_5xx_is_unknown_and_not_repeated(
    h: Harness, fake: FakeGrocy, status: str
) -> None:
    fake.fail("POST", "/stock/products/1/consume", status)
    msg = await h.error("stock_consume", product="Milk", amount=1)
    assert "may or may not have been applied" in msg
    assert fake.count("POST", "/stock/products/1/consume") == 1


async def test_a_write_that_never_connected_is_retried(h: Harness, fake: FakeGrocy) -> None:
    fake.fail("POST", "/stock/products/1/add", "connect")
    out = await h.call("stock_add", product="Milk", amount=1)
    assert out["transaction_id"]
    assert fake.count("POST", "/stock/products/1/add") == 1


async def test_a_write_that_cannot_connect_changed_nothing(h: Harness, fake: FakeGrocy) -> None:
    for _ in range(3):
        fake.fail("POST", "/stock/products/1/add", "connect")
    assert "nothing was changed" in await h.error("stock_add", product="Milk", amount=1)
    assert fake.db["stock_log"] == []


async def test_grocy_refusal_passes_its_message_without_details(h: Harness) -> None:
    msg = await h.error("stock_consume", product="Milk", amount=99)
    assert msg.endswith(
        "Grocy: Amount to be consumed cannot be > current stock amount "
        "(if supplied, at the desired location)"
    )
    assert "stack_trace" not in msg


async def test_sql_errors_are_trimmed(h: Harness) -> None:
    msg = await h.error("catalog_create", entity="locations", fields={"nope": 1})
    assert msg.endswith("Grocy: table locations has no column named nope")


async def test_wrong_api_key_is_an_operator_error(
    make_harness, fake: FakeGrocy, caplog: pytest.LogCaptureFixture
) -> None:  # type: ignore[no-untyped-def]
    h = await make_harness()
    h.runtime.http.headers["GROCY-API-KEY"] = "wrong"
    msg = await h.error("system_info")
    assert "rejected pv-grocy's API key" in msg
    assert "check PV_GROCY_API_KEY" in caplog.text and "wrong" not in caplog.text


def test_reader_refuses_print_endpoints() -> None:
    import asyncio

    import httpx

    from pv_grocy.grocy import GrocyReader

    reader = GrocyReader(httpx.AsyncClient(base_url="http://x"))
    for path in (
        "/stock/products/1/printlabel",
        "/print/shoppinglist/thermal",
        "/chores/1/printlabel/",
    ):
        with pytest.raises(AssertionError):
            asyncio.run(reader.get(path))
