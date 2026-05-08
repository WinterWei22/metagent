"""Tool 4 — Resolve a compound identifier to structured metadata.

Wraps :func:`tools.metabolite_info.tool.fetch_metabolite_info`.
"""
from __future__ import annotations

import logging
from typing import Any

from schemas.molecule import MetaboliteInfoRequest
from tools.agent_tools.schemas import CompoundInfoInput, truncate_to_budget
from tools.metabolite_info import fetch_metabolite_info

logger = logging.getLogger(__name__)


def lookup_compound_info(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve identifier; return slim metadata bundle.

    Output shape (found):
        {
            "found": True,
            "primary_name": str,
            "synonyms": [str, ...],            # up to 8
            "molecular_formula": str | None,
            "exact_mass": float | None,
            "smiles": str | None,
            "inchikey": str | None,
            "chemical_class": str | None,
            "tissue_locations": [str, ...],    # up to 8
            "disease_associations": [str, ...],
            "cross_refs": dict,
            "source": str,
        }

    Output shape (not found):
        {"found": False, "explain": str}
    """
    args = CompoundInfoInput.model_validate(payload)

    try:
        req = MetaboliteInfoRequest(
            identifier=args.identifier,
            id_type=args.id_type,
        )
        resp = fetch_metabolite_info(req)
    except Exception as exc:  # IdentifierFormatError, etc.
        return {
            "error": f"identifier_format_error: {exc}",
            "fallback_suggested": (
                "the identifier could not be parsed; check formatting "
                "(KEGG: 'C00031', HMDB: 'HMDB0000122', InChIKey: 27 chars)"
            ),
        }

    if not resp.found:
        return {
            "found": False,
            "explain": resp.explain,
            "fallback_suggested": (
                "no entry across HMDB/MoNA/PubChem; try search_literature "
                "with the bare name if you need biological context"
            ),
        }

    out: dict[str, Any] = {
        "found": True,
        "primary_name": resp.primary_name,
        "synonyms": resp.synonyms[:8],
        "molecular_formula": resp.molecular_formula,
        "exact_mass": resp.exact_mass,
        "smiles": resp.smiles,
        "inchikey": resp.inchikey,
        "chemical_class": resp.chemical_class,
        "tissue_locations": resp.tissue_locations[:8],
        "disease_associations": resp.disease_associations[:8],
        "cross_refs": dict(resp.cross_refs),
        "source": resp.source,
    }
    # Disease associations are the most likely to bloat — truncate them first.
    return truncate_to_budget(
        out,
        truncatable_key="disease_associations",
        more_hint="more disease associations and synonyms available in source DB",
    )
