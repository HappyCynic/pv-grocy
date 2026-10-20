# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Recipe changes: consume, missing to shopping list, create, edit, ingredients."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from ..errors import GrocyRejected, PartialWrite, ToolInputError, WriteOutcomeUnknown
from ..resolve import Ref, resolve
from ..tooling import (
    DESTROYS,
    SETS,
    WRITE_NOTE,
    Amount,
    Id,
    Name,
    ToolGroup,
    grocy,
    ref_field,
    require,
    writer,
)
from ..tools.recipes import fulfillment_view

TOOLS = ToolGroup()

INGREDIENTS_MAX = 100
RecipeRef = Annotated[Ref, ref_field("recipe")]
Servings = Annotated[float, Field(gt=0, le=1000)]
Description = Annotated[str, Field(max_length=20_000, description="Plain text or HTML")]


class Ingredient(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product: Annotated[Ref, Field(description="Product id or exact name")]
    amount: Amount
    note: Annotated[str | None, Field(max_length=500)] = None
    group: Annotated[str | None, Field(max_length=100, description="e.g. Dough, Topping")] = None


async def _ingredient_rows(recipe_id: int, items: list[Ingredient]) -> list[dict[str, Any]]:
    """Resolve every product before anything is written."""
    rows = []
    for n, i in enumerate(items):
        try:
            p = await resolve("product", i.product)
        except ToolInputError as exc:
            raise ToolInputError(f"ingredients[{n}]: {exc}") from None
        row: dict[str, Any] = {
            "recipe_id": recipe_id,
            "product_id": p["id"],
            "amount": i.amount,
            "qu_id": p.get("qu_id_stock"),
        }
        if i.note:
            row["note"] = i.note
        if i.group:
            row["ingredient_group"] = i.group
        rows.append(row)
    return rows


@TOOLS.write(
    "Consume a recipe's ingredients from stock, as if it was cooked. Grocy takes each "
    "ingredient's amount, only what is in stock when there is less, and skips ingredients "
    "that are out of stock; check recipe_consume_preview first. The bookings share one "
    "transaction_id (see stock_journal) that stock_undo reverts. " + WRITE_NOTE
)
async def recipe_consume(recipe: RecipeRef) -> dict[str, Any]:
    r = await resolve("recipe", recipe)
    await writer().post(f"/recipes/{r['id']}/consume")
    rows = await grocy().objects(
        "stock_log", query=[f"recipe_id={r['id']}", "undone=0"], order="id:desc", limit=1
    )
    return {
        "recipe": {"id": r["id"], "name": r.get("name")},
        "transaction_id": rows[0].get("transaction_id") if rows else None,
    }


@TOOLS.write(
    "Put the products a recipe is missing on the shopping list (only what is not in stock "
    "or already on the list), except `exclude_products`. " + WRITE_NOTE
)
async def recipe_add_missing_to_shopping_list(
    recipe: RecipeRef,
    exclude_products: Annotated[list[Ref], Field(max_length=100)] | None = None,
) -> dict[str, Any]:
    r = await resolve("recipe", recipe)
    excluded = [int((await resolve("product", p))["id"]) for p in exclude_products or []]
    await writer().post(
        f"/recipes/{r['id']}/add-not-fulfilled-products-to-shoppinglist",
        {"excludedProductIds": excluded},
    )
    f = await grocy().get(f"/recipes/{r['id']}/fulfillment") or {}
    return {
        "recipe": {"id": r["id"], "name": r.get("name")},
        "excluded_product_ids": excluded,
        **fulfillment_view(f),
    }


@TOOLS.write(
    "Create a recipe with its ingredients (products by id or exact name, amounts in each "
    f"product's stock unit; at most {INGREDIENTS_MAX}). Every product is checked before "
    "anything is created. " + WRITE_NOTE
)
async def recipe_create(
    name: Name,
    ingredients: Annotated[list[Ingredient], Field(max_length=INGREDIENTS_MAX)] | None = None,
    description: Description = "",
    servings: Servings = 1,
) -> dict[str, Any]:
    items = ingredients or []
    await _ingredient_rows(0, items)  # validate first
    created = await writer().post(
        "/objects/recipes",
        {
            "name": name.strip(),
            "description": description,
            "base_servings": servings,
            "desired_servings": servings,
            "type": "normal",
        },
    )
    rid = int(created["created_object_id"])
    added = 0
    for row in await _ingredient_rows(rid, items):
        try:
            await writer().post("/objects/recipes_pos", row)
        except (GrocyRejected, WriteOutcomeUnknown) as exc:
            raise PartialWrite(
                f"recipe {name!r} was created (id {rid}) but only {added} of {len(items)} "
                f"ingredients were added; ingredient {added} failed: {exc}"
            ) from exc
        added += 1
    return {"id": rid, "name": name.strip(), "ingredients_added": added}


@TOOLS.write(
    "Change a recipe's name, description or servings. Only the fields given change. " + WRITE_NOTE,
    annotations=SETS,
)
async def recipe_update(
    recipe: RecipeRef,
    name: Name | None = None,
    description: Description | None = None,
    servings: Servings | None = None,
) -> dict[str, Any]:
    r = await resolve("recipe", recipe)
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name.strip()
    if description is not None:
        body["description"] = description
    if servings is not None:
        body["desired_servings"] = servings
    require(bool(body), "nothing to change: give name, description or servings")
    await writer().put(f"/objects/recipes/{r['id']}", body)
    return {"id": r["id"], "changed": sorted(body)}


@TOOLS.write("Add one ingredient to a recipe. " + WRITE_NOTE)
async def recipe_ingredient_add(
    recipe: RecipeRef,
    product: Annotated[Ref, ref_field("product")],
    amount: Amount,
    note: Annotated[str | None, Field(max_length=500)] = None,
    group: Annotated[str | None, Field(max_length=100)] = None,
) -> dict[str, Any]:
    r = await resolve("recipe", recipe)
    (row,) = await _ingredient_rows(
        int(r["id"]), [Ingredient(product=product, amount=amount, note=note, group=group)]
    )
    created = await writer().post("/objects/recipes_pos", row)
    return {
        "recipe_id": r["id"],
        "ingredient_id": int(created["created_object_id"]),
        "product_id": row["product_id"],
    }


@TOOLS.write(
    "Remove one ingredient line from a recipe, by the ingredient_id recipe_details shows. "
    "The line must belong to that recipe. " + WRITE_NOTE,
    annotations=DESTROYS,
)
async def recipe_ingredient_remove(recipe: RecipeRef, ingredient_id: Id) -> dict[str, Any]:
    r = await resolve("recipe", recipe)
    try:
        pos = await grocy().object("recipes_pos", ingredient_id)
    except ToolInputError:
        raise ToolInputError(f"no ingredient {ingredient_id}") from None
    require(
        pos.get("recipe_id") == r["id"], f"ingredient {ingredient_id} is not in {r.get('name')!r}"
    )
    await writer().delete(f"/objects/recipes_pos/{ingredient_id}")
    return {"recipe_id": r["id"], "removed": ingredient_id, "product_id": pos.get("product_id")}
