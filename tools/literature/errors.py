"""Typed errors raised by literature_search.

Subclasses of `schemas.common.ToolError` so the orchestrator can pattern-match
on error class. Returning an empty list is a valid response — only API-side
failures escalate to a raised error.
"""
from __future__ import annotations

from schemas.common import ToolError


class RateLimitError(ToolError):
    """Raised when the upstream API returns HTTP 429.

    Recoverable in principle (the orchestrator may back off and retry), but
    this tool itself does not retry — the contract says "no caching, fresh
    call each time", so retry policy belongs to the caller.
    """

    code = "RATE_LIMIT"
    recoverable = True


class LiteratureBackendError(ToolError):
    """Raised when an API responds with a non-2xx, non-429 status, or its
    payload cannot be decoded as the expected JSON / XML shape.

    Distinct from RateLimitError so the orchestrator can decide to fall back
    to a different source rather than back off.
    """

    code = "LITERATURE_BACKEND"
    recoverable = False
