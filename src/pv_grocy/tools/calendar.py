# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Planning reads across tasks, chores, batteries and the meal plan, and the iCal export."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..tooling import Date, ToolGroup, grocy
from .meal_plan import date_range, entries, grocy_today

TOOLS = ToolGroup()

ICAL_PAGE_CHARS = 20_000


@TOOLS.read(
    "What is due from `start_date` to `end_date` (inclusive; default: 7 days from today in "
    "Grocy's time zone; at most 92 days): open tasks due, chores and battery charges due "
    "(overdue ones included, flagged), and meal plan entries."
)
async def calendar_summary(
    start_date: Date | None = None, end_date: Date | None = None
) -> dict[str, Any]:
    g = grocy()
    first, last = date_range(await grocy_today(), start_date, end_date)
    lo, hi = first.isoformat(), last.isoformat() + " 23:59:59"
    tasks = [
        {
            "id": t.get("id"),
            "name": t.get("name"),
            "due_date": t.get("due_date"),
            "overdue": str(t.get("due_date")) < lo,
        }
        for t in await g.get("/tasks") or []
        if t.get("due_date") and str(t.get("due_date")) <= hi
    ]
    chores = [
        {
            "id": c.get("chore_id"),
            "name": c.get("chore_name"),
            "next_due": c.get("next_estimated_execution_time"),
            "overdue": str(c.get("next_estimated_execution_time")) < lo,
        }
        for c in await g.get("/chores") or []
        if c.get("next_estimated_execution_time")
        and str(c.get("next_estimated_execution_time")) <= hi
    ]
    batteries = [
        {
            "id": b.get("battery_id"),
            "name": (b.get("battery") or {}).get("name"),
            "next_charge": b.get("next_estimated_charge_time"),
            "overdue": str(b.get("next_estimated_charge_time")) < lo,
        }
        for b in await g.get("/batteries") or []
        if b.get("next_estimated_charge_time") and str(b.get("next_estimated_charge_time")) <= hi
    ]
    return {
        "start_date": lo,
        "end_date": last.isoformat(),
        "tasks": sorted(tasks, key=lambda t: str(t["due_date"])),
        "chores": sorted(chores, key=lambda c: str(c["next_due"])),
        "batteries": sorted(batteries, key=lambda b: str(b["next_charge"])),
        "meal_plan": await entries(first, last),
    }


@TOOLS.read(
    "Grocy's calendar as iCalendar text (product due dates, tasks, chores, batteries, meal "
    f"plan), in pages of {ICAL_PAGE_CHARS} characters: when `next_offset` is not null, call "
    "again with `offset` set to it."
)
async def calendar_ical(offset: Annotated[int, Field(ge=0)] = 0) -> dict[str, Any]:
    text = await grocy().get_text("/calendar/ical")
    chunk = text[offset : offset + ICAL_PAGE_CHARS]
    nxt = offset + ICAL_PAGE_CHARS if offset + ICAL_PAGE_CHARS < len(text) else None
    return {"ical": chunk, "total_chars": len(text), "next_offset": nxt}
