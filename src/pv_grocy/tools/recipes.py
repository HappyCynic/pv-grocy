# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Recipe reads: list, details with ingredients, fulfillment, consume preview."""

from __future__ import annotations

from typing import Annotated, Any

from ..resolve import Ref, names, resolve
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


def fulfillment_view(f: dict[str, Any]) -> dict[str, Any]:
    return {
        "can_be_made": flag(f.get("need_fulfilled")),
        "can_be_made_with_shopping_list": flag(f.get("need_fulfilled_with_shopping_list")),
        "missing_products_count": f.get("missing_products_count"),
        "costs": f.get("costs"),
        "costs_per_serving": f.get("costs_per_serving"),
        "calories": f.get("calories"),
        "prices_incomplete": flag(f.get("prices_incomplete")),
    }


async def ingredients(recipe_id: int) -> list[dict[str, Any]]:
    """The recipe's own ingredient lines with stock status. Lines of nested recipes are
    included and marked `nested` (they belong to the included recipe)."""
    rows = await grocy().objects("recipes_pos_resolved", query=[f"recipe_id={recipe_id}"])
    units = await names("quantity_units")
    return [
        {
            "ingredient_id": r.get("recipe_pos_id"),
            "product_id": r.get("product_id"),
            "product": r.get("product_name"),
            "amount": r.get("recipe_amount"),
            "unit": units.get(r.get("qu_id") or 0),
            "group": r.get("ingredient_group"),
            "note": r.get("note"),
            "in_stock": r.get("stock_amount"),
            "missing_amount": r.get("missing_amount"),
            "on_shopping_list": r.get("amount_on_shopping_list"),
            "enough_in_stock": flag(r.get("need_fulfilled")),
            "nested": flag(r.get("is_nested_recipe_pos")),
            "only_checks_one_unit": flag(r.get("only_check_single_unit_in_stock")),
        }
        for r in rows
    ]


@TOOLS.read(
    "All recipes with id, servings and whether each can be made from current stock "
    f"(missing products count). At most {LIMIT_DEFAULT} per page by default. " + PAGING_NOTE
)
async def recipes_list(limit: Limit = LIMIT_DEFAULT, offset: Offset = 0) -> dict[str, Any]:
    g = grocy()
    recipes = await g.objects("recipes", query=["type=normal"], order="name")
    status = {f["recipe_id"]: f for f in await g.get("/recipes/fulfillment") or []}
    rows = [
        {
            "id": r["id"],
            "name": r.get("name"),
            "servings": r.get("desired_servings"),
            "can_be_made": flag((status.get(r["id"]) or {}).get("need_fulfilled")),
            "missing_products_count": (status.get(r["id"]) or {}).get("missing_products_count"),
        }
        for r in recipes
    ]
    return paged("recipes", rows, limit, offset)


@TOOLS.read(
    "One recipe: name, servings, description as plain text (at most 4000 characters), and "
    "every ingredient line with ingredient_id (for recipe_ingredient_remove), amount, unit, "
    "and how much is in stock or missing."
)
async def recipe_details(recipe: Annotated[Ref, ref_field("recipe")]) -> dict[str, Any]:
    r = await resolve("recipe", recipe)
    return {
        "id": r["id"],
        "name": r.get("name"),
        "base_servings": r.get("base_servings"),
        "servings": r.get("desired_servings"),
        **description(r.get("description")),
        "ingredients": await ingredients(int(r["id"])),
    }


@TOOLS.read(
    "Whether a recipe can be made from current stock (and with what is on the shopping "
    "list), how many products are missing, and the cost and calories."
)
async def recipe_fulfillment(recipe: Annotated[Ref, ref_field("recipe")]) -> dict[str, Any]:
    r = await resolve("recipe", recipe)
    f = await grocy().get(f"/recipes/{r['id']}/fulfillment") or {}
    missing = [i for i in await ingredients(int(r["id"])) if not i["enough_in_stock"]]
    return {"id": r["id"], "name": r.get("name"), **fulfillment_view(f), "missing": missing}


@TOOLS.read(
    "What recipe_consume would take from stock, without changing anything. Grocy consumes "
    "each ingredient's amount, only what is in stock when there is less (a partial "
    "consume), and skips ingredients that are out of stock or only checked for one unit. "
    "`short` lists the ingredients that would not be fully consumed."
)
async def recipe_consume_preview(recipe: Annotated[Ref, ref_field("recipe")]) -> dict[str, Any]:
    r = await resolve("recipe", recipe)
    lines = []
    for i in await ingredients(int(r["id"])):
        need, have = float(i["amount"] or 0), float(i["in_stock"] or 0)
        skipped = i["only_checks_one_unit"] or have <= 0
        take = 0.0 if skipped else min(need, have)
        lines.append(
            {
                "product_id": i["product_id"],
                "product": i["product"],
                "unit": i["unit"],
                "needed": need,
                "in_stock": have,
                "would_consume": take,
                "left_after": round(have - take, 4),
                "skipped": skipped,
            }
        )
    return {
        "id": r["id"],
        "name": r.get("name"),
        "servings": r.get("desired_servings"),
        "consumes": lines,
        "short": [line["product"] for line in lines if line["would_consume"] < line["needed"]],
    }
