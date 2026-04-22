"""Typed errors for candidate_prefilter. Every error is a ToolError subclass
so the orchestrator can pattern-match without string parsing.
"""
from __future__ import annotations

from schemas.common import ToolError


class InvalidAdductError(ToolError):
    """The requested adduct string is not in the supported table.

    Adducts are a small finite set — if the LLM emits something we don't
    recognise, fail loud so the orchestrator can retry with a known adduct
    rather than silently returning wrong masses.
    """

    code = "PREFILTER_INVALID_ADDUCT"
    recoverable = True


class PubChemLiteNotBuiltError(ToolError):
    """The PubChem Lite SQLite DB path is unset or the file does not exist.

    Rebuilding the DB is a one-time operator task (see build_pubchem_lite.py).
    Not recoverable by retry — the caller must install the DB and re-run.
    """

    code = "PREFILTER_PUBCHEM_LITE_MISSING"
    recoverable = False
