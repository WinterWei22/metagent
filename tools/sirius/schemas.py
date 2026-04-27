"""Pydantic schemas for ``sirius_annotate``.

These schemas are tool-local by design. The only shared type is
``schemas.common.Spectrum``, which is the input spectrum value object used
across the project.
"""
from __future__ import annotations

from bisect import bisect_left
from typing import Literal

from pydantic import BaseModel, Field

from schemas.common import Spectrum


class FragmentAnnotation(BaseModel):
    """One node in a SIRIUS fragmentation tree."""

    mz_observed: float = Field(..., gt=0)
    formula: str = Field(..., min_length=1)
    formula_score: float = Field(..., ge=0.0, le=1.0)
    neutral_loss: str = ""
    neutral_loss_formula: str = ""
    intensity: float = Field(..., ge=0.0, le=1.0)
    depth: int = Field(..., ge=0)


class SiriusAnnotateRequest(BaseModel):
    """Request for SIRIUS formula/tree annotation of a single MS/MS spectrum."""

    spectrum: Spectrum
    instrument_preset: Literal["orbitrap", "qtof", "fticr"] = "orbitrap"
    timeout_seconds: int = Field(120, gt=0)


class SiriusAnnotateResponse(BaseModel):
    """Top formula prediction plus a lookup-ready fragmentation tree."""

    predicted_formula: str = Field(..., min_length=1)
    formula_score: float = Field(..., ge=0.0, le=1.0)
    fragments: list[FragmentAnnotation]
    tree_node_count: int = Field(..., ge=0)
    sirius_version: str = Field(..., min_length=1)
    explain: str = Field(..., min_length=1)

    def lookup_fragment(
        self,
        mz: float,
        tolerance_ppm: float = 5.0,
    ) -> FragmentAnnotation | None:
        """Return the closest fragment within ``tolerance_ppm`` of ``mz``."""
        if mz <= 0 or tolerance_ppm <= 0 or not self.fragments:
            return None

        fragments = sorted(self.fragments, key=lambda frag: frag.mz_observed)
        masses = [frag.mz_observed for frag in fragments]
        tolerance_da = mz * tolerance_ppm / 1_000_000.0
        pos = bisect_left(masses, mz)

        candidates: list[FragmentAnnotation] = []
        if pos < len(fragments):
            candidates.append(fragments[pos])
        if pos > 0:
            candidates.append(fragments[pos - 1])

        best: FragmentAnnotation | None = None
        best_delta = float("inf")
        for frag in candidates:
            delta = abs(frag.mz_observed - mz)
            if delta <= tolerance_da and delta < best_delta:
                best = frag
                best_delta = delta
        return best
