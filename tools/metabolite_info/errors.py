"""Typed errors for fetch_metabolite_info.

Only one failure mode raises: a structurally malformed identifier string.
A valid-looking identifier that simply has no match returns `found=False`
rather than raising, so the orchestrator can distinguish "unknown compound"
from "bad input".
"""
from __future__ import annotations

from schemas.common import ToolError


class IdentifierFormatError(ToolError):
    """The identifier string is empty, whitespace-only, or otherwise malformed.

    Raised before any backend lookup. The orchestrator should treat this as
    a programming error on the caller's side, not an absent compound.
    """

    code = "METABOLITE_INFO_IDENTIFIER_FORMAT"
    recoverable = True
