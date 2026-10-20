# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Which Grocy entities the generic tools may touch (ADR-0002).

From Grocy 4.7's ExposedEntity lists, minus what no MCP client should see or change: API
keys (credentials), sessions (login cookies) and the permission hierarchy. Users are not
an entity in Grocy's object API and are never written here.
"""

from __future__ import annotations

import re

from .errors import ToolInputError

NEVER = frozenset({"api_keys", "sessions", "permission_hierarchy"})

GROCY_EXPOSED = frozenset(
    {
        "products",
        "chores",
        "product_barcodes",
        "batteries",
        "locations",
        "quantity_units",
        "quantity_unit_conversions",
        "shopping_list",
        "shopping_lists",
        "shopping_locations",
        "recipes",
        "recipes_pos",
        "recipes_nestings",
        "tasks",
        "task_categories",
        "product_groups",
        "equipment",
        "api_keys",
        "userfields",
        "userentities",
        "userobjects",
        "meal_plan",
        "stock_log",
        "stock",
        "stock_current_locations",
        "chores_log",
        "meal_plan_sections",
        "products_last_purchased",
        "products_average_price",
        "quantity_unit_conversions_resolved",
        "recipes_pos_resolved",
        "battery_charge_cycles",
        "product_barcodes_view",
        "permission_hierarchy",
        "uihelper_shopping_list",
        "sessions",
    }
)
GROCY_NO_EDIT = frozenset(
    {
        "stock_log",
        "api_keys",
        "stock",
        "stock_current_locations",
        "chores_log",
        "products_last_purchased",
        "products_average_price",
        "quantity_unit_conversions_resolved",
        "recipes_pos_resolved",
        "battery_charge_cycles",
        "product_barcodes_view",
        "permission_hierarchy",
        "uihelper_shopping_list",
        "sessions",
    }
)
GROCY_NO_DELETE = frozenset(
    {
        "stock_log",
        "stock",
        "stock_current_locations",
        "chores_log",
        "products_last_purchased",
        "products_average_price",
        "quantity_unit_conversions_resolved",
        "recipes_pos_resolved",
        "battery_charge_cycles",
        "product_barcodes_view",
        "permission_hierarchy",
        "uihelper_shopping_list",
    }
)

READABLE = GROCY_EXPOSED - NEVER
EDITABLE = READABLE - GROCY_NO_EDIT
DELETABLE = READABLE - GROCY_NO_DELETE
# Master data that a `write` token may create and update (catalog_create/catalog_update).
CATALOG = frozenset(
    {
        "products",
        "product_barcodes",
        "product_groups",
        "locations",
        "quantity_units",
        "quantity_unit_conversions",
        "shopping_lists",
        "shopping_locations",
        "task_categories",
        "meal_plan_sections",
    }
)
assert CATALOG <= EDITABLE

# Mirrors Grocy's own filter grammar (BaseApiController::FilterData), anchored, so a filter
# is rejected here rather than silently cut short by Grocy's unanchored match.
FILTER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]+(!?(>=|<=|=|~|<|>|§))[A-Za-z\w*.$#^| -\\\]]+$")
# Fields no generic write may set.
PROTECTED_FIELDS = frozenset({"id", "row_created_timestamp"})


def check_entity(entity: str, allowed: frozenset[str], action: str) -> str:
    if entity not in allowed:
        raise ToolInputError(
            f"cannot {action} entity {entity!r}; allowed: {', '.join(sorted(allowed))}"
        )
    return entity


def check_filters(filters: list[str]) -> list[str]:
    for f in filters:
        if not FILTER_RE.match(f):
            raise ToolInputError(
                f"invalid filter {f!r}: use <field><op><value> with op one of "
                "= != ~ !~ < > <= >= (e.g. name~milk, location_id=2)"
            )
    return filters
