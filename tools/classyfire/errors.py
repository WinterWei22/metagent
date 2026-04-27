"""Structured errors raised by the ClassyFire tool."""
from __future__ import annotations

from schemas.common import ToolError


class ClassyfireAPIError(ToolError):
    """HTTP error from ClassyFire API."""

    code = "CLASSYFIRE_API_ERROR"
    recoverable = True


class ClassyfireTimeoutError(ToolError):
    """Batch job did not complete within timeout."""

    code = "CLASSYFIRE_TIMEOUT"
    recoverable = True


class ClassyfireNotFoundError(ToolError):
    """Compound not in ClassyFire database.

    This is not a contradiction signal. Verifier callers should treat it as
    UNVERIFIABLE_V0 because novel or rare compounds may be absent.
    """

    code = "CLASSYFIRE_NOT_FOUND"
    recoverable = True


class InvalidStructureError(ToolError):
    """SMILES failed RDKit validation before hitting the API."""

    code = "INVALID_STRUCTURE"
    recoverable = False
