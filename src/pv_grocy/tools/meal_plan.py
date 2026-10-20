# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Meal plan reads."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from pydantic import Field

from ..resolve import names
from ..tooling import Date, ToolGroup, flag, grocy, require

TOOLS = ToolGroup()

RANGE_DAYS_DEFAULT = 7
RANGE_DAYS_MAX = 92


async def grocy_today() -> dt.date:
    """Today in Grocy's own time zone (which may differ from this server's)."""
    t = await grocy().get("/system/time") or {}
    return dt.date.fromisoformat(str(t.get("time_local", ""))[:10] or dt.date.today().isoformat())


def date_range(
    start: dt.date, start_date: str | None, end_date: str | None
) -> tuple[dt.date, dt.date]:
    first = dt.date.fromisoformat(start_date) if start_date else start
    last = (
        dt.date.fromisoformat(end_date)
        if end_date
        else first + dt.timedelta(RANGE_DAYS_DEFAULT - 1)
    )
    require(last >= first, "end_date is before start_date")
    require((last - first).days < RANGE_DAYS_MAX, f"at most {RANGE_DAYS_MAX} days per call")
    return first, last


async def entries(first: dt.date, last: dt.date) -> list[dict[str, Any]]:
    rows = await grocy().objects(
        "meal_plan", query=[f"day>={first.isoformat()}", f"day<={last.isoformat()}"], order="day"
    )
    recipes, sections = await names("recipes"), await names("meal_plan_sections")
    products = await names("products")
    return [
        {
            "entry_id": r.get("id"),
            "day": r.get("day"),
            "type": r.get("type"),
            "section": sections.get(r.get("section_id") or 0) or None,
            "recipe_id": r.get("recipe_id"),
            "recipe": recipes.get(r.get("recipe_id") or 0),
            "servings": r.get("recipe_servings"),
            "product": products.get(r.get("product_id") or 0),
            "product_amount": r.get("product_amount") or None,
            "note": r.get("note"),
            "done": flag(r.get("done")),
        }
        for r in rows
    ]


@TOOLS.read(
    "Meal plan entries from `start_date` to `end_date` (inclusive; default: the 7 days from "
    f"today in Grocy's time zone; at most {RANGE_DAYS_MAX} days), sorted by day, with entry "
    "id, section (e.g. Breakfast), recipe and servings, or a product or a note."
)
async def meal_plan_list(
    start_date: Date | None = None,
    end_date: Date | None = None,
    section: Annotated[str | None, Field(max_length=200, description="Only this section")] = None,
) -> dict[str, Any]:
    first, last = date_range(await grocy_today(), start_date, end_date)
    rows = await entries(first, last)
    if section is not None:
        rows = [r for r in rows if (r["section"] or "").casefold() == section.strip().casefold()]
    return {"start_date": first.isoformat(), "end_date": last.isoformat(), "entries": rows}
