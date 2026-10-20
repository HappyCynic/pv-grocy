# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Generic row writes: master data (catalog_*, write access) and any editable entity
(entity_*, full access). Entity names are checked against entities.py."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..config import Access
from ..entities import CATALOG, DELETABLE, EDITABLE, PROTECTED_FIELDS, check_entity
from ..errors import ToolInputError
from ..tooling import DESTROYS, NO_UNDO, SETS, WRITE_NOTE, Id, ToolGroup, grocy, require, writer
from ..tools.catalog import Entity

TOOLS = ToolGroup()

Scalar = str | int | float | bool | None
Fields = Annotated[
    dict[str, Scalar],
    Field(
        min_length=1,
        max_length=50,
        description="Column -> value (see entity_describe for the columns). Booleans are "
        "stored as 0/1; ids are integers",
    ),
]
CATALOG_LIST = ", ".join(sorted(CATALOG))


def _fields(fields: dict[str, Scalar]) -> dict[str, Any]:
    bad = sorted(set(fields) & PROTECTED_FIELDS)
    require(not bad, f"cannot set {', '.join(bad)}")
    for k, v in fields.items():
        require(k.replace("_", "").isalnum(), f"invalid field name {k!r}")
        if isinstance(v, str):
            require(len(v) <= 20_000, f"{k}: at most 20000 characters")
    return {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items()}


async def _exists(entity: str, obj_id: int) -> dict[str, Any]:
    try:
        return await grocy().object(entity, obj_id)
    except ToolInputError:
        raise ToolInputError(f"no {entity} row with id {obj_id}") from None


@TOOLS.write(
    f"Create a master-data row: one of {CATALOG_LIST} (e.g. a new product, location or "
    "store). Returns the new id. " + WRITE_NOTE
)
async def catalog_create(entity: Entity, fields: Fields) -> dict[str, Any]:
    check_entity(entity, CATALOG, "create")
    created = await writer().post(f"/objects/{entity}", _fields(fields))
    return {"entity": entity, "id": int(created["created_object_id"])}


@TOOLS.write(
    f"Change fields of a master-data row ({CATALOG_LIST}); only the fields given change. "
    + WRITE_NOTE,
    annotations=SETS,
)
async def catalog_update(entity: Entity, id: Id, fields: Fields) -> dict[str, Any]:
    check_entity(entity, CATALOG, "update")
    await _exists(entity, id)
    await writer().put(f"/objects/{entity}/{id}", _fields(fields))
    return {"entity": entity, "id": id, "changed": sorted(fields)}


@TOOLS.write(
    "Create a row in any editable Grocy entity, raw (no checks beyond Grocy's own). Prefer "
    "the specific tools and catalog_create. " + WRITE_NOTE,
    access=Access.FULL,
)
async def entity_create(entity: Entity, fields: Fields) -> dict[str, Any]:
    check_entity(entity, EDITABLE, "create")
    created = await writer().post(f"/objects/{entity}", _fields(fields))
    return {"entity": entity, "id": int(created["created_object_id"])}


@TOOLS.write(
    "Change fields of a row in any editable Grocy entity, raw; only the fields given change. "
    "Prefer the specific tools and catalog_update. " + WRITE_NOTE,
    access=Access.FULL,
    annotations=SETS,
)
async def entity_update(entity: Entity, id: Id, fields: Fields) -> dict[str, Any]:
    check_entity(entity, EDITABLE, "update")
    await _exists(entity, id)
    await writer().put(f"/objects/{entity}/{id}", _fields(fields))
    return {"entity": entity, "id": id, "changed": sorted(fields)}


@TOOLS.write(
    "Delete a row of any deletable Grocy entity. Grocy may delete dependent rows with it "
    "(e.g. a product's stock and barcodes). " + NO_UNDO + " " + WRITE_NOTE,
    access=Access.FULL,
    annotations=DESTROYS,
)
async def entity_delete(entity: Entity, id: Id) -> dict[str, Any]:
    check_entity(entity, DELETABLE, "delete")
    row = await _exists(entity, id)
    await writer().delete(f"/objects/{entity}/{id}")
    return {"entity": entity, "deleted": id, "name": row.get("name")}
