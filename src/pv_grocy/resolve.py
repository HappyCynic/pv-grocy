# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Turn a caller's reference (an id or an exact name) into one Grocy record.

Never guesses (ADR-0003): an integer must be an existing id, and a string must equal
exactly one record's name, ignoring case and surrounding spaces. Anything else is an error
that lists up to five candidates, so a write can never land on "Almond milk" because the
caller said "milk".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ToolInputError
from .tooling import grocy

MAX_CANDIDATES = 5


@dataclass(frozen=True)
class Kind:
    entity: str
    label: str
    name_field: str = "name"
    query: tuple[str, ...] = ()


KINDS = {
    "product": Kind("products", "product"),
    # Grocy keeps internal recipes for meal-plan days and weeks; only real ones resolve.
    "recipe": Kind("recipes", "recipe", query=("type=normal",)),
    "chore": Kind("chores", "chore"),
    "battery": Kind("batteries", "battery"),
    "equipment": Kind("equipment", "equipment item"),
    "location": Kind("locations", "location"),
    "shopping_list": Kind("shopping_lists", "shopping list"),
    "shopping_location": Kind("shopping_locations", "store"),
    "quantity_unit": Kind("quantity_units", "quantity unit"),
    "product_group": Kind("product_groups", "product group"),
    "task_category": Kind("task_categories", "task category"),
    "meal_plan_section": Kind("meal_plan_sections", "meal plan section"),
}

Ref = int | str


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _describe(rows: list[dict[str, Any]], name_field: str) -> str:
    return ", ".join(f"{r.get(name_field)!r} (id {r.get('id')})" for r in rows[:MAX_CANDIDATES])


async def resolve(kind: str, ref: Ref) -> dict[str, Any]:
    k = KINDS[kind]
    if isinstance(ref, bool):
        raise ToolInputError(f"{k.label}: give an id or a name")
    if isinstance(ref, int):
        try:
            row = await grocy().object(k.entity, ref)
        except ToolInputError:
            raise ToolInputError(f"no {k.label} with id {ref}") from None
        if k.query and not all(_matches(row, q) for q in k.query):
            raise ToolInputError(f"no {k.label} with id {ref}")
        return row
    wanted = _norm(ref)
    if not wanted:
        raise ToolInputError(f"{k.label}: the name is empty")
    # Grocy's `~` is a case-insensitive LIKE '%value%': a short candidate list to pick from.
    rows = await grocy().objects(k.entity, query=[*k.query, f"{k.name_field}~{ref.strip()}"])
    exact = [r for r in rows if _norm(r.get(k.name_field)) == wanted]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ToolInputError(
            f"{len(exact)} {k.label}s are named {ref!r}: {_describe(exact, k.name_field)}; "
            "use the id"
        )
    if rows:
        raise ToolInputError(
            f"no {k.label} is named exactly {ref!r}; similar: {_describe(rows, k.name_field)}. "
            "Use the exact name or the id"
        )
    raise ToolInputError(f"no {k.label} named {ref!r}")


async def resolve_id(kind: str, ref: Ref) -> int:
    return int((await resolve(kind, ref))["id"])


async def resolve_optional(kind: str, ref: Ref | None) -> int | None:
    return None if ref is None else await resolve_id(kind, ref)


def _matches(row: dict[str, Any], condition: str) -> bool:
    field, _, value = condition.partition("=")
    return str(row.get(field)) == value


async def resolve_user(ref: Ref) -> dict[str, Any]:
    """Grocy users by id, username or display name (same exact-match rule)."""
    users = await grocy().get("/users")
    users = users if isinstance(users, list) else []
    if isinstance(ref, int) and not isinstance(ref, bool):
        for u in users:
            if u.get("id") == ref:
                return dict(u)
        raise ToolInputError(f"no user with id {ref}")
    wanted = _norm(ref)
    exact = [u for u in users if wanted in (_norm(u.get("username")), _norm(u.get("display_name")))]
    if len(exact) == 1:
        return dict(exact[0])
    if exact:
        raise ToolInputError(f"several users match {ref!r}; use the id")
    raise ToolInputError(f"no user named {ref!r}")


async def names(entity: str, name_field: str = "name") -> dict[int, str]:
    """id -> name for a small master-data table (locations, units, lists ...)."""
    return {int(r["id"]): r.get(name_field) or "" for r in await grocy().objects(entity)}
