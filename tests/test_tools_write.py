# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
from typing import Any

import pytest

from .conftest import Harness
from .fakegrocy import FakeGrocy


def amount(fake: FakeGrocy, pid: int) -> float:
    return fake.amount(pid)


async def test_stock_add_consume_and_undo(h: Harness, fake: FakeGrocy) -> None:
    out = await h.call(
        "stock_add",
        as_="writer",
        product="Milk",
        amount=3,
        best_before_date="2026-12-01",
        price=1.1,
        location="Pantry",
        store="Corner shop",
    )
    assert out["now_in_stock"]["amount"] == 5 and out["bookings"] == 1
    entry = fake.db["stock"][-1]
    assert (entry["location_id"], entry["price"], entry["best_before_date"]) == (
        2,
        1.1,
        "2026-12-01",
    )
    c = await h.call("stock_consume", as_="writer", product="Milk", amount=4, spoiled=True)
    assert c["now_in_stock"]["amount"] == 1 and c["bookings"] == 2  # oldest due first, two entries
    assert all(r["spoiled"] for r in fake.db["stock_log"][-2:])
    await h.call("stock_undo", as_="writer", transaction_id=c["transaction_id"])
    assert amount(fake, 1) == 5
    await h.call("stock_undo", as_="writer", transaction_id=out["transaction_id"])
    assert amount(fake, 1) == 2
    assert "already undone" in await h.error(
        "stock_undo", as_="writer", transaction_id=out["transaction_id"]
    )
    assert "no stock transaction" in await h.error(
        "stock_undo", as_="writer", transaction_id="abcdef123"
    )


async def test_consume_only_from_a_location(h: Harness) -> None:
    assert "cannot be >" in await h.error(
        "stock_consume", as_="writer", product="Milk", amount=1, location="Pantry"
    )


async def test_open_transfer_inventory(h: Harness, fake: FakeGrocy) -> None:
    o = await h.call("stock_open", as_="writer", product="Eggs")
    assert o["now_in_stock"]["amount_opened"] == 4
    t = await h.call(
        "stock_transfer", as_="writer", product="Eggs", amount=1, to_location="Freezer"
    )
    assert (t["from_location_id"], t["to_location_id"]) == (1, 3)
    msg = await h.error(
        "stock_transfer", as_="writer", product="Eggs", amount=1, to_location="Pantry"
    )
    assert "stored in 2 locations" in msg and "give from_location" in msg
    assert "the same" in await h.error(
        "stock_transfer",
        as_="writer",
        product="Eggs",
        amount=1,
        to_location="Fridge",
        from_location="Fridge",
    )
    i = await h.call("stock_inventory", as_="writer", product="Flour", new_amount=5)
    assert i["was"] == 1 and i["now_in_stock"]["amount"] == 5
    await h.call("stock_inventory", as_="writer", product="Flour", new_amount=0)
    assert amount(fake, 4) == 0


async def test_shopping_list_writes(h: Harness, fake: FakeGrocy) -> None:
    await h.call("shopping_list_add", as_="writer", product="Milk", amount=1)
    assert fake.get_row("shopping_list", 1)["amount"] == 3  # type: ignore[index]
    note = await h.call(
        "shopping_list_add", as_="writer", note="Birthday candles", shopping_list="Hardware"
    )
    assert fake.get_row("shopping_list", note["item_id"])["shopping_list_id"] == 2  # type: ignore[index]
    assert "give a product or a note" in await h.error("shopping_list_add", as_="writer")
    await h.call("shopping_list_update", as_="writer", item_id=2, done=True, note="Tall candles")
    assert fake.get_row("shopping_list", 2) | {} == {
        **fake.get_row("shopping_list", 2),
        "done": 1,
        "note": "Tall candles",
    }  # type: ignore[operator]
    assert "nothing to change" in await h.error("shopping_list_update", as_="writer", item_id=2)
    assert "no shopping list item 99" in await h.error(
        "shopping_list_update", as_="writer", item_id=99, done=True
    )
    await h.call("shopping_list_remove", as_="writer", item_id=2)
    assert fake.get_row("shopping_list", 2) is None
    out = await h.call("shopping_list_add_missing", as_="writer")
    assert out["items_after"] == out["items_before"] + 1  # Eggs below minimum
    await h.call("shopping_list_clear", as_="admin")
    assert [i for i in fake.db["shopping_list"] if i["shopping_list_id"] == 1] == []


async def test_recipe_writes(h: Harness, fake: FakeGrocy) -> None:
    r = await h.call(
        "recipe_create",
        as_="writer",
        name="Scrambled eggs",
        servings=2,
        ingredients=[
            {"product": "Eggs", "amount": 3, "group": "Main"},
            {"product": "milk", "amount": 0.5, "note": "splash"},
        ],
    )
    assert r["ingredients_added"] == 2
    pos = [p for p in fake.db["recipes_pos"] if p["recipe_id"] == r["id"]]
    assert [(p["product_id"], p["qu_id"], p.get("ingredient_group")) for p in pos] == [
        (3, 1, "Main"),
        (1, 3, None),
    ]
    before = len(fake.db["recipes"])
    msg = await h.error(
        "recipe_create",
        as_="writer",
        name="Bad",
        ingredients=[{"product": "Eggs", "amount": 1}, {"product": "almond", "amount": 1}],
    )
    assert msg.startswith(
        "Error executing tool recipe_create: ingredients[1]: no product is named exactly"
    )
    assert len(fake.db["recipes"]) == before  # nothing created
    await h.call("recipe_update", as_="writer", recipe="Scrambled eggs", servings=4)
    assert fake.get_row("recipes", r["id"])["desired_servings"] == 4  # type: ignore[index]
    added = await h.call(
        "recipe_ingredient_add", as_="writer", recipe=r["id"], product="Flour", amount=1
    )
    assert "is not in 'Pancakes'" in await h.error(
        "recipe_ingredient_remove",
        as_="writer",
        recipe="Pancakes",
        ingredient_id=added["ingredient_id"],
    )
    await h.call(
        "recipe_ingredient_remove",
        as_="writer",
        recipe=r["id"],
        ingredient_id=added["ingredient_id"],
    )
    assert fake.get_row("recipes_pos", added["ingredient_id"]) is None


async def test_recipe_create_partial_failure_says_what_exists(h: Harness, fake: FakeGrocy) -> None:
    fake.fail("POST", "/objects/recipes_pos", "read_timeout")
    msg = await h.error(
        "recipe_create", as_="writer", name="Toast", ingredients=[{"product": "Flour", "amount": 1}]
    )
    assert "was created (id" in msg and "only 0 of 1 ingredients" in msg


async def test_recipe_consume_partial_and_undo(h: Harness, fake: FakeGrocy) -> None:
    out = await h.call("recipe_consume", as_="writer", recipe="Pancakes")
    assert (amount(fake, 1), amount(fake, 3), amount(fake, 4)) == (
        1,
        2,
        0,
    )  # flour: only the 1 there
    await h.call("stock_undo", as_="writer", transaction_id=out["transaction_id"])
    assert (amount(fake, 1), amount(fake, 3), amount(fake, 4)) == (2, 4, 1)


async def test_recipe_and_meal_plan_to_shopping_list(h: Harness, fake: FakeGrocy) -> None:
    out = await h.call("recipe_add_missing_to_shopping_list", as_="writer", recipe="Pancakes")
    assert (
        any(i["product_id"] == 4 for i in fake.db["shopping_list"])
        and out["can_be_made_with_shopping_list"]
    )
    fake.db["shopping_list"] = []
    await h.call(
        "recipe_add_missing_to_shopping_list",
        as_="writer",
        recipe="Pancakes",
        exclude_products=["Flour"],
    )
    assert fake.db["shopping_list"] == []
    week = await h.call("meal_plan_add_missing_to_shopping_list", as_="writer")
    assert (
        week["week"] == "2026-42"
        and week["planned"]
        and (week["from"], week["to"]) == ("2026-10-19", "2026-10-25")
    )
    assert any(i["product_id"] == 4 for i in fake.db["shopping_list"])
    none = await h.call(
        "meal_plan_add_missing_to_shopping_list", as_="writer", week_of="2027-01-02"
    )
    assert none == {
        **none,
        "week": "2027-00",
        "planned": False,
        "from": "2027-01-01",
        "to": "2027-01-03",
    }


async def test_meal_plan_add_remove(h: Harness, fake: FakeGrocy) -> None:
    e = await h.call(
        "meal_plan_add",
        as_="writer",
        day="2026-10-23",
        recipe="Omelette",
        servings=2,
        section="Dinner",
    )
    row = fake.get_row("meal_plan", e["entry_id"])
    assert row and (row["recipe_id"], row["recipe_servings"], row["section_id"], row["type"]) == (
        2,
        2,
        2,
        "recipe",
    )
    n = await h.call("meal_plan_add", as_="writer", day="2026-10-23", note="Eat out")
    assert fake.get_row("meal_plan", n["entry_id"])["type"] == "note"  # type: ignore[index]
    await h.call("meal_plan_remove", as_="writer", entry_id=e["entry_id"])
    assert "no meal plan entry" in await h.error(
        "meal_plan_remove", as_="writer", entry_id=e["entry_id"]
    )


async def test_chores_tasks_batteries_equipment(h: Harness, fake: FakeGrocy) -> None:
    ex = await h.call(
        "chore_execute", as_="writer", chore="Water plants", tracked_time="2026-10-20 08:00"
    )
    assert fake.get_row("chores_log", ex["execution_id"])["tracked_time"] == "2026-10-20 08:00"  # type: ignore[index]
    u = await h.call("chore_undo", as_="writer", chore="Water plants")
    assert u["undone_execution_id"] == ex["execution_id"]
    assert "exactly one" in await h.error("chore_undo", as_="writer")
    await h.call(
        "chore_create",
        as_="writer",
        name="Descale kettle",
        period_type="monthly",
        period_interval=2,
    )
    t = await h.call(
        "task_create",
        as_="writer",
        name="Call plumber",
        due_date="2026-10-25",
        category="Home",
        assigned_to="sam",
    )
    assert fake.get_row("tasks", t["id"])["assigned_to_user_id"] == 2  # type: ignore[index]
    await h.call("task_complete", as_="writer", task_id=t["id"])
    assert fake.get_row("tasks", t["id"])["done"] == 1  # type: ignore[index]
    await h.call("task_undo", as_="writer", task_id=t["id"])
    await h.call("task_delete", as_="admin", task_id=t["id"])
    assert fake.get_row("tasks", t["id"]) is None
    c = await h.call("battery_charge", as_="writer", battery="Remote")
    await h.call("battery_charge_undo", as_="writer", cycle_id=c["cycle_id"])
    assert fake.get_row("battery_charge_cycles", c["cycle_id"])["undone"] == 1  # type: ignore[index]
    b = await h.call("battery_create", as_="writer", name="Smoke alarm", charge_interval_days=365)
    await h.call("battery_update", as_="writer", battery=b["id"], used_in="Hall")
    e = await h.call("equipment_create", as_="writer", name="Kettle")
    await h.call("equipment_update", as_="writer", equipment="kettle", description="1.7 l")
    assert fake.get_row("equipment", e["id"])["description"] == "1.7 l"  # type: ignore[index]


async def test_catalog_and_raw_entities(h: Harness, fake: FakeGrocy) -> None:
    p = await h.call(
        "catalog_create",
        as_="writer",
        entity="products",
        fields={
            "name": "Oat milk",
            "location_id": 1,
            "qu_id_stock": 3,
            "qu_id_purchase": 3,
            "min_stock_amount": 0,
            "active": True,
        },
    )
    assert fake.get_row("products", p["id"])["active"] == 1  # type: ignore[index]  # bools stored as 0/1
    await h.call(
        "catalog_update",
        as_="writer",
        entity="products",
        id=p["id"],
        fields={"min_stock_amount": 2},
    )
    for entity in ("tasks", "api_keys", "stock_log"):
        assert "cannot create" in await h.error(
            "catalog_create", as_="writer", entity=entity, fields={"name": "x"}
        )
    assert "cannot set id" in await h.error(
        "catalog_update", as_="writer", entity="products", id=1, fields={"id": 9}
    )
    assert "no products row with id 99" in await h.error(
        "catalog_update", as_="writer", entity="products", id=99, fields={"name": "x"}
    )
    await h.call("entity_update", as_="admin", entity="tasks", id=1, fields={"description": "soon"})
    await h.call("entity_delete", as_="admin", entity="products", id=p["id"])
    assert fake.get_row("products", p["id"]) is None
    assert "cannot delete" in await h.error("entity_delete", as_="admin", entity="stock_log", id=1)
    assert "cannot create" in await h.error(
        "entity_create", as_="admin", entity="api_keys", fields={"x": 1}
    )


async def test_files_printing_sharing_link(h: Harness, fake: FakeGrocy) -> None:
    data = base64.b64encode(b"manual").decode()
    await h.call(
        "file_upload",
        as_="admin",
        group="equipmentmanuals",
        file_name="kettle.pdf",
        content_base64=data,
    )
    assert fake.files[("equipmentmanuals", "kettle.pdf")] == b"manual"
    assert "already exists" in await h.error(
        "file_upload",
        as_="admin",
        group="equipmentmanuals",
        file_name="kettle.pdf",
        content_base64=data,
    )
    assert "not valid base64" in await h.error(
        "file_upload", as_="admin", group="userfiles", file_name="a", content_base64="***"
    )
    await h.call("file_delete", as_="admin", group="equipmentmanuals", file_name="kettle.pdf")
    assert ("equipmentmanuals", "kettle.pdf") not in fake.files
    await h.call("print_label", as_="writer", target="product", ref="Milk")
    await h.call("print_label", as_="writer", target="stock_entry", ref=1)
    await h.call("print_shopping_list", as_="writer")
    assert fake.printed == [
        "/stock/products/1/printlabel",
        "/stock/entry/1/printlabel",
        "/print/shoppinglist/thermal",
    ]
    assert "integer" in await h.error("print_label", as_="writer", target="stock_entry", ref="Milk")
    fake.label_printer = False
    assert "not configured" in await h.error("print_label", as_="writer", target="chore", ref=1)
    assert (await h.call("calendar_sharing_link", as_="admin"))["url"].endswith("secret=abc123")


async def test_workflow_apply(h: Harness, fake: FakeGrocy) -> None:
    preview = await h.call(
        "workflow_stock_intake_preview",
        as_="writer",
        items=[
            {"name": "Eggs", "amount": 6},
            {"name": "Flour", "amount": 2, "best_before_date": "2027-01-01"},
        ],
    )
    out = await h.call("workflow_stock_intake_apply", as_="writer", items=preview["apply_items"])
    assert [a["product_id"] for a in out["applied"]] == [3, 4] and all(
        a["transaction_id"] for a in out["applied"]
    )
    assert (amount(fake, 3), amount(fake, 4)) == (10, 3)
    msg = await h.error(
        "workflow_stock_intake_apply", as_="writer", items=[{"product_id": 99, "amount": 1}]
    )
    assert "no products with id 99" in msg
    r = await h.call(
        "workflow_shopping_reconcile_preview",
        as_="writer",
        purchased=[{"product": "Milk", "amount": 5}],
    )
    actions = [{k: v for k, v in a.items() if k != "product"} for a in r["actions"]]
    await h.call("workflow_shopping_reconcile_apply", as_="writer", actions=actions)
    assert fake.get_row("shopping_list", 1) is None
    assert "set_amount needs" in await h.error(
        "workflow_shopping_reconcile_apply",
        as_="writer",
        actions=[{"item_id": 2, "action": "set_amount"}],
    )


async def test_batch_stops_at_the_first_failure(
    h: Harness, fake: FakeGrocy, no_sleep: None
) -> None:
    fake.fail("POST", "/stock/products/3/add", "read_timeout")
    items: list[dict[str, Any]] = [
        {"product_id": 1, "amount": 1},
        {"product_id": 3, "amount": 1},
        {"product_id": 4, "amount": 1},
    ]
    msg = await h.error("workflow_stock_intake_apply", as_="writer", items=items)
    assert "applied 1 of 3 items; item 1 may or may not have been applied" in msg
    assert "items 2 to 2 were not tried" in msg
    assert fake.count("POST", "/stock/products/4/add") == 0
    assert fake.count("POST", "/stock/products/3/add") == 1


async def test_write_limit_counts_batch_items(make_harness: Any, fake: FakeGrocy) -> None:
    h = await make_harness(max_writes=3)
    await h.call("stock_add", as_="writer", product="Milk", amount=1)
    msg = await h.error(
        "workflow_stock_intake_apply", as_="writer", items=[{"product_id": 1, "amount": 1}] * 3
    )
    assert "write limit reached for this token (3 per hour)" in msg and "nothing was changed" in msg
    await h.call(
        "workflow_stock_intake_apply", as_="writer", items=[{"product_id": 1, "amount": 1}] * 2
    )
    assert "write limit" in await h.error("shopping_list_add", as_="writer", note="x")
    await h.call("stock_add", as_="admin", product="Milk", amount=1)  # other tokens unaffected
    assert (await h.call("stock_overview", as_="writer"))["products"]  # reads never limited


@pytest.mark.parametrize(
    "tool", ["task_delete", "entity_delete", "shopping_list_clear", "file_delete"]
)
async def test_write_tokens_cannot_call_full_tools(h: Harness, fake: FakeGrocy, tool: str) -> None:
    before = len(fake.requests)
    assert "Unknown tool" in await h.error(
        tool, as_="writer", task_id=1, entity="tasks", id=1, group="userfiles", file_name="x"
    )
    assert len(fake.requests) == before
