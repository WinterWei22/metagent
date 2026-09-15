"""normalize_ramp_output → v0.3 EnrichmentResult (W4 D4).

RaMP returns its own ``EnrichmentReport`` with ``top_pathways[i]`` carrying:
  pathway_id (RaMP internal "RAMP_P_NNNNNN"),
  pathway_name (text),
  pathway_source ("reactome"/"kegg"/"wikipathways"/"smpdb"/"hmdb"),
  pathway_external_id ("WP3604"/"SMP00466"/"hsa00010"/"R-HSA-XXX"/null),
  p_value, fdr,
  matched_compounds (list of input IDs).

Mapping to v0.3 namespace-prefixed pathway_id:
  source         → namespace prefix
  ─────────────────────────────────
  reactome       → REACT       (pathway_external_id usually R-HSA-XXX)
  kegg           → KEGG        (pathway_external_id hsa00010 etc.)
  wikipathways   → WP          (pathway_external_id WP3604)
  smpdb          → SMPDB       (pathway_external_id SMP00466)
  hmdb           → SMPDB       (HMDB pathways are SMPDB-derived in RaMP)
  unknown        → SMPDB       (conservative fallback; logged as warning)
"""
from __future__ import annotations

import logging
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


_SOURCE_TO_NS = {
    "reactome":     "REACT",
    "kegg":         "KEGG",
    "wikipathways": "WP",
    "smpdb":        "SMPDB",
    "hmdb":         "SMPDB",
}

_SOURCE_TO_DB_ENUM = {
    "reactome":     PathwayDB.REACTOME,
    "kegg":         PathwayDB.KEGG,
    "wikipathways": PathwayDB.WIKIPATHWAYS,
    "smpdb":        PathwayDB.SMPDB,
    "hmdb":         PathwayDB.HMDB,
}


def _namespace_pathway_id(pathway_source: str, ext_id: str | None,
                         ramp_pid: str) -> tuple[str, str]:
    """Return (namespaced_id, native_id_to_store).

    Falls back to "SMPDB:<RAMP_P_xxx>" when source unknown or ext_id missing."""
    src = (pathway_source or "").lower()
    ns = _SOURCE_TO_NS.get(src, "SMPDB")
    if ns not in PATHWAY_NAMESPACES:
        logger.warning("RaMP pathway source %r → ns %r not in whitelist", src, ns)
        ns = "SMPDB"

    native = ext_id or ramp_pid
    if ext_id:
        return f"{ns}:{ext_id}", ext_id
    # No external ID — use RaMP internal as namespaced ID
    return f"{ns}:{ramp_pid}", ramp_pid


def normalize_ramp_output(
    ramp_result: dict[str, Any],
    *,
    top_n: int = 10,
    chebi_lookup: Any | None = None,
) -> EnrichmentResult:
    """Convert run_ramp_enrichment() output dict → v0.3 EnrichmentResult.

    matched_compounds in each pathway are routed through id_resolve to populate
    metabolites_hit. id_type_used dictates source_namespace ("HMDB" or "INCHIKEY"
    or "KEGG").
    """
    if chebi_lookup is None:
        try:
            from concord.lookup.chebi import ChebiLookup
            chebi_lookup = ChebiLookup()
        except (FileNotFoundError, ImportError):
            chebi_lookup = None

    report = ramp_result.get("report")
    if report is None or not getattr(report, "top_pathways", None):
        # Empty input or empty output → return empty EnrichmentResult (validator-ok)
        return EnrichmentResult(
            method=EnrichmentMethod.ORA_RAMP,
            pathway_db=PathwayDB.MERGED,
            pathways=(),
            parameters=ramp_result.get("parameters", {}),
            tool_version=str(ramp_result.get("tool_version", "ramp-enrichment-internal")),
            db_release=str(ramp_result.get("db_release", "unknown")),
            n_input=int(ramp_result.get("n_input", 0)),
            n_input_resolved=int(ramp_result.get("n_input_resolved", 0)),
            wall_time_sec=float(ramp_result.get("wall_time_sec", 0.0)),
            chebi_canonicalized=False,
            tautomer_canonicalized=False,
            notes="ramp_wrapper:empty",
        )

    from concord.reconcile.id_resolve import resolve_ids_to_compound_refs

    id_type_used = (ramp_result.get("id_type_used") or "hmdb").upper()
    # Normalize: id_type_used to source_namespace whitelist
    src_ns = {"HMDB": "HMDB", "KEGG": "KEGG", "INCHIKEY": "INCHIKEY",
              "CHEBI": "CHEBI"}.get(id_type_used, "HMDB")

    hits: list[PathwayHit] = []
    for rank, p in enumerate(report.top_pathways[:top_n]):
        ns_id, native = _namespace_pathway_id(
            p.pathway_source, p.pathway_external_id, p.pathway_id,
        )
        ns = ns_id.split(":", 1)[0]
        if ns not in PATHWAY_NAMESPACES:
            logger.warning("Skipping RaMP pathway %r — namespace %r illegal",
                           p.pathway_id, ns)
            continue

        # Resolve matched_compounds via id_resolve
        matched = list(getattr(p, "matched_compounds", []) or [])
        resolved, _unres = resolve_ids_to_compound_refs(
            matched, source_namespace=src_ns, chebi_lookup=chebi_lookup,
        )

        try:
            hits.append(PathwayHit(
                pathway_id=ns_id,
                pathway_name=p.pathway_name,
                pathway_id_native=native,
                pathway_db=_SOURCE_TO_DB_ENUM.get(
                    p.pathway_source.lower(), PathwayDB.MERGED
                ),
                score=float(p.fdr) if p.fdr is not None else float(p.p_value),
                score_type=ScoreType.FDR if p.fdr is not None else ScoreType.P_VALUE,
                rank=rank,
                metabolites_hit=tuple(resolved),
                n_metabolites_in_pathway=int(p.total_pathway_compounds),
                n_metabolites_input=len(matched),
                auxiliary_scores={
                    "fold_enrichment": float(p.fold_enrichment),
                    "p_value_raw": float(p.p_value),
                },
            ))
        except ValueError as e:
            logger.warning("PathwayHit validator rejected RaMP %r: %s",
                           p.pathway_id, e)
            continue

    return EnrichmentResult(
        method=EnrichmentMethod.ORA_RAMP,
        pathway_db=PathwayDB.MERGED,   # RaMP merges several sources
        pathways=tuple(hits),
        parameters=ramp_result.get("parameters", {}),
        tool_version=str(ramp_result.get("tool_version", "ramp-enrichment-internal")),
        db_release=str(ramp_result.get("db_release", "unknown")),
        n_input=int(ramp_result.get("n_input", 0)),
        n_input_resolved=int(ramp_result.get("n_input_resolved", 0)),
        wall_time_sec=float(ramp_result.get("wall_time_sec", 0.0)),
        chebi_canonicalized=any(
            r.primary_id.startswith("CHEBI:") for h in hits for r in h.metabolites_hit
        ),
        tautomer_canonicalized=False,
        notes=f"ramp_wrapper id_type={id_type_used}",
    )
