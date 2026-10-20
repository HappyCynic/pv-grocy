# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Battery reads (rechargeable or replaceable batteries tracked by charge cycle)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from pydantic import Field

from ..resolve import Ref, resolve_id
from ..tooling import ToolGroup, flag, grocy, pick, ref_field
from .chores import grocy_now

TOOLS = ToolGroup()

HISTORY_MAX = 50


@TOOLS.read(
    "Batteries with where they are used, last charge and next estimated charge. "
    "`due_within_days` keeps those due within that many days (overdue included); "
    "`overdue_only` keeps those already past due."
)
async def batteries_list(
    due_within_days: Annotated[int | None, Field(ge=0, le=365)] = None,
    overdue_only: bool = False,
) -> dict[str, Any]:
    rows = await grocy().get("/batteries") or []
    now = await grocy_now()
    horizon = None
    if due_within_days is not None and now:
        horizon = (dt.datetime.fromisoformat(now) + dt.timedelta(days=due_within_days)).isoformat(
            " "
        )
    out = []
    for r in rows:
        b = r.get("battery") or {}
        nxt = r.get("next_estimated_charge_time")
        overdue = bool(nxt) and str(nxt) < now
        if overdue_only and not overdue:
            continue
        if horizon is not None and not (nxt and str(nxt) <= horizon):
            continue
        out.append(
            {
                "id": r.get("battery_id"),
                "name": b.get("name"),
                "used_in": b.get("used_in"),
                "last_charged": r.get("last_tracked_time"),
                "next_charge": nxt,
                "overdue": overdue,
            }
        )
    out.sort(key=lambda b: str(b["next_charge"] or "9999"))
    return {"batteries": out, "now": now}


@TOOLS.read(
    "One battery: details, charge cycle count, last and next charge, and its most recent "
    f"charge cycles (`history`, at most {HISTORY_MAX}) with the cycle ids "
    "battery_charge_undo takes."
)
async def battery_details(
    battery: Annotated[Ref, ref_field("battery")],
    history: Annotated[int, Field(ge=0, le=HISTORY_MAX)] = 10,
) -> dict[str, Any]:
    g = grocy()
    bid = await resolve_id("battery", battery)
    d = await g.get(f"/batteries/{bid}") or {}
    cycles = (
        await g.objects(
            "battery_charge_cycles", query=[f"battery_id={bid}"], order="id:desc", limit=history
        )
        if history
        else []
    )
    return {
        **pick(d.get("battery"), "id", "name", "description", "used_in", "charge_interval_days"),
        "active": flag((d.get("battery") or {}).get("active", 1)),
        "charge_cycles": d.get("charge_cycles_count"),
        "last_charged": d.get("last_charged"),
        "next_charge": d.get("next_estimated_charge_time"),
        "history": [
            {
                "cycle_id": c.get("id"),
                "time": c.get("tracked_time"),
                "undone": flag(c.get("undone")),
            }
            for c in cycles
        ],
    }
