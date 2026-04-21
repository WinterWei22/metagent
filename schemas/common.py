"""Shared data types used across all tools.

Nothing in this file imports from tools/. Tools import from here, never the reverse.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Base class for all tool-raised errors.

    Tools should raise a subclass of this rather than returning partial results.
    The orchestrator catches ToolError subclasses and surfaces them to the LLM
    as structured failure signals.
    """

    code: str = "TOOL_ERROR"
    recoverable: bool = False

    def __init__(self, message: str, *, code: str | None = None, recoverable: bool | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if recoverable is not None:
            self.recoverable = recoverable

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
        }


# ---------------------------------------------------------------------------
# Core value objects
# ---------------------------------------------------------------------------


class Spectrum(BaseModel):
    """A cleaned, normalised MS/MS spectrum.

    Raw spectra should be passed through spectrum_preprocess before being wrapped
    in this type. Downstream tools assume mz is sorted ascending and intensities
    are normalised to the interval [0, 1] with the base peak at 1.0.
    """

    model_config = ConfigDict(frozen=False)

    mz: list[float] = Field(..., description="Mass-to-charge ratios, sorted ascending.")
    intensity: list[float] = Field(..., description="Normalised intensities in [0, 1].")
    precursor_mz: float = Field(..., gt=0)
    adduct: str = Field(..., description="E.g. '[M+H]+', '[M-H]-', '[M+Na]+'.")
    ionization_mode: Literal["positive", "negative"]
    collision_energy: float | None = Field(None, description="eV, optional.")

    @model_validator(mode="after")
    def _check_lengths(self) -> Spectrum:
        if len(self.mz) != len(self.intensity):
            raise ValueError(
                f"mz and intensity length mismatch: {len(self.mz)} vs {len(self.intensity)}"
            )
        if len(self.mz) == 0:
            raise ValueError("Spectrum must have at least one peak.")
        if any(v < 0 or v > 1 for v in self.intensity):
            raise ValueError("Intensity values must be in [0, 1] after preprocessing.")
        return self


class Candidate(BaseModel):
    """A proposed molecular identification.

    `score` is always normalised to [0, 1] regardless of the originating model's
    native scale. Each tool is responsible for calibrating its own scores before
    emitting Candidates so that the orchestrator can compare across tools.
    """

    smiles: str
    name: str | None = None
    source: Literal["library", "generated", "reference"]
    score: float = Field(..., ge=0.0, le=1.0)
    source_id: str | None = Field(
        None,
        description="HMDB ID, GNPS accession, internal model run ID, etc. Must be stable and lookup-able.",
    )
    explain: str = Field(
        ...,
        description="One or two sentences on why this candidate was proposed. Consumed by the reporter.",
    )


class LiteratureRecord(BaseModel):
    """A single literature hit. Every field except doi is required to be non-null.

    `abstract` may be an empty string when the source API returns no abstract,
    but must never be synthesised.
    """

    pmid: str = Field(..., pattern=r"^\d+$", description="Numeric PMID, no 'PMID:' prefix.")
    title: str
    abstract: str = Field(..., description="Verbatim from source API. Empty string if unavailable.")
    authors: list[str]
    year: int = Field(..., ge=1800, le=2100)
    journal: str
    doi: str | None = None
    url: str


class PathwayEntry(BaseModel):
    """One pathway that a metabolite belongs to."""

    id: str = Field(..., description="E.g. 'hsa00010' for KEGG or 'R-HSA-70171' for Reactome.")
    name: str
    source: Literal["kegg", "reactome", "smpdb", "wikipathways"]
    hit_count: int = Field(
        ...,
        ge=0,
        description="Count of queried metabolites (focal + co-observed) present in this pathway.",
    )
    url: str


class PrefilteredCandidate(BaseModel):
    """A candidate structure surviving the mass/formula pre-filter.

    Produced by the candidate_prefilter tool. Consumed by library_search and
    molecule_generate as an optional pool-narrowing input. Unlike `Candidate`,
    this type does NOT carry a match score against an MS/MS spectrum — it is
    purely structural.
    """

    smiles: str
    name: str | None = None
    source_pool: Literal["gnps", "pubchem_lite", "hmdb"]
    source_id: str = Field(
        ...,
        description="Stable identifier in the source pool: CCMSLIB ID, PubChem CID, or HMDB ID.",
    )
    molecular_formula: str
    exact_mass: float = Field(..., gt=0)
    mass_error_ppm: float = Field(..., ge=0)
    has_reference_spectrum: bool = Field(
        ...,
        description=(
            "True iff this candidate has an MS/MS spectrum available (currently only "
            "meaningful for pool='gnps'). library_search uses this to decide which "
            "candidates it can actually match spectrally."
        ),
    )
