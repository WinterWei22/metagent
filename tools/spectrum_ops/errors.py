"""Typed errors raised by spectrum_preprocess.

Every tool error inherits from schemas.common.ToolError so the orchestrator can
pattern-match on error class and surface a structured failure signal to the LLM.
"""
from __future__ import annotations

from schemas.common import ToolError


class InvalidSpectrumError(ToolError):
    """Raised when the input peak list cannot be cleaned into a usable Spectrum.

    Triggers:
      - all peak intensities are non-positive,
      - fewer than 3 peaks survive the relative-intensity filter + ppm merge,
      - a belt-and-suspenders length mismatch that somehow bypassed the
        Pydantic validator (normally caught at request construction time).
    """

    code = "INVALID_SPECTRUM"
    recoverable = False
