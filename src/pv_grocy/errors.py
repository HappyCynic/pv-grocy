# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Errors with messages that are safe to show the caller (and to log)."""

from __future__ import annotations


class ToolInputError(ValueError):
    """Bad arguments, or a name or id that cannot be served."""


class GrocyUnavailable(Exception):
    """Grocy could not be reached or failed. Nothing was changed (reads, or writes that were
    never sent)."""


class GrocyRejected(Exception):
    """Grocy refused the request (HTTP 400). The text is Grocy's own error message, capped."""


class GrocyAuthFailed(Exception):
    """Grocy refused pv-grocy's API key. An operator problem, not the caller's."""


class WriteOutcomeUnknown(Exception):
    """A write was sent but Grocy did not confirm it (timeout, dropped connection or a server
    error). It may or may not have been applied, so it is never retried automatically."""


class PartialWrite(Exception):
    """A multi-step write stopped part-way. The message says exactly what was changed."""
