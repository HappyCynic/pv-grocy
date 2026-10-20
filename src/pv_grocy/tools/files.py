# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Files Grocy stores (product and recipe pictures, equipment manuals, user files)."""

from __future__ import annotations

import base64
from typing import Annotated, Any, Literal

from pydantic import Field

from ..tooling import ToolGroup, grocy

TOOLS = ToolGroup()

FILE_MAX_BYTES = 4 * 1024 * 1024
FileGroup = Literal[
    "productpictures", "recipepictures", "equipmentmanuals", "userfiles", "userpictures"
]
FileName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=255,
        pattern=r"^[^/\\\x00-\x1f]+$",
        description="File name as Grocy shows it (e.g. a product's picture_file_name)",
    ),
]


def file_path(group: str, file_name: str) -> str:
    # Grocy takes the file name base64-encoded in the path.
    return f"/files/{group}/{base64.b64encode(file_name.encode()).decode()}"


@TOOLS.read(
    f"Download a file Grocy stores, as base64, at most {FILE_MAX_BYTES // (1024 * 1024)} MB. "
    "Pictures can be scaled down with best_fit_width / best_fit_height (pixels)."
)
async def file_download(
    group: FileGroup,
    file_name: FileName,
    best_fit_width: Annotated[int | None, Field(ge=16, le=4096)] = None,
    best_fit_height: Annotated[int | None, Field(ge=16, le=4096)] = None,
) -> dict[str, Any]:
    params: dict[str, str | int] = {}
    if best_fit_width or best_fit_height:
        params["force_serve_as"] = "picture"
        if best_fit_width:
            params["best_fit_width"] = best_fit_width
        if best_fit_height:
            params["best_fit_height"] = best_fit_height
    content, content_type = await grocy().get_bytes(
        file_path(group, file_name), FILE_MAX_BYTES, params or None
    )
    return {
        "group": group,
        "file_name": file_name,
        "content_type": content_type,
        "size": len(content),
        "content_base64": base64.b64encode(content).decode(),
    }
