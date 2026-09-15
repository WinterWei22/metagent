"""normalize_fella_output → v0.3 EnrichmentResult (W5 D2).

FELLA via docker exec returns JSON:
    {
      "method": "fella_rwr" | "fella_diffusion",
      "pathways": [
        {"pathway_id": "hsa00010", "pathway_name": "Glycolysis",
         "p_value": 0.01, "hits_kegg_ids": ["C00031", ...]},
        ...
      ],
      "n_resolved": int,
      "tool_version": str,
      "db_release": "kegg_hsa_via_FELLA"
    }

Pathway namespace: KEGG:hsa00XXX (FELLA always operates on KEGG).
metabolites_hit: KEGG cpd hits → ChEBI via id_resolve.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from concord.schema.enrichment import (
    EnrichmentMethod,
    EnrichmentResult,
    PATHWAY_NAMESPACES,
    PathwayDB,
    PathwayHit,
    ScoreType,
)

logger = logging.getLogger(__name__)

_KEGG_PATH_RE = re.compile(r"^(hsa|mmu|rno|map)\d{4,5}$")


def _namespace_pathway_id(raw_id: str) -> tuple[str, str]:
    s = str(raw_id).strip()
    if not s:
        return "", ""
    if _KEGG_PATH_RE.match(s):
        return f"KEGG:{s}", s
    # FELLA may return "path:hsa00010" or "hsa00010" — strip prefix
    if s.startswith("path:"):
        rest = s[5:]
        if _KEGG_PATH_RE.match(rest):
            return f"KEGG:{rest}", rest
    # Conservative fallback
    return f"KEGG:{s}", s


_METHOD_MAP = {
    "fella_rwr": EnrichmentMethod.FELLA_RWR,
    "fella_diffusion": EnrichmentMethod.FELLA_DIFFUSION,
}


def normalize_fella_output(
    result: dict[str, Any],
    *,
    top_n: int = 10,
    chebi_lookup: Any | None = None,
) -> EnrichmentResult:
    """Convert FELLA docker output → v0.3 EnrichmentResult."""
    if chebi_lookup is None:
        try:
            from concord.lookup.chebi import ChebiLookup
            chebi_lookup = ChebiLookup()
        except (FileNotFoundError, ImportError):
            chebi_lookup = None

    method_raw = result.get("method", "fella_rwr")
    method = _METHOD_MAP.get(method_raw, EnrichmentMethod.FELLA_RWR)

    pathways_raw = result.get("raw", []) or []
    # FELLA score is RWR / diffusion activity (higher = more relevant);
    # may also include p.score. Sort by p_value ascending (smaller = more sig).
    pathways_sorted = sorted(
        pathways_raw,
        key=lambda p: float(p.get("p_value", 1.0) if p.get("p_value") is not None else 1.0),
    )
    top = pathways_sorted[:top_n]

    from concord.reconcile.id_resolve import resolve_ids_to_compound_refs

    hits: list[PathwayHit] = []
    for rank, p in enumerate(top):
        raw_id = str(p.get("pathway_id") or "")
        ns_id, native = _namespace_pathway_id(raw_id)
        if not ns_id or ns_id.split(":", 1)[0] not in PATHWAY_NAMESPACES:
            logger.warning("Skip FELLA pathway: bad ns %r", ns_id)
            continue
        pval = float(p.get("p_value") or 1.0)
        score_type = (
            ScoreType.RWR_SCORE if method == EnrichmentMethod.FELLA_RWR
            else ScoreType.DIFFUSION_SCORE
        )

        hit_kegg = list(p.get("hits_kegg_ids") or [])
        resolved, _unres = resolve_ids_to_compound_refs(
            hit_kegg, source_namespace="KEGG", chebi_lookup=chebi_lookup,
        )

        try:
            hits.append(PathwayHit(
                pathway_id=ns_id,
                pathway_name=str(p.get("pathway_name") or raw_id),
                pathway_id_native=native,
                pathway_db=PathwayDB.KEGG,
                score=pval,
                score_type=score_type,
                rank=rank,
                metabolites_hit=tuple(resolved),
                n_metabolites_in_pathway=int(p.get("pathway_size") or 0),
                n_metabolites_input=len(hit_kegg),
                auxiliary_scores={},
            ))
        except ValueError as e:
            logger.warning("PathwayHit validator rejected %r: %s", raw_id, e)

    return EnrichmentResult(
        method=method,
        pathway_db=PathwayDB.KEGG,
        pathways=tuple(hits),
        parameters=result.get("parameters", {}),
        tool_version=str(result.get("tool_version", "FELLA")),
        db_release=str(result.get("db_release", "kegg_hsa")),
        n_input=int(result.get("n_input", 0)),
        n_input_resolved=int(result.get("n_input_resolved", 0)),
        wall_time_sec=float(result.get("wall_time_sec", 0.0)),
        chebi_canonicalized=any(
            r.primary_id.startswith("CHEBI:")
            for h in hits for r in h.metabolites_hit
        ),
        tautomer_canonicalized=False,
        notes=f"fella {method_raw}",
    )
