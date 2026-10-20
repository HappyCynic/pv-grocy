# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Read tools: every module here only reads Grocy (through GrocyReader)."""

from __future__ import annotations

from ..tooling import ToolGroup
from . import (
    batteries,
    calendar,
    catalog,
    chores,
    equipment,
    files,
    meal_plan,
    recipes,
    shopping,
    stock,
    system,
    tasks,
    workflows,
)

GROUPS: tuple[ToolGroup, ...] = tuple(
    m.TOOLS
    for m in (
        stock,
        shopping,
        recipes,
        meal_plan,
        chores,
        tasks,
        batteries,
        equipment,
        catalog,
        calendar,
        files,
        workflows,
        system,
    )
)
