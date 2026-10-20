# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Against a real Grocy, to catch the fake drifting from it: `pytest -m live` with
PV_GROCY_TEST_URL (and PV_GROCY_TEST_API_KEY unless Grocy runs in demo mode).

THIS CHANGES THE GROCY IT RUNS AGAINST. Use a throwaway demo instance (CONTRIBUTING.md),
never a household's Grocy. It undoes what it can, but not everything can be undone.
"""

from __future__ import annotations

import base64
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from pv_grocy.config import parse_config
from pv_grocy.server import Runtime

from .conftest import Harness

pytestmark = pytest.mark.live
URL = os.environ.get("PV_GROCY_TEST_URL")


@pytest.fixture
async def live() -> AsyncIterator[Harness]:
    if not URL:
        pytest.skip("PV_GROCY_TEST_URL is not set")
    tokens = [
        {"label": "admin", "sha256": "0" * 64, "access": "full"},
        {"label": "reader", "sha256": "1" * 64, "access": "read"},
    ]
    cfg = parse_config(
        {"grocy": {"url": URL}, "tokens": tokens},
        {
            "PV_GROCY_API_KEY": os.environ.get("PV_GROCY_TEST_API_KEY", "demo"),
            "PV_GROCY_WRITE": "enabled",
        },
    )
    runtime = Runtime(cfg)
    await runtime.start()
    try:
        yield Harness(runtime)
    finally:
        await runtime.stop()


async def any_product(h: Harness) -> dict[str, Any]:
    products = (await h.call("stock_overview", as_="reader", limit=200))["products"]
    plain = []
    for p in sorted(products, key=lambda p: -p["amount"]):
        detail = await h.call("stock_product", as_="reader", product=p["product_id"])
        if not detail["product"]["tare_weight_handling"]:
            plain.append(p)
            break
    assert plain, "the live Grocy has no stock without tare weight handling; use demo mode"
    return plain[0]


async def test_every_read_tool_works(live: Harness) -> None:
    h = live
    assert (await h.call("system_info", as_="reader"))["grocy_version"]
    p = await any_product(h)
    for tool, args in [
        ("stock_due", {}),
        ("stock_product", {"product": p["product_id"]}),
        ("stock_product", {"product": p["name"].upper()}),
        ("stock_entries", {"product": p["product_id"]}),
        ("stock_search", {"query": p["name"][:3]}),
        ("stock_journal", {"limit": 5}),
        ("shopping_list_view", {}),
        ("recipes_list", {}),
        ("meal_plan_list", {}),
        ("chores_list", {}),
        ("tasks_list", {"include_done": True}),
        ("batteries_list", {}),
        ("equipment_list", {}),
        ("entity_list", {"entity": "locations"}),
        ("entity_describe", {"entity": "products"}),
        ("search", {"query": "a"}),
        ("calendar_summary", {}),
        ("calendar_ical", {}),
        ("workflow_match_products", {"items": [{"name": p["name"]}, {"name": "zz-no-such-thing"}]}),
    ]:
        await h.call(tool, as_="reader", **args)
    history = await h.call("stock_price_history", as_="reader", product=p["product_id"])
    # The fake copies Grocy's price-history shape; a renamed field would show up as nulls here.
    assert history["unit"] and history["total"] >= len(history["prices"])
    for row in history["prices"]:
        assert row["date"] and row["price"] is not None, row
    if history["prices"]:
        assert history["latest"] == history["prices"][0] and history["lowest"]
    recipes = (await h.call("recipes_list", as_="reader"))["recipes"]
    if recipes:
        for tool in ("recipe_details", "recipe_fulfillment", "recipe_consume_preview"):
            await h.call(tool, as_="reader", recipe=recipes[0]["id"])
    assert "cannot list" in await h.error("entity_list", as_="reader", entity="api_keys")


async def test_stock_round_trip_with_undo(live: Harness) -> None:
    h = live
    p = await any_product(h)
    before = (await h.call("stock_product", product=p["product_id"]))["amount"]
    added = await h.call("stock_add", product=p["product_id"], amount=2)
    assert added["now_in_stock"]["amount"] == before + 2
    consumed = await h.call("stock_consume", product=p["product_id"], amount=1)
    assert consumed["now_in_stock"]["amount"] == before + 1
    for tx in (consumed["transaction_id"], added["transaction_id"]):
        await h.call("stock_undo", transaction_id=tx)
    assert (await h.call("stock_product", product=p["product_id"]))["amount"] == before
    assert "already undone" in await h.error("stock_undo", transaction_id=added["transaction_id"])
    assert "Grocy:" in await h.error("stock_consume", product=p["product_id"], amount=999_999)


async def test_shopping_recipe_meal_plan_chore_task_battery(live: Harness) -> None:
    h = live
    tag = uuid.uuid4().hex[:8]
    item = await h.call("shopping_list_add", note=f"live-test {tag}")
    await h.call("shopping_list_update", item_id=item["item_id"], amount=2, done=True)
    await h.call("shopping_list_remove", item_id=item["item_id"])
    p = await any_product(h)
    r = await h.call(
        "recipe_create",
        name=f"Live test {tag}",
        ingredients=[{"product": p["product_id"], "amount": 1}],
    )
    assert r["ingredients_added"] == 1
    details = await h.call("recipe_details", recipe=f"live test {tag}")
    assert details["ingredients"][0]["product_id"] == p["product_id"]
    e = await h.call("meal_plan_add", day="2030-06-03", recipe=r["id"])
    await h.call("meal_plan_remove", entry_id=e["entry_id"])
    await h.call("entity_delete", entity="recipes", id=r["id"])
    t = await h.call("task_create", name=f"live-test {tag}", due_date="2030-01-01")
    await h.call("task_complete", task_id=t["id"])
    await h.call("task_undo", task_id=t["id"])
    await h.call("task_delete", task_id=t["id"])
    chores = (await h.call("chores_list", as_="reader"))["chores"]
    if chores:
        ex = await h.call("chore_execute", chore=chores[0]["id"])
        await h.call("chore_undo", execution_id=ex["execution_id"])
    batteries = (await h.call("batteries_list", as_="reader"))["batteries"]
    if batteries:
        c = await h.call("battery_charge", battery=batteries[0]["id"])
        await h.call("battery_charge_undo", cycle_id=c["cycle_id"])


async def test_master_data_and_files(live: Harness) -> None:
    h = live
    tag = uuid.uuid4().hex[:8]
    loc = await h.call(
        "catalog_create",
        entity="locations",
        fields={"name": f"live-test {tag}", "is_freezer": False},
    )
    await h.call("catalog_update", entity="locations", id=loc["id"], fields={"description": "x"})
    assert "no column named nope" in await h.error(
        "catalog_create", entity="locations", fields={"nope": 1}
    )
    await h.call("entity_delete", entity="locations", id=loc["id"])
    name = f"live-test-{tag}.txt"
    await h.call(
        "file_upload",
        group="userfiles",
        file_name=name,
        content_base64=base64.b64encode(b"hi").decode(),
    )
    got = await h.call("file_download", as_="reader", group="userfiles", file_name=name)
    assert base64.b64decode(got["content_base64"]) == b"hi"
    await h.call("file_delete", group="userfiles", file_name=name)


async def test_remaining_tools(live: Harness) -> None:
    """Every tool not exercised above, so a Grocy change to any endpoint shows up here."""
    h = live
    tag = uuid.uuid4().hex[:8]
    p = await any_product(h)
    pid = p["product_id"]
    # Stock: open, transfer, inventory (each undone), barcode lookup.
    detail = await h.call("stock_product", as_="reader", product=pid)
    opened = await h.call("stock_open", product=pid, amount=1)
    await h.call("stock_undo", transaction_id=opened["transaction_id"])
    locations = (await h.call("entity_list", as_="reader", entity="locations"))["rows"]
    here = detail["locations"][0]["location_id"]
    there = next(loc["id"] for loc in locations if loc["id"] != here)
    moved = await h.call(
        "stock_transfer", product=pid, amount=1, from_location=here, to_location=there
    )
    await h.call("stock_undo", transaction_id=moved["transaction_id"])
    counted = await h.call("stock_inventory", product=pid, new_amount=detail["amount"] + 1)
    await h.call("stock_undo", transaction_id=counted["transaction_id"])
    assert (await h.call("stock_product", product=pid))["amount"] == detail["amount"]
    barcodes = (await h.call("entity_list", as_="reader", entity="product_barcodes", limit=1))[
        "rows"
    ]
    if barcodes:
        found = await h.call("stock_barcode_lookup", as_="reader", barcode=barcodes[0]["barcode"])
        assert found["product"]["id"] == barcodes[0]["product_id"]

    # Workflows: preview, then apply, then undo the bookings.
    intake = await h.call(
        "workflow_stock_intake_preview", as_="reader", items=[{"name": p["name"], "amount": 1}]
    )
    assert intake["apply_items"] == [{"product_id": pid, "amount": 1}]
    applied = await h.call("workflow_stock_intake_apply", items=intake["apply_items"])
    for a in applied["applied"]:
        await h.call("stock_undo", transaction_id=a["transaction_id"])
    await h.call("shopping_list_add", product=pid, amount=2)
    reconcile = await h.call(
        "workflow_shopping_reconcile_preview",
        as_="reader",
        purchased=[{"product": pid, "amount": 1}],
    )
    assert reconcile["actions"]
    actions = [{k: v for k, v in a.items() if k != "product"} for a in reconcile["actions"]]
    await h.call("workflow_shopping_reconcile_apply", actions=actions)

    # Shopping list bulk adds and clear (demo data only).
    await h.call("shopping_list_add_missing")
    await h.call("shopping_list_add_missing", which="overdue")
    await h.call("shopping_list_clear", done_only=True)

    # Recipes: edit, ingredients, missing to shopping list, consume (undone).
    r = await h.call("recipe_create", name=f"Live test {tag}")
    await h.call("recipe_update", recipe=r["id"], description="<p>live</p>", servings=2)
    ing = await h.call("recipe_ingredient_add", recipe=r["id"], product=pid, amount=1)
    await h.call("recipe_add_missing_to_shopping_list", recipe=r["id"])
    consumed = await h.call("recipe_consume", recipe=r["id"])
    if consumed["transaction_id"]:
        await h.call("stock_undo", transaction_id=consumed["transaction_id"])
    await h.call("recipe_ingredient_remove", recipe=r["id"], ingredient_id=ing["ingredient_id"])
    await h.call("entity_delete", entity="recipes", id=r["id"])
    week = await h.call("meal_plan_add_missing_to_shopping_list")
    assert week["week"]

    # Chores, batteries, equipment: create, read, change, delete.
    c = await h.call("chore_create", name=f"live-test {tag}", period_type="weekly")
    assert (await h.call("chore_details", as_="reader", chore=c["id"]))["period_type"] == "weekly"
    await h.call("entity_delete", entity="chores", id=c["id"])
    b = await h.call("battery_create", name=f"live-test {tag}", charge_interval_days=30)
    await h.call("battery_update", battery=b["id"], used_in="live test")
    assert (await h.call("battery_details", as_="reader", battery=b["id"]))[
        "used_in"
    ] == "live test"
    await h.call("entity_delete", entity="batteries", id=b["id"])
    e = await h.call("equipment_create", name=f"live-test {tag}")
    await h.call("equipment_update", equipment=e["id"], description="<p>manual</p>")
    assert (await h.call("equipment_details", as_="reader", equipment=e["id"]))[
        "description"
    ] == "manual"
    await h.call("entity_delete", entity="equipment", id=e["id"])

    # Raw entities.
    group = await h.call(
        "entity_create", entity="product_groups", fields={"name": f"live-test {tag}"}
    )
    await h.call(
        "entity_update", entity="product_groups", id=group["id"], fields={"description": "x"}
    )
    assert (await h.call("entity_get", as_="reader", entity="product_groups", id=group["id"]))[
        "row"
    ]["description"] == "x"
    await h.call("entity_delete", entity="product_groups", id=group["id"])

    # Sharing link and printing. A demo Grocy has no label printer: Grocy answering with
    # its own refusal still shows the endpoint exists.
    assert "secret=" in (await h.call("calendar_sharing_link"))["url"]
    for tool, args in (
        ("print_label", {"target": "product", "ref": pid}),
        ("print_shopping_list", {}),
    ):
        try:
            await h.call(tool, **args)
        except ToolError as exc:  # a Grocy refusal is fine; a missing route is not
            assert "Grocy:" in str(exc) and "not found" not in str(exc).lower(), (tool, exc)
