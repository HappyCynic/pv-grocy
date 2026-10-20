# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Equipment reads (appliances and their manuals)."""

from __future__ import annotations

from typing import Annotated, Any

from ..resolve import Ref, resolve
from ..text import description
from ..tooling import ToolGroup, grocy, ref_field

TOOLS = ToolGroup()


@TOOLS.read("Equipment items with id, name and manual file name, if any.")
async def equipment_list() -> dict[str, Any]:
    rows = await grocy().objects("equipment", order="name")
    return {
        "equipment": [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "manual_file": r.get("instruction_manual_file_name"),
            }
            for r in rows
        ]
    }


@TOOLS.read(
    "One equipment item: description as plain text (at most 4000 characters) and manual "
    "file name (download with file_download, group equipmentmanuals)."
)
async def equipment_details(
    equipment: Annotated[Ref, ref_field("equipment item")],
) -> dict[str, Any]:
    r = await resolve("equipment", equipment)
    return {
        "id": r.get("id"),
        "name": r.get("name"),
        **description(r.get("description")),
        "manual_file": r.get("instruction_manual_file_name"),
    }
