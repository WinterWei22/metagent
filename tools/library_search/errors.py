"""Typed errors for library_search. Every error is a ToolError subclass so the
orchestrator can pattern-match without string parsing.
"""
from __future__ import annotations

from schemas.common import ToolError


class LibraryUnavailableError(ToolError):
    """Raised when a requested reference library cannot be loaded.

    Examples: METAGENT_GNPS_PATH unset while the GNPS fallback path is needed,
    file not readable, JSON parse failure.
    """

    code = "LIBRARY_SEARCH_LIBRARY_UNAVAILABLE"
    recoverable = False


class InHouseModelError(ToolError):
    """Raised when the in-house ms-clip retriever cannot run.

    Examples: checkpoint missing, conda env not found, subprocess non-zero exit,
    prediction pickle malformed.
    """

    code = "LIBRARY_SEARCH_INHOUSE_MODEL"
    recoverable = True
