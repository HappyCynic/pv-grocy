# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""File uploads and deletes (full access)."""

from __future__ import annotations

import base64
import binascii
from typing import Annotated, Any

from pydantic import Field

from ..config import Access
from ..errors import ToolInputError
from ..tooling import DESTROYS, NO_UNDO, WRITE_NOTE, ToolGroup, writer
from ..tools.files import FILE_MAX_BYTES, FileGroup, FileName, file_path

TOOLS = ToolGroup()


@TOOLS.write(
    f"Upload a file to Grocy from base64 (at most {FILE_MAX_BYTES // (1024 * 1024)} MB). Grocy "
    "refuses to overwrite an existing file. To use it as a product's picture, set the "
    "product's picture_file_name with catalog_update. " + WRITE_NOTE,
    access=Access.FULL,
)
async def file_upload(
    group: FileGroup,
    file_name: FileName,
    content_base64: Annotated[str, Field(min_length=1, max_length=FILE_MAX_BYTES * 4 // 3 + 4)],
) -> dict[str, Any]:
    try:
        content = base64.b64decode(content_base64, validate=True)
    except binascii.Error, ValueError:
        raise ToolInputError("content_base64 is not valid base64") from None
    if len(content) > FILE_MAX_BYTES:
        raise ToolInputError(f"file is larger than {FILE_MAX_BYTES} bytes")
    await writer().put_bytes(file_path(group, file_name), content)
    return {"group": group, "file_name": file_name, "size": len(content)}


@TOOLS.write(
    "Delete a file Grocy stores. " + NO_UNDO + " " + WRITE_NOTE,
    access=Access.FULL,
    annotations=DESTROYS,
)
async def file_delete(group: FileGroup, file_name: FileName) -> dict[str, Any]:
    await writer().delete(file_path(group, file_name))
    return {"group": group, "deleted": file_name}
