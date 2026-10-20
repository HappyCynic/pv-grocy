# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Task reads (to-dos, separate from chores)."""

from __future__ import annotations

from typing import Any

from ..resolve import names
from ..tooling import LIMIT_DEFAULT, PAGING_NOTE, Limit, Offset, ToolGroup, flag, grocy, paged

TOOLS = ToolGroup()


@TOOLS.read(
    "Tasks (to-dos) with id, due date, category, assignee and whether done; by default only "
    f"open ones. At most {LIMIT_DEFAULT} per page by default. " + PAGING_NOTE
)
async def tasks_list(
    include_done: bool = False, limit: Limit = LIMIT_DEFAULT, offset: Offset = 0
) -> dict[str, Any]:
    g = grocy()
    rows = await g.objects("tasks", query=[] if include_done else ["done=0"])
    categories = await names("task_categories")
    users = {int(u["id"]): u.get("display_name") for u in await g.get("/users") or []}
    tasks = [
        {
            "id": t.get("id"),
            "name": t.get("name"),
            "description": t.get("description"),
            "due_date": t.get("due_date"),
            "category": categories.get(t.get("category_id") or 0),
            "assigned_to": users.get(t.get("assigned_to_user_id") or 0),
            "done": flag(t.get("done")),
            "done_time": t.get("done_timestamp"),
        }
        for t in rows
    ]
    tasks.sort(key=lambda t: (t["done"], str(t["due_date"] or "9999"), str(t["name"])))
    return paged("tasks", tasks, limit, offset)
