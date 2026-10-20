# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Stock changes. Each one is a single Grocy booking with a transaction_id that stock_undo
reverts."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..errors import ToolInputError
from ..resolve import Ref, resolve, resolve_id, resolve_optional
from ..tooling import (
    WRITE_NOTE,
    Amount,
    Date,
    ToolGroup,
    grocy,
    ref_field,
    require,
    writer,
)
from ..tools.stock import TRANSACTION_ID

TOOLS = ToolGroup()

UNDO_HINT = "Each change returns a transaction_id; stock_undo reverts it."
TARE_NOTE = (
    "For a product with tare weight handling (stock_product shows it), Grocy expects the "
    "gross weight including the container."
)


async def _after(pid: int) -> dict[str, Any]:
    d = await grocy().get(f"/stock/products/{pid}") or {}
    return {
        "amount": d.get("stock_amount"),
        "amount_opened": d.get("stock_amount_opened"),
        "unit": (d.get("quantity_unit_stock") or {}).get("name"),
    }


def _booked(rows: Any) -> dict[str, Any]:
    rows = rows if isinstance(rows, list) else []
    ids = sorted({str(r.get("transaction_id")) for r in rows if r.get("transaction_id")})
    return {
        "transaction_id": ids[0] if len(ids) == 1 else None,
        "transaction_ids": ids,
        "bookings": len(rows),
    }


async def _product(ref: Ref) -> dict[str, Any]:
    return await resolve("product", ref)


@TOOLS.write(
    "Add stock of a product (e.g. after buying it): `amount` in the product's stock unit, "
    "optional due date (default: the product's default), price per unit, location (default: "
    "the product's default location) and store. " + TARE_NOTE + " " + UNDO_HINT + " " + WRITE_NOTE
)
async def stock_add(
    product: Annotated[Ref, ref_field("product")],
    amount: Amount,
    best_before_date: Date | None = None,
    price: Annotated[float | None, Field(ge=0, description="Price per stock unit")] = None,
    location: Annotated[Ref | None, ref_field("location")] = None,
    store: Annotated[Ref | None, ref_field("store (shopping location)")] = None,
) -> dict[str, Any]:
    p = await _product(product)
    body: dict[str, Any] = {"amount": amount, "transaction_type": "purchase"}
    if best_before_date:
        body["best_before_date"] = best_before_date
    if price is not None:
        body["price"] = price
    if (loc := await resolve_optional("location", location)) is not None:
        body["location_id"] = loc
    if (shop := await resolve_optional("shopping_location", store)) is not None:
        body["shopping_location_id"] = shop
    rows = await writer().post(f"/stock/products/{p['id']}/add", body)
    return {
        "product": {"id": p["id"], "name": p.get("name")},
        "added": amount,
        **_booked(rows),
        "now_in_stock": await _after(int(p["id"])),
    }


@TOOLS.write(
    "Consume stock of a product (used up, or thrown away with `spoiled`), oldest due first, "
    "optionally only from `location`. Grocy refuses more than is in stock. "
    + TARE_NOTE
    + " "
    + UNDO_HINT
    + " "
    + WRITE_NOTE
)
async def stock_consume(
    product: Annotated[Ref, ref_field("product")],
    amount: Amount,
    spoiled: bool = False,
    location: Annotated[Ref | None, ref_field("location")] = None,
) -> dict[str, Any]:
    p = await _product(product)
    body: dict[str, Any] = {"amount": amount, "spoiled": spoiled, "transaction_type": "consume"}
    if (loc := await resolve_optional("location", location)) is not None:
        body["location_id"] = loc
    rows = await writer().post(f"/stock/products/{p['id']}/consume", body)
    return {
        "product": {"id": p["id"], "name": p.get("name")},
        "consumed": amount,
        "spoiled": spoiled,
        **_booked(rows),
        "now_in_stock": await _after(int(p["id"])),
    }


@TOOLS.write(
    "Mark units of a product as opened (e.g. an opened bottle of milk), which can shorten "
    "its due date. " + UNDO_HINT + " " + WRITE_NOTE
)
async def stock_open(
    product: Annotated[Ref, ref_field("product")],
    amount: Amount = 1,
) -> dict[str, Any]:
    p = await _product(product)
    rows = await writer().post(f"/stock/products/{p['id']}/open", {"amount": amount})
    return {
        "product": {"id": p["id"], "name": p.get("name")},
        "opened": amount,
        **_booked(rows),
        "now_in_stock": await _after(int(p["id"])),
    }


@TOOLS.write(
    "Move stock of a product to another location. `from_location` may be left out when the "
    "product is stored in only one place. " + UNDO_HINT + " " + WRITE_NOTE
)
async def stock_transfer(
    product: Annotated[Ref, ref_field("product")],
    amount: Amount,
    to_location: Annotated[Ref, ref_field("location")],
    from_location: Annotated[Ref | None, ref_field("location")] = None,
) -> dict[str, Any]:
    p = await _product(product)
    to_id = await resolve_id("location", to_location)
    from_id = await resolve_optional("location", from_location)
    if from_id is None:
        here = await grocy().get(f"/stock/products/{p['id']}/locations") or []
        if len(here) != 1:
            where = ", ".join(f"{h.get('location_name')} (id {h.get('location_id')})" for h in here)
            raise ToolInputError(
                f"{p.get('name')} is stored in {len(here)} locations"
                + (f" ({where})" if where else "")
                + "; give from_location"
            )
        from_id = int(here[0]["location_id"])
    require(from_id != to_id, "from_location and to_location are the same")
    rows = await writer().post(
        f"/stock/products/{p['id']}/transfer",
        {"amount": amount, "location_id_from": from_id, "location_id_to": to_id},
    )
    return {
        "product": {"id": p["id"], "name": p.get("name")},
        "moved": amount,
        "from_location_id": from_id,
        "to_location_id": to_id,
        **_booked(rows),
    }


@TOOLS.write(
    "Correct a product's stock to an absolute amount after counting it (an inventory "
    "correction): this replaces the current amount, it does not add to it. Optional due "
    "date and location apply to any amount added. " + TARE_NOTE + " " + UNDO_HINT + " " + WRITE_NOTE
)
async def stock_inventory(
    product: Annotated[Ref, ref_field("product")],
    new_amount: Annotated[float, Field(ge=0, le=1_000_000)],
    best_before_date: Date | None = None,
    location: Annotated[Ref | None, ref_field("location")] = None,
) -> dict[str, Any]:
    p = await _product(product)
    before = await _after(int(p["id"]))
    body: dict[str, Any] = {"new_amount": new_amount}
    if best_before_date:
        body["best_before_date"] = best_before_date
    if (loc := await resolve_optional("location", location)) is not None:
        body["location_id"] = loc
    rows = await writer().post(f"/stock/products/{p['id']}/inventory", body)
    return {
        "product": {"id": p["id"], "name": p.get("name")},
        "was": before.get("amount"),
        **_booked(rows),
        "now_in_stock": await _after(int(p["id"])),
    }


@TOOLS.write(
    "Undo one stock booking (add, consume, open, transfer or inventory correction) by its "
    "transaction_id, from the result of that change or from stock_journal. Grocy refuses a "
    "transaction that was already undone. " + WRITE_NOTE
)
async def stock_undo(
    transaction_id: Annotated[str, TRANSACTION_ID],
) -> dict[str, Any]:
    rows = await grocy().objects("stock_log", query=[f"transaction_id={transaction_id}"])
    require(bool(rows), f"no stock transaction {transaction_id}")
    await writer().post(f"/stock/transactions/{transaction_id}/undo")
    return {
        "undone": transaction_id,
        "bookings": len(rows),
        "product_ids": sorted({r.get("product_id") for r in rows}),
    }
