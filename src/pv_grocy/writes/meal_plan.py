# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Meal plan changes."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from pydantic import Field

from ..errors import ToolInputError
from ..resolve import Ref, resolve, resolve_optional
from ..tooling import (
    DESTROYS,
    WRITE_NOTE,
    Date,
    Id,
    Text,
    ToolGroup,
    grocy,
    ref_field,
    require,
    writer,
)
from ..tools.meal_plan import grocy_today
from ..tools.recipes import fulfillment_view

TOOLS = ToolGroup()


@TOOLS.write(
    "Add an entry to the meal plan on `day`: a recipe (with servings), or a free-text note, "
    "or both, optionally in a section such as Breakfast (meal_plan_sections). " + WRITE_NOTE
)
async def meal_plan_add(
    day: Date,
    recipe: Annotated[Ref | None, ref_field("recipe")] = None,
    servings: Annotated[float, Field(gt=0, le=1000)] = 1,
    note: Text | None = None,
    section: Annotated[Ref | None, ref_field("meal plan section")] = None,
) -> dict[str, Any]:
    require(recipe is not None or bool(note and note.strip()), "give a recipe or a note")
    body: dict[str, Any] = {"day": day, "type": "recipe" if recipe is not None else "note"}
    if recipe is not None:
        r = await resolve("recipe", recipe)
        body |= {"recipe_id": r["id"], "recipe_servings": servings}
    if note:
        body["note"] = note
    if (sid := await resolve_optional("meal_plan_section", section)) is not None:
        body["section_id"] = sid
    created = await writer().post("/objects/meal_plan", body)
    return {"entry_id": int(created["created_object_id"]), "day": day, "type": body["type"]}


@TOOLS.write(
    "Remove one meal plan entry, by the entry_id meal_plan_list shows. " + WRITE_NOTE,
    annotations=DESTROYS,
)
async def meal_plan_remove(entry_id: Id) -> dict[str, Any]:
    try:
        e = await grocy().object("meal_plan", entry_id)
    except ToolInputError:
        raise ToolInputError(f"no meal plan entry {entry_id}") from None
    await writer().delete(f"/objects/meal_plan/{entry_id}")
    return {"removed": entry_id, "day": e.get("day"), "recipe_id": e.get("recipe_id")}


def grocy_week(day: dt.date) -> tuple[str, dt.date, dt.date]:
    """Grocy's meal-plan week for a day: SQLite STRFTIME('%Y-%W') (Monday-first weeks, days
    before the year's first Monday are week 00), so a week is split at New Year. Not ISO."""
    monday = day - dt.timedelta(days=day.weekday())
    first = max(monday, dt.date(day.year, 1, 1))
    last = min(monday + dt.timedelta(days=6), dt.date(day.year, 12, 31))
    return day.strftime("%Y-%W"), first, last


@TOOLS.write(
    "Put what the meal plan's recipes are missing on the shopping list for one week: the "
    "Monday-to-Sunday week containing `week_of` (default: today), split at New Year as Grocy "
    "does. This is Grocy's own week calculation, so stock is counted once across the week's "
    "recipes and servings. " + WRITE_NOTE
)
async def meal_plan_add_missing_to_shopping_list(week_of: Date | None = None) -> dict[str, Any]:
    day = dt.date.fromisoformat(week_of) if week_of else await grocy_today()
    name, first, last = grocy_week(day)
    span = {"week": name, "from": first.isoformat(), "to": last.isoformat()}
    rows = await grocy().objects("recipes", query=["type=mealplan-week", f"name={name}"])
    if not rows:
        return {**span, "planned": False, "note": "nothing with a recipe is planned that week"}
    rid = rows[0]["id"]
    await writer().post(f"/recipes/{rid}/add-not-fulfilled-products-to-shoppinglist", {})
    f = await grocy().get(f"/recipes/{rid}/fulfillment") or {}
    return {**span, "planned": True, **fulfillment_view(f)}
