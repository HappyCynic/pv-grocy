# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Shopping list changes."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from ..config import Access
from ..errors import ToolInputError
from ..resolve import Ref, resolve
from ..tooling import (
    DESTROYS,
    NO_UNDO,
    SETS,
    WRITE_NOTE,
    Amount,
    Id,
    Text,
    ToolGroup,
    grocy,
    ref_field,
    require,
    writer,
)
from ..tools.shopping import DEFAULT_LIST_ID

TOOLS = ToolGroup()

ListRef = Annotated[Ref, ref_field("shopping list")]


async def _item(item_id: int) -> dict[str, Any]:
    try:
        return await grocy().object("shopping_list", item_id)
    except ToolInputError:
        raise ToolInputError(f"no shopping list item {item_id}") from None


@TOOLS.write(
    "Put a product on a shopping list (default: the first list), or a free-text item with "
    "only a `note` (e.g. 'birthday candles'). Amount is in the product's stock unit. " + WRITE_NOTE
)
async def shopping_list_add(
    product: Annotated[Ref | None, ref_field("product")] = None,
    amount: Amount = 1,
    note: Text | None = None,
    shopping_list: ListRef = DEFAULT_LIST_ID,
) -> dict[str, Any]:
    require(product is not None or bool(note and note.strip()), "give a product or a note")
    sl = await resolve("shopping_list", shopping_list)
    if product is None:
        created = await writer().post(
            "/objects/shopping_list",
            {"note": note, "amount": amount, "shopping_list_id": sl["id"]},
        )
        return {"list_id": sl["id"], "item_id": int(created["created_object_id"]), "note": note}
    p = await resolve("product", product)
    body: dict[str, Any] = {"product_id": p["id"], "list_id": sl["id"], "product_amount": amount}
    if note:
        body["note"] = note
    await writer().post("/stock/shoppinglist/add-product", body)
    return {"list_id": sl["id"], "product": {"id": p["id"], "name": p.get("name")}, "added": amount}


@TOOLS.write(
    "Change one shopping list item (by item_id from shopping_list_view): its amount, its "
    "note, or tick it off (`done`). Only the fields given change. " + WRITE_NOTE,
    annotations=SETS,
)
async def shopping_list_update(
    item_id: Id,
    amount: Amount | None = None,
    note: Text | None = None,
    done: bool | None = None,
) -> dict[str, Any]:
    await _item(item_id)
    body: dict[str, Any] = {}
    if amount is not None:
        body["amount"] = amount
    if note is not None:
        body["note"] = note
    if done is not None:
        body["done"] = 1 if done else 0
    require(bool(body), "nothing to change: give amount, note or done")
    await writer().put(f"/objects/shopping_list/{item_id}", body)
    return {"item_id": item_id, "changed": sorted(body)}


@TOOLS.write(
    "Remove one item from a shopping list (by item_id from shopping_list_view). " + WRITE_NOTE,
    annotations=DESTROYS,
)
async def shopping_list_remove(item_id: Id) -> dict[str, Any]:
    item = await _item(item_id)
    await writer().delete(f"/objects/shopping_list/{item_id}")
    return {"removed": item_id, "product_id": item.get("product_id"), "note": item.get("note")}


@TOOLS.write(
    "Add products to a shopping list in bulk: those below their minimum stock amount "
    "(`below_min_stock`, the default), those past their due date (`overdue`), or expired "
    "ones (`expired`). " + WRITE_NOTE
)
async def shopping_list_add_missing(
    which: Literal["below_min_stock", "overdue", "expired"] = "below_min_stock",
    shopping_list: ListRef = DEFAULT_LIST_ID,
) -> dict[str, Any]:
    sl = await resolve("shopping_list", shopping_list)
    path = {
        "below_min_stock": "add-missing-products",
        "overdue": "add-overdue-products",
        "expired": "add-expired-products",
    }[which]
    before = len(await grocy().objects("shopping_list", query=[f"shopping_list_id={sl['id']}"]))
    await writer().post(f"/stock/shoppinglist/{path}", {"list_id": sl["id"]})
    after = len(await grocy().objects("shopping_list", query=[f"shopping_list_id={sl['id']}"]))
    return {"list_id": sl["id"], "which": which, "items_before": before, "items_after": after}


@TOOLS.write(
    "Remove ALL items from a shopping list, or only ticked-off ones with `done_only`. "
    + NO_UNDO
    + " "
    + WRITE_NOTE,
    access=Access.FULL,
    annotations=DESTROYS,
)
async def shopping_list_clear(
    shopping_list: ListRef = DEFAULT_LIST_ID,
    done_only: bool = False,
) -> dict[str, Any]:
    sl = await resolve("shopping_list", shopping_list)
    count = len(await grocy().objects("shopping_list", query=[f"shopping_list_id={sl['id']}"]))
    await writer().post("/stock/shoppinglist/clear", {"list_id": sl["id"], "done_only": done_only})
    return {"list_id": sl["id"], "done_only": done_only, "items_before": count}
