# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Write tools (ADR-0002). Imported only when PV_GROCY_WRITE=enabled; nothing here runs on
its own (no startup or background writes): only a granted tool call changes Grocy."""

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
    printing,
    recipes,
    shopping,
    stock,
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
        workflows,
        printing,
        files,
        calendar,
    )
)
