# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Grocy server information."""

from __future__ import annotations

from typing import Any

from ..tooling import ToolGroup, grocy

TOOLS = ToolGroup()


@TOOLS.read("Grocy's version, PHP and SQLite versions, time zone and current local time.")
async def system_info() -> dict[str, Any]:
    g = grocy()
    info = await g.get("/system/info") or {}
    t = await g.get("/system/time") or {}
    version = info.get("grocy_version") or {}
    # Not `os` or `client`: the host's kernel string and our own user agent.
    return {
        "grocy_version": version.get("Version"),
        "grocy_release_date": version.get("ReleaseDate"),
        "php_version": info.get("php_version"),
        "sqlite_version": info.get("sqlite_version"),
        "timezone": t.get("timezone"),
        "local_time": t.get("time_local"),
    }
