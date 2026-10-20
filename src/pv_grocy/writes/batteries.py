# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Battery changes."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..resolve import Ref, resolve_id
from ..tooling import (
    SETS,
    WRITE_NOTE,
    DateTime,
    Id,
    Name,
    Text,
    ToolGroup,
    grocy,
    ref_field,
    require,
    writer,
)

TOOLS = ToolGroup()

Interval = Annotated[int, Field(ge=0, le=3650, description="Days between charges; 0: not tracked")]


@TOOLS.write(
    "Record a battery charge (or replacement), now or at `tracked_time`. "
    "battery_charge_undo reverts it. " + WRITE_NOTE
)
async def battery_charge(
    battery: Annotated[Ref, ref_field("battery")],
    tracked_time: DateTime | None = None,
) -> dict[str, Any]:
    bid = await resolve_id("battery", battery)
    row = (
        await writer().post(
            f"/batteries/{bid}/charge", {"tracked_time": tracked_time} if tracked_time else {}
        )
        or {}
    )
    d = await grocy().get(f"/batteries/{bid}") or {}
    return {
        "battery_id": bid,
        "cycle_id": row.get("id"),
        "tracked_time": row.get("tracked_time"),
        "next_charge": d.get("next_estimated_charge_time"),
    }


@TOOLS.write("Undo one battery charge cycle, by the cycle_id battery_details shows. " + WRITE_NOTE)
async def battery_charge_undo(cycle_id: Id) -> dict[str, Any]:
    await writer().post(f"/batteries/charge-cycles/{cycle_id}/undo")
    return {"undone_cycle_id": cycle_id}


@TOOLS.write("Create a battery to track. " + WRITE_NOTE)
async def battery_create(
    name: Name, used_in: Text = "", charge_interval_days: Interval = 0, description: Text = ""
) -> dict[str, Any]:
    created = await writer().post(
        "/objects/batteries",
        {
            "name": name.strip(),
            "used_in": used_in,
            "charge_interval_days": charge_interval_days,
            "description": description,
        },
    )
    return {"id": int(created["created_object_id"]), "name": name.strip()}


@TOOLS.write(
    "Change a battery's name, where it is used, charge interval or description. Only the "
    "fields given change. " + WRITE_NOTE,
    annotations=SETS,
)
async def battery_update(
    battery: Annotated[Ref, ref_field("battery")],
    name: Name | None = None,
    used_in: Text | None = None,
    charge_interval_days: Interval | None = None,
    description: Text | None = None,
) -> dict[str, Any]:
    bid = await resolve_id("battery", battery)
    body = {
        k: v
        for k, v in {
            "name": name,
            "used_in": used_in,
            "description": description,
            "charge_interval_days": charge_interval_days,
        }.items()
        if v is not None
    }
    require(bool(body), "nothing to change")
    await writer().put(f"/objects/batteries/{bid}", body)
    return {"id": bid, "changed": sorted(body)}
