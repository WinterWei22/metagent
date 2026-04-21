"""Schemas for molecule-centric tools: de novo generation and metadata lookup."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from schemas.common import Candidate, PrefilteredCandidate, Spectrum


# ---------------------------------------------------------------------------
# Tool 3: molecule_generate
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    spectrum: Spectrum
    molecular_formula: str | None = Field(
        None,
        description="If known (e.g. from SIRIUS upstream), enforced as a hard constraint.",
    )
    candidate_pool: list[PrefilteredCandidate] | None = Field(
        None,
        description=(
            "Optional output from candidate_prefilter. When provided, the generator "
            "should prefer candidates with matching exact mass from this pool over "
            "fully free generation. Exact blending strategy is left to the model wrapper."
        ),
    )
    n_candidates: int = Field(20, ge=0, le=200)
    max_molecular_weight: float = Field(1500.0, gt=0)


class GenerateResponse(BaseModel):
    candidates: list[Candidate] = Field(
        ...,
        description="All SMILES are guaranteed to parse under RDKit. Invalid ones are filtered.",
    )
    n_generated_raw: int = Field(..., ge=0, description="How many the model emitted before validation.")
    n_valid: int = Field(..., ge=0, description="How many passed RDKit validation.")
    explain: str


# ---------------------------------------------------------------------------
# Tool 4: fetch_metabolite_info
# ---------------------------------------------------------------------------


class MetaboliteInfoRequest(BaseModel):
    identifier: str = Field(..., min_length=1)
    id_type: Literal["hmdb", "kegg", "inchikey", "smiles", "name", "auto"] = "auto"


class MetaboliteInfoResponse(BaseModel):
    """Structured metabolite metadata.

    When `found` is False, all other fields are None or empty. Partial hits are
    still a valid response: unknown fields default to None / [] rather than being
    invented. This is a trust anchor for the verifier.
    """

    found: bool
    primary_name: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    molecular_formula: str | None = None
    exact_mass: float | None = None
    smiles: str | None = None
    inchikey: str | None = None
    chemical_class: str | None = None
    tissue_locations: list[str] = Field(default_factory=list)
    disease_associations: list[str] = Field(default_factory=list)
    cross_refs: dict[str, str] = Field(
        default_factory=dict,
        description="Keys: 'hmdb', 'kegg', 'chebi', 'pubchem_cid', 'chembl', etc.",
    )
    source: Literal["hmdb", "pubchem", "kegg", "cached"] | None = None
    explain: str
