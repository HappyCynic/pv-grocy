# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Chore reads."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..resolve import Ref, resolve_id
from ..text import description
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

HISTORY_MAX = 50


async def grocy_now() -> str:
    t = await grocy().get("/system/time") or {}
    return str(t.get("time_local") or "")


def _user(u: dict[str, Any] | None) -> str | None:
    return (u or {}).get("display_name") or (u or {}).get("username")


@TOOLS.read(
    "Chores with their next due time, last done time and who is assigned next. "
    "`overdue_only` keeps chores whose next time has passed (Grocy's local time). "
    f"At most {LIMIT_DEFAULT} per page by default. " + PAGING_NOTE
)
async def chores_list(
    overdue_only: bool = False, limit: Limit = LIMIT_DEFAULT, offset: Offset = 0
) -> dict[str, Any]:
    rows = await grocy().get("/chores") or []
    now = await grocy_now()
    chores = [
        {
            "id": r.get("chore_id"),
            "name": r.get("chore_name"),
            "next_due": r.get("next_estimated_execution_time"),
            "last_done": r.get("last_tracked_time"),
            "assigned_to": _user(r.get("next_execution_assigned_user")),
            "overdue": bool(r.get("next_estimated_execution_time"))
            and str(r.get("next_estimated_execution_time")) < now,
        }
        for r in rows
    ]
    if overdue_only:
        chores = [c for c in chores if c["overdue"]]
    chores.sort(key=lambda c: str(c["next_due"] or "9999"))
    return paged("chores", chores, limit, offset, now=now)


@TOOLS.read(
    "One chore: schedule, description, last done and by whom, next due, how often it is "
    f"done, and its most recent executions (`history`, at most {HISTORY_MAX}) with the "
    "execution ids chore_undo takes."
)
async def chore_details(
    chore: Annotated[Ref, ref_field("chore")],
    history: Annotated[int, Field(ge=0, le=HISTORY_MAX)] = 10,
) -> dict[str, Any]:
    g = grocy()
    cid = await resolve_id("chore", chore)
    d = await g.get(f"/chores/{cid}") or {}
    c = d.get("chore") or {}
    log = (
        await g.objects("chores_log", query=[f"chore_id={cid}"], order="id:desc", limit=history)
        if history
        else []
    )
    return {
        "id": cid,
        "name": c.get("name"),
        **description(c.get("description")),
        "period_type": c.get("period_type"),
        "period_interval": c.get("period_interval"),
        "active": flag(c.get("active", 1)),
        "last_done": d.get("last_tracked"),
        "last_done_by": _user(d.get("last_done_by")),
        "times_done": d.get("tracked_count"),
        "next_due": d.get("next_estimated_execution_time"),
        "assigned_to": _user(d.get("next_execution_assigned_user")),
        "history": [
            {
                "execution_id": e.get("id"),
                "time": e.get("tracked_time"),
                "done_by_user_id": e.get("done_by_user_id"),
                "skipped": flag(e.get("skipped")),
                "undone": flag(e.get("undone")),
            }
            for e in log
        ],
    }
