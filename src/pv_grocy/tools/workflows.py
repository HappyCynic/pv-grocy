# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Preview halves of the batch workflows (receipt intake, shopping reconcile). They change
nothing; their output is what the matching *_apply tool takes, after the user confirms."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..errors import ToolInputError
from ..resolve import Ref, names, resolve
from ..tooling import Date, ToolGroup, flag, grocy
from .shopping import DEFAULT_LIST_ID, list_items

TOOLS = ToolGroup()

BATCH_MAX = 50
CANDIDATES_MAX = 5
MIN_WORD = 3


class ExternalItem(BaseModel):
    """An item from a receipt, a message or a photo, already turned into fields."""

    model_config = ConfigDict(extra="forbid")
    name: Annotated[str | None, Field(max_length=200)] = None
    barcode: Annotated[str | None, Field(max_length=200)] = None
    amount: Annotated[float, Field(gt=0, le=100_000)] = 1
    best_before_date: Date | None = None
    price: Annotated[float | None, Field(ge=0, description="Per unit")] = None

    @model_validator(mode="after")
    def _named(self) -> ExternalItem:
        if not (self.name and self.name.strip()) and not (self.barcode and self.barcode.strip()):
            raise ValueError("each item needs a name or a barcode")
        return self


class Purchased(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product: Annotated[Ref, Field(description="Product id or exact name")]
    amount: Annotated[float, Field(gt=0, le=100_000)]


def _norm(s: Any) -> str:
    return " ".join(str(s or "").split()).casefold()


async def match_items(items: list[ExternalItem]) -> list[dict[str, Any]]:
    g = grocy()
    products = {int(p["id"]): p for p in await g.objects("products") if flag(p.get("active", 1))}
    by_barcode = {
        _norm(b.get("barcode")): int(b["product_id"]) for b in await g.objects("product_barcodes")
    }
    out = []
    for i, item in enumerate(items):
        result: dict[str, Any] = {"index": i, "input": item.model_dump(exclude_none=True)}
        pid = by_barcode.get(_norm(item.barcode)) if item.barcode else None
        if pid in products:
            result |= {
                "status": "matched",
                "matched_by": "barcode",
                "product": {"id": pid, "name": products[pid].get("name")},
            }
            out.append(result)
            continue
        name = _norm(item.name)
        exact = [p for p in products.values() if _norm(p.get("name")) == name] if name else []
        if len(exact) == 1:
            result |= {
                "status": "matched",
                "matched_by": "name",
                "product": {"id": exact[0]["id"], "name": exact[0].get("name")},
            }
        else:
            pool = exact or [p for p in products.values() if name and name in _norm(p.get("name"))]
            if not pool and name:
                words = [w for w in name.split() if len(w) >= MIN_WORD]
                pool = [
                    p for p in products.values() if any(w in _norm(p.get("name")) for w in words)
                ]
            result |= {
                "status": "ambiguous" if pool else "unmatched",
                "candidates": [
                    {"id": p["id"], "name": p.get("name")} for p in pool[:CANDIDATES_MAX]
                ],
            }
        out.append(result)
    return out


ItemsArg = Annotated[list[ExternalItem], Field(min_length=1, max_length=BATCH_MAX)]


@TOOLS.read(
    "Match items from a receipt, message or photo (each with a name and/or barcode) to "
    f"Grocy products, at most {BATCH_MAX} items. Never guesses: `matched` is an exact barcode "
    "or exact name; otherwise `ambiguous` with up to 5 candidates, or `unmatched`. Changes "
    "nothing."
)
async def workflow_match_products(items: ItemsArg) -> dict[str, Any]:
    return {"matches": await match_items(items)}


@TOOLS.read(
    "Preview adding purchased items to stock (the 'I bought these' workflow), at most "
    f"{BATCH_MAX} items. Matches each item like workflow_match_products and returns "
    "`apply_items`: the stock additions for matched items, ready for "
    "workflow_stock_intake_apply once the user has confirmed them (and resolved the "
    "unmatched ones). Amounts are in each product's stock unit; `unit_check` flags products "
    "whose purchase unit differs. Changes nothing."
)
async def workflow_stock_intake_preview(items: ItemsArg) -> dict[str, Any]:
    g = grocy()
    matches = await match_items(items)
    units, locations = await names("quantity_units"), await names("locations")
    amounts = {r["product_id"]: r.get("amount") for r in await g.get("/stock") or []}
    apply_items = []
    for m in matches:
        if m["status"] != "matched":
            continue
        pid = int(m["product"]["id"])
        p = await g.object("products", pid)
        item = items[m["index"]]
        stock_unit, purchase_unit = (
            units.get(p.get("qu_id_stock") or 0),
            units.get(p.get("qu_id_purchase") or 0),
        )
        m["product"] |= {
            "in_stock": amounts.get(pid, 0),
            "stock_unit": stock_unit,
            "default_location": locations.get(p.get("location_id") or 0),
            "unit_check": stock_unit != purchase_unit,
        }
        apply_items.append(
            {
                "product_id": pid,
                "amount": item.amount,
                "best_before_date": item.best_before_date,
                "price": item.price,
            }
        )
    return {
        "matches": matches,
        "apply_items": [{k: v for k, v in a.items() if v is not None} for a in apply_items],
        "unresolved": [m["index"] for m in matches if m["status"] != "matched"],
    }


@TOOLS.read(
    "Preview updating a shopping list after shopping: for each purchased product (id or "
    f"exact name, at most {BATCH_MAX}), the list items to remove or reduce. Returns `actions` "
    "ready for workflow_shopping_reconcile_apply once the user has confirmed them. Changes "
    "nothing."
)
async def workflow_shopping_reconcile_preview(
    purchased: Annotated[list[Purchased], Field(min_length=1, max_length=BATCH_MAX)],
    shopping_list: Annotated[
        Ref, Field(description="Shopping list id or exact name")
    ] = DEFAULT_LIST_ID,
) -> dict[str, Any]:
    sl = await resolve("shopping_list", shopping_list)
    items = [i for i in await list_items(int(sl["id"])) if not i["done"]]
    actions, not_on_list, errors = [], [], []
    for n, p in enumerate(purchased):
        try:
            product = await resolve("product", p.product)
        except ToolInputError as exc:  # report per item, keep going
            errors.append({"index": n, "error": str(exc)})
            continue
        left = p.amount
        mine = [i for i in items if i["product_id"] == product["id"]]
        if not mine:
            not_on_list.append({"index": n, "product": product.get("name")})
        for i in mine:
            if left <= 0:
                break
            have = float(i["amount"] or 0)
            if left >= have:
                actions.append(
                    {"item_id": i["item_id"], "action": "remove", "product": i["product"]}
                )
                left -= have
            else:
                actions.append(
                    {
                        "item_id": i["item_id"],
                        "action": "set_amount",
                        "amount": round(have - left, 4),
                        "product": i["product"],
                    }
                )
                left = 0
    return {
        "list": {"id": sl["id"], "name": sl.get("name")},
        "actions": actions,
        "not_on_list": not_on_list,
        "errors": errors,
    }
