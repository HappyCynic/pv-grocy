# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Task changes."""

from __future__ import annotations

from typing import Annotated, Any

from ..config import Access
from ..errors import ToolInputError
from ..resolve import Ref, resolve_optional, resolve_user
from ..tooling import (
    DESTROYS,
    NO_UNDO,
    WRITE_NOTE,
    Date,
    DateTime,
    Id,
    Name,
    Text,
    ToolGroup,
    grocy,
    ref_field,
    writer,
)

TOOLS = ToolGroup()


async def _task(task_id: int) -> dict[str, Any]:
    try:
        return await grocy().object("tasks", task_id)
    except ToolInputError:
        raise ToolInputError(f"no task {task_id}") from None


@TOOLS.write(
    "Create a task (a to-do), optionally with a due date, category and assignee. " + WRITE_NOTE
)
async def task_create(
    name: Name,
    description: Text = "",
    due_date: Date | None = None,
    category: Annotated[Ref | None, ref_field("task category")] = None,
    assigned_to: Annotated[Ref | None, ref_field("user")] = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name.strip(), "description": description}
    if due_date:
        body["due_date"] = due_date
    if (cat := await resolve_optional("task_category", category)) is not None:
        body["category_id"] = cat
    if assigned_to is not None:
        body["assigned_to_user_id"] = (await resolve_user(assigned_to))["id"]
    created = await writer().post("/objects/tasks", body)
    return {"id": int(created["created_object_id"]), "name": name.strip()}


@TOOLS.write("Mark a task done, now or at `done_time`. task_undo reverts it. " + WRITE_NOTE)
async def task_complete(task_id: Id, done_time: DateTime | None = None) -> dict[str, Any]:
    await _task(task_id)
    await writer().post(f"/tasks/{task_id}/complete", {"done_time": done_time} if done_time else {})
    return {"id": task_id, "done": True}


@TOOLS.write("Mark a done task as not done again. " + WRITE_NOTE)
async def task_undo(task_id: Id) -> dict[str, Any]:
    await _task(task_id)
    await writer().post(f"/tasks/{task_id}/undo")
    return {"id": task_id, "done": False}


@TOOLS.write(
    "Delete a task. " + NO_UNDO + " Prefer task_complete for finished tasks. " + WRITE_NOTE,
    access=Access.FULL,
    annotations=DESTROYS,
)
async def task_delete(task_id: Id) -> dict[str, Any]:
    t = await _task(task_id)
    await writer().delete(f"/objects/tasks/{task_id}")
    return {"deleted": task_id, "name": t.get("name")}
