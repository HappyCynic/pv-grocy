# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64

import pytest

from pv_grocy.errors import GrocyRejected

from .conftest import Harness
from .fakegrocy import FakeGrocy


async def test_stock_overview_paging_and_location(h: Harness) -> None:
    out = await h.call("stock_overview", as_="reader", limit=2)
    assert [p["name"] for p in out["products"]] == ["Eggs", "Flour"]
    assert out["total"] == 3 and out["next_offset"] == 2
    last = await h.call("stock_overview", as_="reader", limit=2, offset=2)
    assert [p["name"] for p in last["products"]] == ["Milk"] and last["next_offset"] is None
    pantry = await h.call("stock_overview", as_="reader", location="pantry")
    assert [(p["name"], p["amount_here"]) for p in pantry["products"]] == [("Flour", 1)]
    assert pantry["location"] == {"id": 2, "name": "Pantry"}


async def test_stock_due(h: Harness) -> None:
    out = await h.call("stock_due", as_="reader", days=5)
    assert [p["name"] for p in out["due_soon"]] == ["Milk"]
    assert {m["name"] for m in out["missing"]} == {"Eggs"}


async def test_stock_product_entries_search_barcode(h: Harness) -> None:
    p = await h.call("stock_product", as_="reader", product="Milk")
    assert p["amount"] == 2 and p["unit"] == "Bottle" and p["barcodes"] == ["4000000000001"]
    assert p["locations"] == [{"location_id": 1, "name": "Fridge", "amount": 2}]
    e = await h.call("stock_entries", as_="reader", product=1)
    assert e["entries"][0]["location"] == "Fridge" and e["entries"][0]["opened"] is False
    s = await h.call("stock_search", as_="reader", query="milk")
    assert [r["name"] for r in s["products"]] == ["Milk", "Almond milk"]  # exact first
    s = await h.call("stock_search", as_="reader", query="40000")
    assert s["products"][0]["matched_by"] == "barcode"
    assert (await h.call("stock_search", as_="reader", query="cheese"))["products"] == []
    assert (
        len(
            (await h.call("stock_search", as_="reader", query="cheese", include_inactive=True))[
                "products"
            ]
        )
        == 1
    )
    b = await h.call("stock_barcode_lookup", as_="reader", barcode="4000000000001")
    assert b["product"] == {"id": 1, "name": "Milk"} and b["amount"] == 2
    assert "No product with barcode" in await h.error(
        "stock_barcode_lookup", as_="reader", barcode="1"
    )


async def test_stock_journal_filters_and_paging(h: Harness) -> None:
    for _ in range(3):
        await h.call("stock_add", product="Flour", amount=1)
    tx = (await h.call("stock_add", product="Milk", amount=1))["transaction_id"]
    j = await h.call("stock_journal", as_="reader", limit=2)
    assert len(j["entries"]) == 2 and j["next_offset"] == 2 and j["entries"][0]["product"] == "Milk"
    assert len((await h.call("stock_journal", as_="reader", product="Flour"))["entries"]) == 3
    assert (await h.call("stock_journal", as_="reader", transaction_id=tx))["entries"][0][
        "transaction_id"
    ] == tx


async def test_fake_price_history_matches_grocy(h: Harness, fake: FakeGrocy) -> None:
    assert h.runtime.services is not None
    reader = h.runtime.services.reader
    rows = await reader.get("/stock/products/1/price-history")
    # Newest first; the purchase without a price and the undone one are left out.
    assert [(r["date"], r["price"]) for r in rows] == [
        ("2026-10-15", 1.2),
        ("2026-10-01", 1.49),
        ("2026-09-12", 0.99),
    ]
    assert [set(r) for r in rows] == [{"date", "price", "shopping_location"}] * 3
    assert rows[0]["shopping_location"] == {"id": 2, "name": "Market"}
    assert rows[1]["shopping_location"] is None
    assert await reader.get("/stock/products/2/price-history") == []
    await h.call("stock_add", product="Almond milk", amount=1, price=2.5, store="Market")
    await h.call("stock_add", product="Almond milk", amount=1)  # no price: not in the history
    tx = (await h.call("stock_add", product="Almond milk", amount=1, price=9))["transaction_id"]
    await h.call("stock_undo", transaction_id=tx)
    rows = await reader.get("/stock/products/2/price-history")
    assert rows == [
        {"date": "2026-10-20", "price": 2.5, "shopping_location": {"id": 2, "name": "Market"}}
    ]
    with pytest.raises(GrocyRejected, match="does not exist"):  # Grocy answers 400
        await reader.get("/stock/products/99/price-history")
    assert fake.requests[-1] == ("GET", "/stock/products/99/price-history")


MILK_PRICES = [
    {"date": "2026-10-15", "price": 1.2, "store": "Market"},
    {"date": "2026-10-01", "price": 1.49, "store": None},
    {"date": "2026-09-12", "price": 0.99, "store": "Corner shop"},
]


async def test_stock_price_history_by_name_and_id(h: Harness) -> None:
    out = await h.call("stock_price_history", as_="reader", product="Milk")
    assert out["product"] == {"id": 1, "name": "Milk"} and out["unit"] == "Bottle"
    assert out["prices"] == MILK_PRICES  # newest first; the second one has no store
    assert (out["total"], out["next_offset"]) == (3, None)
    assert out["lowest"] == MILK_PRICES[2]
    assert out["highest"] == MILK_PRICES[1]
    assert out["latest"] == MILK_PRICES[0]
    by_id = await h.call("stock_price_history", as_="reader", product=1)
    assert by_id["product"] == out["product"] and by_id["prices"] == MILK_PRICES


async def test_stock_price_history_partial_name_is_not_looked_up(
    h: Harness, fake: FakeGrocy
) -> None:
    msg = await h.error("stock_price_history", as_="reader", product="almond")
    assert "no product is named exactly 'almond'" in msg and "'Almond milk' (id 2)" in msg
    assert not [p for _m, p in fake.requests if p.endswith("/price-history")]


async def test_stock_price_history_pages_keep_the_summary(h: Harness) -> None:
    out = await h.call("stock_price_history", as_="reader", product="Milk", limit=1, offset=1)
    assert out["prices"] == [MILK_PRICES[1]] and out["next_offset"] == 2
    assert (out["lowest"], out["highest"], out["latest"]) == (
        MILK_PRICES[2],
        MILK_PRICES[1],
        MILK_PRICES[0],
    )
    out = await h.call("stock_price_history", as_="reader", product="Milk", limit=2)
    assert out["prices"] == MILK_PRICES[:2] and out["total"] == 3 and out["next_offset"] == 2


async def test_stock_price_history_ties_report_the_most_recent(h: Harness) -> None:
    # Lowest price (0.99) at Corner shop in September, then at Market in October.
    await h.call("stock_add", product="Milk", amount=1, price=0.99, store="Market")
    out = await h.call("stock_price_history", as_="reader", product="Milk")
    assert out["lowest"] == {"date": "2026-10-20", "price": 0.99, "store": "Market"}
    assert out["latest"] == out["lowest"] and out["total"] == 4


async def test_stock_price_history_never_bought(h: Harness) -> None:
    out = await h.call("stock_price_history", as_="reader", product="Almond milk")
    assert out["prices"] == [] and out["total"] == 0 and out["next_offset"] is None
    assert out["lowest"] is None and out["highest"] is None and out["latest"] is None


async def test_shopping_list_view(h: Harness) -> None:
    out = await h.call("shopping_list_view", as_="reader")
    assert out["list"] == {"id": 1, "name": "Shopping list"}
    assert [(i["product"], i["note"], i["unit"]) for i in out["items"]] == [
        ("Milk", None, "Bottle"),
        (None, "Candles", None),
    ]
    assert (await h.call("shopping_list_view", as_="reader", shopping_list="Hardware"))[
        "items"
    ] == []


async def test_recipes(h: Harness) -> None:
    d = await h.call("recipe_details", as_="reader", recipe="Pancakes")
    assert d["description"] == "Mix well."  # HTML to text, script dropped
    assert [(i["product"], i["amount"], i["enough_in_stock"]) for i in d["ingredients"]] == [
        ("Milk", 1, True),
        ("Eggs", 2, True),
        ("Flour", 3, False),
    ]
    f = await h.call("recipe_fulfillment", as_="reader", recipe=1)
    assert f["can_be_made"] is False and f["missing_products_count"] == 1
    assert [m["product"] for m in f["missing"]] == ["Flour"]
    p = await h.call("recipe_consume_preview", as_="reader", recipe=1)
    flour = next(line for line in p["consumes"] if line["product"] == "Flour")
    assert flour["would_consume"] == 1 and flour["left_after"] == 0 and p["short"] == ["Flour"]


async def test_meal_plan_and_calendar(h: Harness) -> None:
    m = await h.call("meal_plan_list", as_="reader")
    assert m["start_date"] == "2026-10-20" and m["end_date"] == "2026-10-26"
    assert [(e["recipe"], e["section"], e["servings"]) for e in m["entries"]] == [
        ("Pancakes", "Breakfast", 2)
    ]
    assert (await h.call("meal_plan_list", as_="reader", section="dinner"))["entries"] == []
    assert "end_date is before" in await h.error(
        "meal_plan_list", as_="reader", start_date="2026-10-20", end_date="2026-10-01"
    )
    assert "at most 92 days" in await h.error(
        "meal_plan_list", as_="reader", start_date="2026-01-01", end_date="2026-12-31"
    )
    c = await h.call("calendar_summary", as_="reader")
    assert [t["name"] for t in c["tasks"]] == ["Fix shelf"] and c["tasks"][0]["overdue"]
    assert c["chores"][0]["overdue"] and c["batteries"][0]["overdue"] and len(c["meal_plan"]) == 1
    page = await h.call("calendar_ical", as_="reader")
    assert page["ical"].startswith("BEGIN:VCALENDAR") and page["next_offset"] == 20_000
    text, offset = page["ical"], page["next_offset"]
    while offset is not None:
        page = await h.call("calendar_ical", as_="reader", offset=offset)
        text, offset = text + page["ical"], page["next_offset"]
    assert len(text) == page["total_chars"] and text.endswith("END:VCALENDAR\r\n")


async def test_chores_tasks_batteries_equipment(h: Harness) -> None:
    c = await h.call("chores_list", as_="reader", overdue_only=True)
    assert c["chores"][0]["name"] == "Water plants" and c["chores"][0]["assigned_to"] == "Alex"
    d = await h.call("chore_details", as_="reader", chore="water plants")
    assert d["description"] == "All of them" and d["history"][0]["execution_id"] == 1
    t = await h.call("tasks_list", as_="reader")
    assert [(x["name"], x["category"], x["assigned_to"]) for x in t["tasks"]] == [
        ("Fix shelf", "Home", "Alex")
    ]
    assert len((await h.call("tasks_list", as_="reader", include_done=True))["tasks"]) == 2
    b = await h.call("batteries_list", as_="reader", overdue_only=True)
    assert b["batteries"][0]["name"] == "Remote"
    assert (await h.call("batteries_list", as_="reader", due_within_days=0))["batteries"][0][
        "overdue"
    ]
    bd = await h.call("battery_details", as_="reader", battery="Remote")
    assert bd["history"][0]["cycle_id"] == 1
    eq = await h.call("equipment_details", as_="reader", equipment="Dishwasher")
    assert eq["description"] == "Manual\n\nRinse first" and eq["manual_file"] == "dishwasher.pdf"


async def test_generic_entities_and_search(h: Harness) -> None:
    rows = await h.call(
        "entity_list", as_="reader", entity="locations", filters=["name~fr"], order="name:desc"
    )
    assert [r["name"] for r in rows["rows"]] == ["Fridge", "Freezer"]
    assert (await h.call("entity_get", as_="reader", entity="products", id=4))["row"][
        "name"
    ] == "Flour"
    d = await h.call("entity_describe", as_="reader", entity="locations")
    assert d["fields"]["is_freezer"] == "int" and d["catalog_create_update"] and d["entity_delete"]
    for entity in ("api_keys", "sessions", "permission_hierarchy", "users"):
        assert "cannot" in await h.error("entity_list", as_="reader", entity=entity)
    for bad in ("name", "name~~x", "1d=2", "name=x{y}", "x'=1"):
        assert "invalid filter" in await h.error(
            "entity_list", as_="reader", entity="products", filters=[bad]
        )
    s = await h.call("search", as_="reader", query="mil")
    assert [(r["kind"], r["name"]) for r in s["results"]] == [
        ("product", "Almond milk"),
        ("product", "Milk"),
    ]
    s = await h.call("search", as_="reader", query="e", kinds=["location"])
    assert {r["kind"] for r in s["results"]} == {"location"}


async def test_files_and_system(h: Harness, fake: FakeGrocy) -> None:
    f = await h.call("file_download", as_="reader", group="productpictures", file_name="milk.jpg")
    assert base64.b64decode(f["content_base64"]) == b"\xff\xd8jpeg"
    assert "not found" in await h.error(
        "file_download", as_="reader", group="userfiles", file_name="x.txt"
    )
    fake.files[("userfiles", "big.bin")] = b"x" * (4 * 1024 * 1024 + 1)
    assert "larger than" in await h.error(
        "file_download", as_="reader", group="userfiles", file_name="big.bin"
    )
    s = await h.call("system_info", as_="reader")
    assert s == {**s, "grocy_version": "4.7.1", "timezone": "America/Chicago"} and "os" not in s


async def test_workflow_previews(h: Harness) -> None:
    m = await h.call(
        "workflow_match_products",
        as_="reader",
        items=[
            {"name": "milk"},
            {"name": "almond"},
            {"barcode": "4000000000001"},
            {"name": "kale"},
            {"name": "old cheese"},
        ],
    )
    assert [x["status"] for x in m["matches"]] == [
        "matched",
        "ambiguous",
        "matched",
        "unmatched",
        "unmatched",
    ]
    assert m["matches"][1]["candidates"] == [{"id": 2, "name": "Almond milk"}]
    p = await h.call(
        "workflow_stock_intake_preview",
        as_="reader",
        items=[{"name": "Eggs", "amount": 12, "price": 0.25}, {"name": "kale"}],
    )
    assert p["apply_items"] == [{"product_id": 3, "amount": 12, "price": 0.25}] and p[
        "unresolved"
    ] == [1]
    assert p["matches"][0]["product"]["unit_check"] is True  # bought in packs, stocked in pieces
    assert "needs a name or a barcode" in await h.error(
        "workflow_match_products", as_="reader", items=[{"amount": 1}]
    )
    r = await h.call(
        "workflow_shopping_reconcile_preview",
        as_="reader",
        purchased=[
            {"product": "Milk", "amount": 1},
            {"product": "Flour", "amount": 1},
            {"product": "zz", "amount": 1},
        ],
    )
    assert r["actions"] == [
        {"item_id": 1, "action": "set_amount", "amount": 1.0, "product": "Milk"}
    ]
    assert r["not_on_list"] == [{"index": 1, "product": "Flour"}] and r["errors"][0]["index"] == 2
