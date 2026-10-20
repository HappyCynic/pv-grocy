# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Chore changes."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from ..resolve import Ref, resolve_id, resolve_user
from ..tooling import (
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


@TOOLS.write(
    "Record that a chore was done (or `skipped`), now or at `tracked_time`, by the API "
    "key's user or `done_by` (a user id or name). This schedules its next time. chore_undo "
    "reverts it. " + WRITE_NOTE
)
async def chore_execute(
    chore: Annotated[Ref, ref_field("chore")],
    done_by: Annotated[Ref | None, ref_field("user")] = None,
    tracked_time: DateTime | None = None,
    skipped: bool = False,
) -> dict[str, Any]:
    cid = await resolve_id("chore", chore)
    body: dict[str, Any] = {"skipped": skipped}
    if done_by is not None:
        body["done_by"] = (await resolve_user(done_by))["id"]
    if tracked_time:
        body["tracked_time"] = tracked_time
    row = await writer().post(f"/chores/{cid}/execute", body) or {}
    d = await grocy().get(f"/chores/{cid}") or {}
    return {
        "chore_id": cid,
        "execution_id": row.get("id"),
        "tracked_time": row.get("tracked_time"),
        "skipped": skipped,
        "next_due": d.get("next_estimated_execution_time"),
    }


@TOOLS.write(
    "Undo a chore execution: give `execution_id` (from chore_execute or chore_details), or "
    "`chore` to undo its most recent execution that is not undone yet. " + WRITE_NOTE
)
async def chore_undo(
    execution_id: Id | None = None,
    chore: Annotated[Ref | None, ref_field("chore")] = None,
) -> dict[str, Any]:
    require((execution_id is None) != (chore is None), "give exactly one of execution_id or chore")
    if execution_id is None:
        assert chore is not None
        cid = await resolve_id("chore", chore)
        rows = await grocy().objects(
            "chores_log", query=[f"chore_id={cid}", "undone=0"], order="id:desc", limit=1
        )
        require(bool(rows), "that chore has no execution to undo")
        execution_id = int(rows[0]["id"])
    await writer().post(f"/chores/executions/{execution_id}/undo")
    return {"undone_execution_id": execution_id}


@TOOLS.write(
    "Create a chore. `period_type` sets how it repeats (default `manually`: no schedule); "
    "with daily, weekly, monthly or yearly, `period_interval` is every how many of those "
    "(default 1). " + WRITE_NOTE
)
async def chore_create(
    name: Name,
    description: Text = "",
    period_type: Literal["manually", "hourly", "daily", "weekly", "monthly", "yearly"] = "manually",
    period_interval: Annotated[int, Field(ge=1, le=1000)] = 1,
) -> dict[str, Any]:
    created = await writer().post(
        "/objects/chores",
        {
            "name": name.strip(),
            "description": description,
            "period_type": period_type,
            "period_interval": period_interval,
        },
    )
    return {"id": int(created["created_object_id"]), "name": name.strip()}
