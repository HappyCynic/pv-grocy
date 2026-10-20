# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Per-token write limit (ADR-0002): a sliding one-hour window, held in memory only.

It guards against a runaway or prompt-injected client, not against the operator, so the
counts are not persisted and reset when the server restarts.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

WINDOW_SECONDS = 3600.0


class WriteLimitReached(Exception):
    def __init__(self, limit: int, minutes: int):
        super().__init__(
            f"write limit reached for this token ({limit} per hour); try again in about "
            f"{minutes} minute{'s' if minutes != 1 else ''}; nothing was changed"
        )


class WriteLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._calls: dict[str, deque[float]] = {}

    def check(self, key: str, limit: int, count: int = 1) -> None:
        """Count `count` writes for `key`, or raise WriteLimitReached (nothing counted)."""
        now = self._clock()
        with self._lock:
            calls = self._calls.setdefault(key, deque())
            while calls and calls[0] <= now - WINDOW_SECONDS:
                calls.popleft()
            if len(calls) + count > limit:
                wait = (calls[0] + WINDOW_SECONDS - now) if calls else WINDOW_SECONDS
                raise WriteLimitReached(limit, max(1, round(wait / 60)))
            calls.extend([now] * count)
