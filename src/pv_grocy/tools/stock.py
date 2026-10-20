# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Stock reads: what is in stock, what is due, one product, its entries, search, journal."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..resolve import Ref, names, resolve, resolve_id
from ..tooling import (
    LIMIT_DEFAULT,
    PAGING_NOTE,
    Limit,
    Offset,
    ToolGroup,
    flag,
    grocy,
    paged,
    pick,
    ref_field,
)

TOOLS = ToolGroup()

DUE_DAYS_MAX = 365
JOURNAL_LIMIT_DEFAULT = 25
SEARCH_LIMIT_DEFAULT = 20
TRANSACTION_ID = Field(pattern=r"^[0-9a-f]{6,32}$", description="transaction_id from the journal")


def stock_row(row: dict[str, Any], units: dict[int, str]) -> dict[str, Any]:
    """One line of GET /stock or /stock/volatile."""
    product = row.get("product") or {}
    return {
        "product_id": row.get("product_id"),
        "name": product.get("name"),
        "amount": row.get("amount"),
        "amount_opened": row.get("amount_opened"),
        "unit": units.get(product.get("qu_id_stock") or 0),
        "next_due_date": row.get("best_before_date"),
        "value": row.get("value"),
        "min_stock_amount": product.get("min_stock_amount"),
    }


@TOOLS.read(
    "What is in stock: one line per product with amount, opened amount, stock unit, next "
    "due date and value. `location` limits it to products stored there. "
    f"At most {LIMIT_DEFAULT} products per page by default. " + PAGING_NOTE
)
async def stock_overview(
    location: Annotated[Ref | None, ref_field("location")] = None,
    limit: Limit = LIMIT_DEFAULT,
    offset: Offset = 0,
) -> dict[str, Any]:
    g = grocy()
    rows = await g.get("/stock") or []
    units = await names("quantity_units")
    lines = [stock_row(r, units) for r in rows]
    where = None
    if location is not None:
        loc = await resolve("location", location)
        where = {"id": loc["id"], "name": loc.get("name")}
        entries = await g.get(f"/stock/locations/{loc['id']}/entries") or []
        here: dict[int, float] = {}
        for e in entries:
            here[e["product_id"]] = here.get(e["product_id"], 0) + float(e.get("amount") or 0)
        lines = [
            dict(line, amount_here=here[line["product_id"]])
            for line in lines
            if line["product_id"] in here
        ]
    lines.sort(key=lambda line: str(line["name"]).casefold())
    return paged("products", lines, limit, offset, location=where)


@TOOLS.read(
    "Products that need attention: due soon (within `days`, default 5), overdue, expired, "
    "and below their minimum stock amount (`missing`). Use for a daily check or to decide "
    "what to use up or buy."
)
async def stock_due(
    days: Annotated[int, Field(ge=0, le=DUE_DAYS_MAX)] = 5,
) -> dict[str, Any]:
    data = await grocy().get("/stock/volatile", {"due_soon_days": days}) or {}
    units = await names("quantity_units")
    return {
        "days": days,
        "due_soon": [stock_row(r, units) for r in data.get("due_products") or []],
        "overdue": [stock_row(r, units) for r in data.get("overdue_products") or []],
        "expired": [stock_row(r, units) for r in data.get("expired_products") or []],
        "missing": [
            {
                "product_id": m.get("id"),
                "name": m.get("name"),
                "amount_missing": m.get("amount_missing"),
                "partly_in_stock": flag(m.get("is_partly_in_stock")),
            }
            for m in data.get("missing_products") or []
        ],
    }


@TOOLS.read(
    "Everything about one product's stock: amounts (total, opened, per location), stock "
    "unit, next due date, last purchase and use, last and average price, barcodes, default "
    "location, minimum stock amount, and whether tare weight handling is on (then stock "
    "changes take the gross weight including the container)."
)
async def stock_product(
    product: Annotated[Ref, ref_field("product")],
) -> dict[str, Any]:
    g = grocy()
    pid = await resolve_id("product", product)
    d = await g.get(f"/stock/products/{pid}") or {}
    locs = await g.get(f"/stock/products/{pid}/locations") or []
    p = d.get("product") or {}
    location_names = await names("locations")
    return {
        "product": pick(p, "id", "name", "description", "min_stock_amount", "active")
        | {
            "default_location": location_names.get(p.get("location_id") or 0),
            "parent_product_id": p.get("parent_product_id"),
            "tare_weight_handling": flag(p.get("enable_tare_weight_handling")),
        },
        "unit": (d.get("quantity_unit_stock") or {}).get("name"),
        "amount": d.get("stock_amount"),
        "amount_opened": d.get("stock_amount_opened"),
        "amount_aggregated": d.get("stock_amount_aggregated"),
        "value": d.get("stock_value"),
        "next_due_date": d.get("next_due_date"),
        "last_purchased": d.get("last_purchased"),
        "last_used": d.get("last_used"),
        "last_price": d.get("last_price"),
        "average_price": d.get("avg_price"),
        "locations": [
            {
                "location_id": loc.get("location_id"),
                "name": loc.get("location_name"),
                "amount": loc.get("amount"),
            }
            for loc in locs
        ],
        "barcodes": [b.get("barcode") for b in d.get("product_barcodes") or []],
    }


@TOOLS.read(
    "A product's individual stock entries (one per purchase), oldest due first: entry id, "
    "amount, due date, purchase date, location, opened, price and note. Entry ids are for "
    f"print_label. At most {LIMIT_DEFAULT} per page by default. " + PAGING_NOTE
)
async def stock_entries(
    product: Annotated[Ref, ref_field("product")],
    limit: Limit = LIMIT_DEFAULT,
    offset: Offset = 0,
) -> dict[str, Any]:
    pid = await resolve_id("product", product)
    rows = await grocy().get(f"/stock/products/{pid}/entries") or []
    location_names = await names("locations")
    entries = [
        pick(r, "id", "amount", "best_before_date", "purchased_date", "price", "note")
        | {"location": location_names.get(r.get("location_id") or 0), "opened": flag(r.get("open"))}
        for r in rows
    ]
    return paged("entries", entries, limit, offset, product_id=pid)


@TOOLS.read(
    "Find products by part of their name or by barcode, with the amount in stock. Use it "
    "when you do not know a product's exact name; other tools need the exact name or id. "
    f"At most {SEARCH_LIMIT_DEFAULT} results by default. " + PAGING_NOTE
)
async def stock_search(
    query: Annotated[str, Field(min_length=1, max_length=200)],
    include_inactive: bool = False,
    limit: Limit = SEARCH_LIMIT_DEFAULT,
    offset: Offset = 0,
) -> dict[str, Any]:
    g = grocy()
    q = query.strip()
    products = {int(p["id"]): p for p in await g.objects("products", query=[f"name~{q}"])}
    matched_by = dict.fromkeys(products, "name")
    for b in await g.objects("product_barcodes", query=[f"barcode~{q}"]):
        pid = int(b["product_id"])
        if pid not in products:
            products[pid] = await g.object("products", pid)
            matched_by[pid] = "barcode"
    if not include_inactive:
        products = {k: v for k, v in products.items() if flag(v.get("active", 1))}
    amounts = {r["product_id"]: r.get("amount") for r in await g.get("/stock") or []}
    results = sorted(
        (
            {
                "id": pid,
                "name": p.get("name"),
                "matched_by": matched_by[pid],
                "amount_in_stock": amounts.get(pid, 0),
                "active": flag(p.get("active", 1)),
            }
            for pid, p in products.items()
        ),
        key=lambda r: (str(r["name"]).casefold() != q.casefold(), str(r["name"]).casefold()),
    )
    return paged("products", results, limit, offset)


@TOOLS.read(
    "Look up a product by its exact barcode, with its stock amount and due date. For part "
    "of a barcode or a name, use stock_search."
)
async def stock_barcode_lookup(
    barcode: Annotated[str, Field(min_length=1, max_length=200)],
) -> dict[str, Any]:
    d = await grocy().get(f"/stock/products/by-barcode/{barcode.strip()}") or {}
    p = d.get("product") or {}
    return {
        "product": pick(p, "id", "name"),
        "unit": (d.get("quantity_unit_stock") or {}).get("name"),
        "amount": d.get("stock_amount"),
        "amount_opened": d.get("stock_amount_opened"),
        "next_due_date": d.get("next_due_date"),
    }


def journal_row(
    r: dict[str, Any], products: dict[int, str], locations: dict[int, str]
) -> dict[str, Any]:
    return {
        "id": r.get("id"),
        "transaction_id": r.get("transaction_id"),
        "time": r.get("row_created_timestamp"),
        "type": r.get("transaction_type"),
        "product_id": r.get("product_id"),
        "product": products.get(r.get("product_id") or 0),
        "amount": r.get("amount"),
        "location": locations.get(r.get("location_id") or 0),
        "spoiled": flag(r.get("spoiled")),
        "recipe_id": r.get("recipe_id"),
        "undone": flag(r.get("undone")),
    }


@TOOLS.read(
    "The stock journal, newest first: every purchase, consumption, transfer, opening and "
    "inventory correction, with its transaction_id (stock_undo reverts one) and whether it "
    "was undone. Filter by `product` or by `transaction_id`. "
    f"At most {JOURNAL_LIMIT_DEFAULT} per page by default. " + PAGING_NOTE
)
async def stock_journal(
    product: Annotated[Ref | None, ref_field("product")] = None,
    transaction_id: Annotated[str | None, TRANSACTION_ID] = None,
    limit: Limit = JOURNAL_LIMIT_DEFAULT,
    offset: Offset = 0,
) -> dict[str, Any]:
    query = []
    if product is not None:
        query.append(f"product_id={await resolve_id('product', product)}")
    if transaction_id is not None:
        query.append(f"transaction_id={transaction_id}")
    rows = await grocy().objects(
        "stock_log", query=query, order="id:desc", limit=limit + 1, offset=offset
    )
    products, locations = await names("products"), await names("locations")
    more = len(rows) > limit
    return {
        "entries": [journal_row(r, products, locations) for r in rows[:limit]],
        "next_offset": offset + limit if more else None,
    }
