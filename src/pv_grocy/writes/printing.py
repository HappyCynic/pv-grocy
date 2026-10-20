# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Label and thermal printing (Grocy's print endpoints are GETs with a side effect)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from ..resolve import Ref, resolve_id
from ..tooling import PRINTS, ToolGroup, require, writer

TOOLS = ToolGroup()

PRINT_NOTE = "Needs label printing set up in Grocy; it prints on a physical printer."


@TOOLS.write(
    "Print a Grocy label for a product, recipe, chore or battery (by id or exact name), or "
    "for one stock entry (by the entry id stock_entries shows). " + PRINT_NOTE,
    annotations=PRINTS,
)
async def print_label(
    target: Literal["product", "recipe", "chore", "battery", "stock_entry"],
    ref: Annotated[Ref, Field(description="Id or exact name (stock_entry: the entry id)")],
) -> dict[str, Any]:
    if target == "stock_entry":
        require(
            isinstance(ref, int) and not isinstance(ref, bool) and ref > 0,
            "a stock entry is given by its id (an integer)",
        )
        path = f"/stock/entry/{ref}/printlabel"
    else:
        oid = await resolve_id(target, ref)
        base = {
            "product": "/stock/products",
            "recipe": "/recipes",
            "chore": "/chores",
            "battery": "/batteries",
        }[target]
        path = f"{base}/{oid}/printlabel"
    await writer().print_trigger(path)
    return {"printed": target, "path": path}


@TOOLS.write(
    "Print the shopping list on Grocy's thermal printer. " + PRINT_NOTE,
    annotations=PRINTS,
)
async def print_shopping_list() -> dict[str, Any]:
    await writer().print_trigger("/print/shoppinglist/thermal")
    return {"printed": "shopping_list"}
