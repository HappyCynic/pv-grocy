# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Apply halves of the batch workflows. They take only explicit ids (from a preview the
user confirmed), never names, and each item counts against the hourly write limit."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..errors import GrocyRejected, PartialWrite, ToolInputError, WriteOutcomeUnknown
from ..tooling import WRITE_NOTE, Amount, Date, Id, ToolGroup, grocy, writer
from ..tools.workflows import BATCH_MAX

TOOLS = ToolGroup()

STOP_NOTE = (
    "Items are applied in order; on the first failure it stops and reports what was applied, "
    "what failed and what was not tried, so nothing is applied twice."
)


class IntakeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: Id
    amount: Amount
    best_before_date: Date | None = None
    price: Annotated[float | None, Field(ge=0)] = None
    location_id: Id | None = None


class ReconcileAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: Id
    action: Literal["remove", "set_amount"]
    amount: Amount | None = None

    @model_validator(mode="after")
    def _amount(self) -> ReconcileAction:
        if (self.action == "set_amount") != (self.amount is not None):
            raise ValueError("set_amount needs `amount`; remove takes none")
        return self


def _stopped(done: list[dict[str, Any]], n: int, total: int, exc: Exception) -> PartialWrite:
    state = "may or may not have been applied" if isinstance(exc, WriteOutcomeUnknown) else "failed"
    rest = f"; items {n + 1} to {total - 1} were not tried" if n + 1 < total else ""
    return PartialWrite(
        f"applied {len(done)} of {total} items; item {n} {state} ({exc}){rest}. Applied: {done}"
    )


@TOOLS.write(
    f"Add confirmed items to stock, at most {BATCH_MAX}: the `apply_items` of "
    "workflow_stock_intake_preview after the user confirmed them. Takes product ids only. "
    "Each item is one stock booking with its own transaction_id (stock_undo reverts one). "
    + STOP_NOTE
    + " "
    + WRITE_NOTE,
    write_cost=lambda args: len(args.get("items") or []),
)
async def workflow_stock_intake_apply(
    items: Annotated[list[IntakeItem], Field(min_length=1, max_length=BATCH_MAX)],
) -> dict[str, Any]:
    g = grocy()
    for i in items:  # every id checked before the first booking
        await g.object("products", i.product_id)
        if i.location_id is not None:
            await g.object("locations", i.location_id)
    done: list[dict[str, Any]] = []
    for n, i in enumerate(items):
        body = {
            "amount": i.amount,
            "transaction_type": "purchase",
            **i.model_dump(exclude_none=True, exclude={"product_id", "amount"}),
        }
        try:
            rows = await writer().post(f"/stock/products/{i.product_id}/add", body)
        except (GrocyRejected, WriteOutcomeUnknown, ToolInputError) as exc:
            raise _stopped(done, n, len(items), exc) from exc
        tx = sorted({r.get("transaction_id") for r in rows or [] if r.get("transaction_id")})
        done.append(
            {
                "product_id": i.product_id,
                "amount": i.amount,
                "transaction_id": tx[0] if tx else None,
            }
        )
    return {"applied": done}


@TOOLS.write(
    f"Apply confirmed shopping list changes, at most {BATCH_MAX * 2}: the `actions` of "
    "workflow_shopping_reconcile_preview after the user confirmed them (remove an item, or "
    "set its amount). " + STOP_NOTE + " " + WRITE_NOTE,
    write_cost=lambda args: len(args.get("actions") or []),
)
async def workflow_shopping_reconcile_apply(
    actions: Annotated[list[ReconcileAction], Field(min_length=1, max_length=BATCH_MAX * 2)],
) -> dict[str, Any]:
    g = grocy()
    for a in actions:
        await g.object("shopping_list", a.item_id)
    done: list[dict[str, Any]] = []
    for n, a in enumerate(actions):
        try:
            if a.action == "remove":
                await writer().delete(f"/objects/shopping_list/{a.item_id}")
            else:
                await writer().put(f"/objects/shopping_list/{a.item_id}", {"amount": a.amount})
        except (GrocyRejected, WriteOutcomeUnknown, ToolInputError) as exc:
            raise _stopped(done, n, len(actions), exc) from exc
        done.append(a.model_dump(exclude_none=True))
    return {"applied": done}
