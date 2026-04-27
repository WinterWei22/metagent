"""Typed errors for the SIRIUS fragmentation-tree tool."""
from __future__ import annotations

from schemas.common import ToolError


class SiriusNotInstalledError(ToolError):
    """The SIRIUS executable cannot be resolved or executed."""

    code = "SIRIUS_NOT_INSTALLED"
    recoverable = False


class SiriusTimeoutError(ToolError):
    """SIRIUS did not finish within the request timeout."""

    code = "SIRIUS_TIMEOUT"
    recoverable = True


class SiriusParseError(ToolError):
    """SIRIUS produced malformed or unsupported output."""

    code = "SIRIUS_PARSE_ERROR"
    recoverable = False


class SiriusNoFormulaError(ToolError):
    """SIRIUS completed but produced no molecular formula candidate."""

    code = "SIRIUS_NO_FORMULA"
    recoverable = True
