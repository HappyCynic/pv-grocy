# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Names resolve exactly or not at all (ADR-0003)."""

from __future__ import annotations

from .conftest import Harness
from .fakegrocy import FakeGrocy, seed


async def test_exact_name_ignoring_case_and_spaces(h: Harness) -> None:
    for ref in ("Milk", "milk", "  MILK ", 1):
        assert (await h.call("stock_product", product=ref))["product"]["id"] == 1


async def test_a_part_of_a_name_is_never_picked(h: Harness, fake: FakeGrocy) -> None:
    msg = await h.error("stock_add", product="almond", amount=1)
    assert "no product is named exactly 'almond'" in msg and "'Almond milk' (id 2)" in msg
    assert fake.db["stock_log"] == seed()["stock_log"]


async def test_several_records_with_the_same_name(h: Harness, fake: FakeGrocy) -> None:
    fake.db["products"].append({**fake.db["products"][0], "id": 9})
    msg = await h.error("stock_product", product="Milk")
    assert "2 products are named 'Milk'" in msg and "use the id" in msg


async def test_unknown_id_and_unknown_name(h: Harness) -> None:
    assert "no product with id 42" in await h.error("stock_product", product=42)
    assert "no product named 'zzz'" in await h.error("stock_product", product="zzz")


async def test_internal_meal_plan_recipes_never_resolve(h: Harness) -> None:
    assert "no recipe with id -1" in await h.error("recipe_details", recipe=-1)
    assert "no recipe named '2026-42'" in await h.error("recipe_details", recipe="2026-42")
    names = [r["name"] for r in (await h.call("recipes_list"))["recipes"]]
    assert names == ["Omelette", "Pancakes"]


async def test_users_by_id_username_or_display_name(h: Harness) -> None:
    for ref in (2, "sam", "Sam"):
        out = await h.call("chore_execute", chore="Water plants", done_by=ref)
        assert out["execution_id"]
    assert "no user named 'pat'" in await h.error("chore_execute", chore=1, done_by="pat")
