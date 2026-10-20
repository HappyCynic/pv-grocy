# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Equipment changes."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..resolve import Ref, resolve_id
from ..tooling import SETS, WRITE_NOTE, Name, ToolGroup, ref_field, require, writer

TOOLS = ToolGroup()

Description = Annotated[str, Field(max_length=20_000, description="Plain text or HTML")]


@TOOLS.write("Create an equipment item (an appliance, tool or device). " + WRITE_NOTE)
async def equipment_create(name: Name, description: Description = "") -> dict[str, Any]:
    created = await writer().post(
        "/objects/equipment", {"name": name.strip(), "description": description}
    )
    return {"id": int(created["created_object_id"]), "name": name.strip()}


@TOOLS.write(
    "Change an equipment item's name or description. Only the fields given change. " + WRITE_NOTE,
    annotations=SETS,
)
async def equipment_update(
    equipment: Annotated[Ref, ref_field("equipment item")],
    name: Name | None = None,
    description: Description | None = None,
) -> dict[str, Any]:
    eid = await resolve_id("equipment", equipment)
    body = {k: v for k, v in {"name": name, "description": description}.items() if v is not None}
    require(bool(body), "nothing to change: give name or description")
    await writer().put(f"/objects/equipment/{eid}", body)
    return {"id": eid, "changed": sorted(body)}
