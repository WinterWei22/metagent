"""Schema for the candidate_prefilter tool (Track A2).

Takes a precursor m/z + adduct (+ optional formula), returns a narrowed pool
of candidate structures before library_search or molecule_generate run.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from schemas.common import PrefilteredCandidate


class PrefilterRequest(BaseModel):
    precursor_mz: float = Field(..., gt=0)
    adduct: str = Field(..., description="E.g. '[M+H]+', '[M+Na]+', '[M-H]-'.")
    molecular_formula: str | None = Field(
        None,
        description="Hard constraint if known (e.g. from SIRIUS). Canonical Hill form, e.g. 'C6H12O6'.",
    )
    mass_tolerance_ppm: float = Field(5.0, gt=0, le=100)
    pools: list[Literal["gnps", "pubchem_lite", "hmdb"]] = Field(
        default_factory=lambda: ["gnps", "pubchem_lite"]
    )
    max_candidates: int = Field(5000, ge=1, le=100_000)


class PrefilterResponse(BaseModel):
    candidates: list[PrefilteredCandidate] = Field(
        ...,
        description="Sorted by mass_error_ppm ascending. May be empty.",
    )
    neutral_mass_computed: float = Field(
        ...,
        gt=0,
        description="Neutral exact mass backed out from precursor_mz and adduct.",
    )
    n_by_pool: dict[str, int] = Field(
        default_factory=dict,
        description="How many candidates came from each queried pool.",
    )
    explain: str
