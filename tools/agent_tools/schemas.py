"""LLM-facing Pydantic input schemas for the 5 agent tools.

Two design rules:

1. Inputs use plain types only (str / int / list[str]) so the OpenAI-style
   tool definition can JSON-schema them faithfully. No nested objects;
   the LLM should never need to produce a nested JSON to call a tool.

2. Validation errors raise ``pydantic.ValidationError``; the dispatcher
   catches and converts to ``{"error": "validation_error", ...}`` so the
   LLM sees the failure as a tool result and can retry.

Output schemas are intentionally NOT enforced by Pydantic — wrappers
return plain ``dict`` projections sized to fit the 2 KB tool-result
budget. Use ``truncate_to_budget`` to enforce the cap.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Output budget
# ---------------------------------------------------------------------------

# Per spec pitfall #3: tool_result payload limited to ~2 KB so the LLM's
# context cannot be drowned by a single hit. Callers that need more should
# call again with a tighter parameter (e.g. top_k).
TOOL_RESULT_BUDGET_BYTES = 2048


def truncate_to_budget(
    payload: dict[str, Any],
    *,
    truncatable_key: str | None = None,
    more_hint: str | None = None,
    budget: int = TOOL_RESULT_BUDGET_BYTES,
) -> dict[str, Any]:
    """Return ``payload`` if its JSON serialisation fits ``budget`` bytes.

    If the payload is over budget AND ``truncatable_key`` points at a list
    field, items are dropped from the tail until the result fits, with a
    ``_truncated`` note added. If still over budget, the value at
    ``truncatable_key`` is replaced with an empty list and an apology
    string is added.

    Never raises; never returns ``None``.
    """
    blob = json.dumps(payload, ensure_ascii=False, default=str)
    if len(blob.encode("utf-8")) <= budget:
        return payload

    if truncatable_key and isinstance(payload.get(truncatable_key), list):
        items = list(payload[truncatable_key])
        while items:
            items.pop()
            payload = {**payload, truncatable_key: items}
            blob = json.dumps(payload, ensure_ascii=False, default=str)
            if len(blob.encode("utf-8")) <= budget - 80:  # leave room for hint
                payload["_truncated"] = (
                    f"dropped {len(payload[truncatable_key]) - len(items) + 1} "
                    f"trailing items to fit {budget}-byte budget"
                )
                if more_hint:
                    payload["_more"] = more_hint
                return payload

    # Still over budget: keep top-level keys but null out big fields.
    return {
        "error": "result_too_large",
        "fallback_suggested": (
            "the underlying tool returned more data than fits in the 2 KB "
            "tool-result budget; rerun with a smaller top_k / max_results"
        ),
        "_original_size_bytes": len(blob.encode("utf-8")),
    }


# ---------------------------------------------------------------------------
# Tool 1 — query_ramp_enrichment
# ---------------------------------------------------------------------------


class RampEnrichmentInput(BaseModel):
    """Run hypergeometric pathway enrichment on a compound list."""

    compound_kegg_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "List of KEGG compound IDs (e.g. 'C00031' or 'cpd:C00031'). "
            "At least one ID required. Both bare and 'cpd:' prefixed forms "
            "accepted; case-insensitive."
        ),
    )
    top_k: int = Field(
        5,
        ge=1,
        le=20,
        description="Top-K pathways to return, ranked by FDR ascending.",
    )


# ---------------------------------------------------------------------------
# Tool 2 — query_pathway_membership
# ---------------------------------------------------------------------------


class PathwayMembershipInput(BaseModel):
    """Look up which pathways a single metabolite belongs to."""

    metabolite_id: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description=(
            "KEGG compound ID ('C00031'/'cpd:C00031') OR HMDB ID "
            "('HMDB0000122'). Free-text names are NOT accepted here."
        ),
    )
    co_observed_ids: list[str] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "Optional: other metabolites observed in the same sample, used "
            "to compute a co-occurrence plausibility score. Same ID format "
            "as metabolite_id."
        ),
    )
    max_pathways: int = Field(10, ge=1, le=30)


# ---------------------------------------------------------------------------
# Tool 3 — query_kegg_path
# ---------------------------------------------------------------------------


class KeggPathInput(BaseModel):
    """Check whether one KEGG compound is upstream of another via BFS."""

    compound_a: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description=(
            "Source compound. Accepts KEGG cpd ID ('C00073'), HMDB ID "
            "('HMDB0000696'), 14-char InChIKey first-block, or canonical name."
        ),
    )
    compound_b: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Target compound. Same formats as compound_a.",
    )
    max_path_length: int = Field(
        6,
        ge=1,
        le=8,
        description="BFS hop budget. Default 6 matches verifier Layer 6d.",
    )


# ---------------------------------------------------------------------------
# Tool 4 — lookup_compound_info
# ---------------------------------------------------------------------------


class CompoundInfoInput(BaseModel):
    """Resolve a compound identifier to a metadata bundle."""

    identifier: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="HMDB ID, KEGG ID, InChIKey, SMILES, or compound name.",
    )
    id_type: Literal[
        "auto", "hmdb", "kegg", "inchikey", "smiles", "name"
    ] = Field(
        "auto",
        description=(
            "Hint for parsing. 'auto' (default) detects from format; pass an "
            "explicit value only when the identifier is ambiguous."
        ),
    )


# ---------------------------------------------------------------------------
# Tool 5 — search_literature
# ---------------------------------------------------------------------------


class LiteratureInput(BaseModel):
    """Search PubMed / Europe PMC for paper titles + abstracts."""

    query: str = Field(
        ...,
        min_length=2,
        max_length=300,
        description=(
            "Free-text query, e.g. 'methionine cycle hepatocellular carcinoma'. "
            "Avoid raw IDs; use compound + biology terms."
        ),
    )
    max_results: int = Field(5, ge=1, le=10)
    year_from: int | None = Field(
        None,
        ge=1900,
        le=2100,
        description="Optional lower bound on publication year (inclusive).",
    )


# ---------------------------------------------------------------------------
# Registry mapping
# ---------------------------------------------------------------------------

# (name, schema, short description) — consumed by tool_definitions.py to build
# the OpenAI-style JSON. Wrappers register in dispatcher.py against the same
# names.
SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "query_ramp_enrichment": RampEnrichmentInput,
    "query_pathway_membership": PathwayMembershipInput,
    "query_kegg_path": KeggPathInput,
    "lookup_compound_info": CompoundInfoInput,
    "search_literature": LiteratureInput,
}
