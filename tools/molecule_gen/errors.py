"""Typed errors for molecule_generate. Every error is a ToolError subclass
so the orchestrator can pattern-match without string parsing.
"""
from __future__ import annotations

from schemas.common import ToolError


class ModelLoadError(ToolError):
    code = "MOLECULE_GEN_MODEL_LOAD"
    recoverable = False


class NoValidCandidatesError(ToolError):
    code = "MOLECULE_GEN_NO_VALID"
    recoverable = True


class FingerprinterError(ToolError):
    code = "MOLECULE_GEN_FINGERPRINTER"
    recoverable = False
