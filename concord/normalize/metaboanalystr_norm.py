"""normalize_metaboanalystr_output → v0.3 EnrichmentResult (W5 D1).

MetaboAnalystR via docker exec returns JSON with shape:
    {
      "method": "metaboanalystr_psea" | "metaboanalystr_msea" | "metaboanalystr_mummichog",
      "pathways": [
        {"pathway_id": "hsa00010" | "SMP00466",
         "pathway_name": "Glycolysis", "p_value": 1e-5, "fdr": 0.01,
         "total": 20, "expected": 1.2, "hits": 5, "hits_ids": [...]},
        ...
      ],
      "n_resolved": int,
      "tool_version": str,
      "db_release": "kegg" | "smpdb" | ...
    }

Pathway namespace per v0.3 (Q05-NEW-4):
    KEGG pathway (hsa00010)  → KEGG:hsa00010
    SMPDB pathway (SMP00466) → SMPDB:SMP00466
    Other / unknown          → SMPDB:<id> (conservative fallback)
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

_KEGG_RE = re.compile(r"^(hsa|mmu|rno|map)\d{4,5}$")
_SMP_RE = re.compile(r"^SMP\d{5,7}$", re.IGNORECASE)


def _namespace_pathway_id(raw_id: str, library: str) -> tuple[str, str]:
    """Return (namespaced_id, native_id)."""
    s = str(raw_id).strip()
    if not s:
        return ("", "")
    if _KEGG_RE.match(s):
        return f"KEGG:{s}", s
    if _SMP_RE.match(s):
        return f"SMPDB:{s.upper()}", s.upper()
    # library hint fallback
    lib = library.lower() if library else ""
    if lib == "kegg":
        return f"KEGG:{s}", s
    if lib == "smpdb":
        return f"SMPDB:{s}", s
    # Conservative
    return f"SMPDB:{s}", s


_METHOD_MAP = {
    "metaboanalystr_psea": EnrichmentMethod.PSEA_METABOANALYSTR,
    "metaboanalystr_msea": EnrichmentMethod.MSEA_METABOANALYSTR,
    "metaboanalystr_mummichog": EnrichmentMethod.MUMMICHOG,
}


def normalize_metaboanalystr_output(
    result: dict[str, Any],
    *,
    top_n: int = 10,
    chebi_lookup: Any | None = None,
) -> EnrichmentResult:
    """Convert MetaboAnalystR docker output → v0.3 EnrichmentResult.

    Args:
        result: dict from run_metaboanalystr_*() in concord.wrappers
        top_n: how many pathway hits to keep (sorted by p_value)
        chebi_lookup: optional ChebiLookup; if provided, hits_ids → CompoundRef
            via id_resolve
    """
    if chebi_lookup is None:
        try:
            from concord.lookup.chebi import ChebiLookup
            chebi_lookup = ChebiLookup()
        except (FileNotFoundError, ImportError):
            chebi_lookup = None

    method_raw = result.get("method", "metaboanalystr_psea")
    method = _METHOD_MAP.get(method_raw, EnrichmentMethod.PSEA_METABOANALYSTR)
    library = (result.get("parameters", {}) or {}).get("library", "kegg")
    db_enum = PathwayDB.KEGG if library == "kegg" else PathwayDB.SMPDB

    pathways_raw = result.get("raw", []) or []
    # Sort by p_value ascending
    pathways_sorted = sorted(
        pathways_raw,
        key=lambda p: float(p.get("p_value", 1.0) if p.get("p_value") is not None else 1.0),
    )
    top = pathways_sorted[:top_n]

    from concord.reconcile.id_resolve import resolve_ids_to_compound_refs

    id_type_used = (result.get("parameters", {}) or {}).get("id_type", "hmdb").upper()
    src_ns = {"HMDB": "HMDB", "KEGG": "KEGG", "CHEBI": "CHEBI"}.get(id_type_used, "HMDB")

    hits: list[PathwayHit] = []
    for rank, p in enumerate(top):
        raw_id = str(p.get("pathway_id") or "")
        ns_id, native = _namespace_pathway_id(raw_id, library)
        if not ns_id or ns_id.split(":", 1)[0] not in PATHWAY_NAMESPACES:
            logger.warning("Skip metaboanalystr pathway: bad ns %r", ns_id)
            continue
        pval = float(p.get("p_value") or 1.0)
        fdr = p.get("fdr")
        fdr = float(fdr) if (fdr is not None and fdr == fdr) else None  # NaN-safe

        # metabolite hits — if hits_ids provided
        hit_ids = p.get("hits_ids") or []
        if hit_ids:
            resolved, _ = resolve_ids_to_compound_refs(
                hit_ids, source_namespace=src_ns, chebi_lookup=chebi_lookup,
            )
        else:
            resolved = []

        try:
            hits.append(PathwayHit(
                pathway_id=ns_id,
                pathway_name=str(p.get("pathway_name") or raw_id),
                pathway_id_native=native,
                pathway_db=db_enum,
                score=fdr if fdr is not None else pval,
                score_type=ScoreType.FDR if fdr is not None else ScoreType.P_VALUE,
                rank=rank,
                metabolites_hit=tuple(resolved),
                n_metabolites_in_pathway=int(p.get("total") or 0),
                n_metabolites_input=int(p.get("hits") or 0),
                auxiliary_scores={
                    "expected": float(p.get("expected") or 0.0),
                    "p_value_raw": pval,
                },
            ))
        except ValueError as e:
            logger.warning("PathwayHit validator rejected %r: %s", raw_id, e)
            continue

    return EnrichmentResult(
        method=method,
        pathway_db=db_enum,
        pathways=tuple(hits),
        parameters=result.get("parameters", {}),
        tool_version=str(result.get("tool_version", "MetaboAnalystR")),
        db_release=str(result.get("db_release", library)),
        n_input=int(result.get("n_input", 0)),
        n_input_resolved=int(result.get("n_input_resolved", 0)),
        wall_time_sec=float(result.get("wall_time_sec", 0.0)),
        chebi_canonicalized=any(
            r.primary_id.startswith("CHEBI:")
            for h in hits for r in h.metabolites_hit
        ),
        tautomer_canonicalized=False,
        notes=f"metaboanalystr {method_raw} lib={library}",
    )
