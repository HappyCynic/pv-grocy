# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Generic reads over Grocy's object API, and search across kinds of things."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from ..entities import CATALOG, DELETABLE, EDITABLE, READABLE, check_entity, check_filters
from ..resolve import KINDS
from ..tooling import LIMIT_DEFAULT, PAGING_NOTE, Id, Limit, Offset, ToolGroup, grocy

TOOLS = ToolGroup()

FIELD_MAX_CHARS = 1000
SEARCH_LIMIT_MAX = 50
SEARCH_KINDS = (
    "product",
    "recipe",
    "chore",
    "battery",
    "equipment",
    "location",
    "shopping_list",
    "shopping_location",
    "product_group",
    "quantity_unit",
    "task_category",
    "meal_plan_section",
)
SearchKind = Literal[
    "product",
    "recipe",
    "chore",
    "battery",
    "equipment",
    "location",
    "shopping_list",
    "shopping_location",
    "product_group",
    "quantity_unit",
    "task_category",
    "meal_plan_section",
]
Entity = Annotated[
    str,
    Field(description="Grocy entity (table) name, e.g. products, locations, shopping_lists"),
]
Filters = Annotated[
    list[str],
    Field(
        max_length=10,
        description="Grocy filters, all must match: <field><op><value>, op one of = != "
        "~ (contains, "
        "case-insensitive) !~ < > <= >=; e.g. ['name~milk', 'active=1']",
    ),
]


def _clip(row: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in row.items():
        if isinstance(v, str) and len(v) > FIELD_MAX_CHARS:
            v = v[: FIELD_MAX_CHARS - 1] + "…"
        out[k] = v
    return out


@TOOLS.read(
    "Rows of any readable Grocy entity (table), raw, optionally filtered and ordered; long "
    f"text fields are cut at {FIELD_MAX_CHARS} characters. Prefer the specific tools; use "
    "this for master data such as shopping_lists, locations, quantity_units, product_groups, "
    "shopping_locations, task_categories, meal_plan_sections or userfields. API keys and "
    f"sessions are never readable. At most {LIMIT_DEFAULT} rows per page by default. " + PAGING_NOTE
)
async def entity_list(
    entity: Entity,
    filters: Filters | None = None,
    order: Annotated[
        str | None,
        Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(:(asc|desc))?$", description="field or field:desc"),
    ] = None,
    limit: Limit = LIMIT_DEFAULT,
    offset: Offset = 0,
) -> dict[str, Any]:
    check_entity(entity, READABLE, "list")
    rows = await grocy().objects(
        entity, query=check_filters(filters or []), order=order, limit=limit + 1, offset=offset
    )
    return {
        "entity": entity,
        "rows": [_clip(r) for r in rows[:limit]],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


@TOOLS.read("One row of any readable Grocy entity by id, raw.")
async def entity_get(entity: Entity, id: Id) -> dict[str, Any]:
    check_entity(entity, READABLE, "read")
    return {"entity": entity, "row": _clip(await grocy().object(entity, id))}


@TOOLS.read(
    "Describe a Grocy entity: its fields (from a sample row, with example values), its user "
    "fields (custom fields defined in Grocy), and which tools may create, change or delete "
    "rows of it."
)
async def entity_describe(entity: Entity) -> dict[str, Any]:
    check_entity(entity, READABLE, "describe")
    g = grocy()
    sample = await g.objects(entity, limit=1)
    userfields = await g.objects("userfields", query=[f"entity={entity}"])
    fields = {
        k: type(v).__name__ if v is not None else "null"
        for k, v in (sample[0] if sample else {}).items()
    }
    return {
        "entity": entity,
        "fields": fields,
        "sample": _clip(sample[0]) if sample else None,
        "userfields": [
            {"name": u.get("name"), "caption": u.get("caption"), "type": u.get("type")}
            for u in userfields
        ],
        "catalog_create_update": entity in CATALOG,
        "entity_create_update": entity in EDITABLE,
        "entity_delete": entity in DELETABLE,
    }


@TOOLS.read(
    "Find things by part of their name across products, recipes, chores, batteries, "
    "equipment, locations, shopping lists, stores, product groups, quantity units, task "
    "categories and meal plan sections (or only `kinds`). Returns kind, id and exact name, "
    f"exact matches first, at most `limit` (default 10, max {SEARCH_LIMIT_MAX}) per kind."
)
async def search(
    query: Annotated[str, Field(min_length=1, max_length=200)],
    kinds: list[SearchKind] | None = None,
    limit: Annotated[int, Field(ge=1, le=SEARCH_LIMIT_MAX)] = 10,
) -> dict[str, Any]:
    g = grocy()
    q = query.strip()
    results = []
    for kind in kinds or SEARCH_KINDS:
        k = KINDS[kind]
        rows = await g.objects(k.entity, query=[*k.query, f"{k.name_field}~{q}"])
        rows.sort(
            key=lambda r: (
                str(r.get(k.name_field)).casefold() != q.casefold(),
                str(r.get(k.name_field)).casefold(),
            )
        )
        results += [
            {"kind": kind, "id": r.get("id"), "name": r.get(k.name_field)} for r in rows[:limit]
        ]
    return {"query": q, "results": results}
