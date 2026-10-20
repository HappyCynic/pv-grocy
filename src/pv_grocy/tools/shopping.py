# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Shopping list reads."""

from __future__ import annotations

from typing import Annotated, Any

from ..resolve import Ref, names, resolve
from ..tooling import (
    LIMIT_DEFAULT,
    PAGING_NOTE,
    Limit,
    Offset,
    ToolGroup,
    flag,
    grocy,
    paged,
    ref_field,
)

TOOLS = ToolGroup()

DEFAULT_LIST_ID = 1


async def list_items(list_id: int) -> list[dict[str, Any]]:
    rows = await grocy().objects("shopping_list", query=[f"shopping_list_id={list_id}"])
    products, units = await names("products"), await names("quantity_units")
    return [
        {
            "item_id": r.get("id"),
            "product_id": r.get("product_id"),
            "product": products.get(r.get("product_id") or 0),
            "amount": r.get("amount"),
            "unit": units.get(r.get("qu_id") or 0),
            "note": r.get("note"),
            "done": flag(r.get("done")),
        }
        for r in rows
    ]


@TOOLS.read(
    "Items on a shopping list (default: the first list), with item_id, product, amount, "
    "unit, note and whether it is ticked off. Item ids are for shopping_list_update and "
    "shopping_list_remove; list names and ids are in entity_list(entity='shopping_lists'). "
    f"At most {LIMIT_DEFAULT} items per page by default. " + PAGING_NOTE
)
async def shopping_list_view(
    shopping_list: Annotated[Ref, ref_field("shopping list")] = DEFAULT_LIST_ID,
    include_done: bool = True,
    limit: Limit = LIMIT_DEFAULT,
    offset: Offset = 0,
) -> dict[str, Any]:
    sl = await resolve("shopping_list", shopping_list)
    items = await list_items(int(sl["id"]))
    if not include_done:
        items = [i for i in items if not i["done"]]
    return paged("items", items, limit, offset, list={"id": sl["id"], "name": sl.get("name")})
