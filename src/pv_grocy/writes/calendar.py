# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""The iCal sharing link: a read, but the link is a credential (anyone with it can read the
calendar without logging in), so only full-access tokens get it (ADR-0002)."""

from __future__ import annotations

from typing import Any

from ..tooling import ToolGroup, grocy

TOOLS = ToolGroup()


@TOOLS.full_read(
    "Grocy's public iCal sharing link. Anyone who has this link can read the household "
    "calendar without logging in: share it only with the user's explicit request."
)
async def calendar_sharing_link() -> dict[str, Any]:
    d = await grocy().get("/calendar/ical/sharing-link") or {}
    return {"url": d.get("url")}
