"""Schemas for spectrum-centric tools: preprocess, library search, predict.

All three live here because they share the `Spectrum` value object and are
often composed in sequence by the orchestrator.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from schemas.common import Candidate, PrefilteredCandidate, Spectrum


# ---------------------------------------------------------------------------
# Tool 1: spectrum_preprocess
# ---------------------------------------------------------------------------


class PreprocessRequest(BaseModel):
    raw_mz: list[float] = Field(..., min_length=1)
    raw_intensity: list[float] = Field(..., min_length=1)
    precursor_mz: float = Field(..., gt=0)
    adduct: str
    ionization_mode: Literal["positive", "negative"]
    collision_energy: float | None = None
    min_relative_intensity: float = Field(
        0.01,
        ge=0.0,
        le=1.0,
        description="Peaks below this fraction of base peak are dropped.",
    )
    mz_tolerance_ppm: float = Field(5.0, gt=0, description="For merging near-duplicate peaks.")

    @model_validator(mode="after")
    def _check_equal_lengths(self) -> PreprocessRequest:
        if len(self.raw_mz) != len(self.raw_intensity):
            raise ValueError(
                f"raw_mz and raw_intensity length mismatch: "
                f"{len(self.raw_mz)} vs {len(self.raw_intensity)}"
            )
        return self


class PreprocessResponse(BaseModel):
    spectrum: Spectrum
    n_peaks_in: int = Field(..., ge=0)
    n_peaks_out: int = Field(..., ge=0)
    base_peak_mz: float
    base_peak_intensity: float
    quality_flag: Literal["good", "sparse", "noisy", "invalid"]
    explain: str


# ---------------------------------------------------------------------------
# Tool 2: library_search
# ---------------------------------------------------------------------------


class LibrarySearchRequest(BaseModel):
    spectrum: Spectrum
    candidate_pool: list[PrefilteredCandidate] | None = Field(
        None,
        description=(
            "Output from candidate_prefilter. When provided, only candidates "
            "with has_reference_spectrum=True are compared spectrally. When "
            "None, falls back to scanning the full GNPS v0-usable set."
        ),
    )
    top_k: int = Field(10, ge=0, le=100)
    min_score: float = Field(0.3, ge=0.0, le=1.0)
    libraries: list[Literal["inhouse", "gnps"]] = Field(
        default_factory=lambda: ["inhouse", "gnps"]
    )
    mass_tolerance_ppm: float | None = Field(
        None,
        ge=0.0,
        le=1000.0,
        description=(
            "Optional precursor-mass window (ppm) for the no-candidate-pool "
            "fallback path. When set, the GNPS scan only scores records whose "
            "precursor_mz is within ±tol_ppm of req.spectrum.precursor_mz. "
            "Default None preserves the original full-pool scan; recommended "
            "10 ppm for HRMS data."
        ),
    )
    excluded_source_ids: list[str] | None = Field(
        None,
        description=(
            "Optional list of GNPS spectrum_ids to remove from the no-pool "
            "fallback path BEFORE deduplication and scoring. The original "
            "self-exclusion contract is the caller's responsibility (see "
            "evaluation.sub6.identification.identify_spectrum); this field "
            "augments — does not replace — that audit by also keeping "
            "self-matches out of the in-tool dedup-by-SMILES step, which "
            "otherwise lets a 1.0 self-match absorb every other record "
            "sharing its SMILES once a tight mass-window has been applied. "
            "Default None preserves the original behaviour."
        ),
    )


class LibrarySearchResponse(BaseModel):
    candidates: list[Candidate] = Field(
        ..., description="Sorted descending by score. May be empty."
    )
    libraries_searched: list[str]
    n_total_compared: int = Field(..., ge=0)
    explain: str

    @model_validator(mode="after")
    def _check_sorted(self) -> LibrarySearchResponse:
        scores = [c.score for c in self.candidates]
        if scores != sorted(scores, reverse=True):
            raise ValueError("Candidates must be sorted descending by score.")
        return self


# ---------------------------------------------------------------------------
# Tool 6: predict_spectrum
# ---------------------------------------------------------------------------


class PredictSpectrumRequest(BaseModel):
    smiles: str = Field(..., min_length=1)
    adduct: str
    ionization_mode: Literal["positive", "negative"]
    collision_energies: list[float] = Field(
        default_factory=lambda: [10.0, 20.0, 40.0],
        description="CFM-ID uses these three as standard.",
    )
    top_n_peaks: int = Field(50, ge=1, le=500)


class PredictSpectrumResponse(BaseModel):
    predicted: Spectrum = Field(..., description="Union across collision energies, normalised.")
    per_energy: dict[float, Spectrum] = Field(
        default_factory=dict,
        description="Keyed by collision energy in eV. Optional but recommended.",
    )
    model_version: str = Field(..., description="E.g. 'cfm-id-4.0.0'. Recorded in every report.")
    explain: str
