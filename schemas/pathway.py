"""Schemas for context-providing tools: pathway membership and literature search."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from schemas.common import LiteratureRecord, PathwayEntry


# ---------------------------------------------------------------------------
# Tool 5: pathway_context
# ---------------------------------------------------------------------------


class PathwayContextRequest(BaseModel):
    metabolite_id: str = Field(
        ...,
        min_length=1,
        description="HMDB ID or KEGG compound ID. Resolution is handled internally.",
    )
    organism: str = Field("hsa", description="KEGG organism code. Default human.")
    co_observed_ids: list[str] = Field(
        default_factory=list,
        description="Other metabolites detected in the same sample. Used for cooccurrence scoring.",
    )
    neighbour_depth: int = Field(1, ge=0, le=3)
    max_pathways: int = Field(10, ge=1, le=50)


class PathwayContextResponse(BaseModel):
    pathways: list[PathwayEntry]
    upstream_neighbours: list[str] = Field(
        default_factory=list,
        description="Metabolite IDs one reaction upstream of the focal metabolite.",
    )
    downstream_neighbours: list[str] = Field(default_factory=list)
    cooccurrence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of immediate neighbours that also appear in co_observed_ids.",
    )
    plausibility_summary: str = Field(
        ...,
        max_length=800,
        description=(
            "Templated natural-language summary suitable for direct inclusion in the report. "
            "Written by the tool, not the LLM."
        ),
    )
    explain: str


# ---------------------------------------------------------------------------
# Tool 7: literature_search
# ---------------------------------------------------------------------------


class LiteratureSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    max_results: int = Field(5, ge=0, le=50)
    year_from: int | None = Field(None, ge=1800, le=2100)
    sources: list[Literal["pubmed", "europepmc"]] = Field(
        default_factory=lambda: ["europepmc"]
    )


class LiteratureSearchResponse(BaseModel):
    records: list[LiteratureRecord]
    query_used: str = Field(
        ...,
        description="Actual query sent to the API. May differ from input after normalisation.",
    )
    explain: str
