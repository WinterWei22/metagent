"""normalize_mummichog_output → v0.3 EnrichmentResult (W4 D2).

Mummichog v2.7.0 outputs human_mfn pathway names + comma-separated KEGG cpd
IDs per pathway (hits_kegg_ids). This normalizer converts to the namespaced
v0.3 schema:
  - pathway_id = "KEGG:" + human_mfn pathway name (using KEGG namespace since
    mummichog's reference network is KEGG-based even though the names are
    human_mfn-style descriptive strings)
  - metabolites_hit via concord.reconcile.id_resolve(hits_kegg_ids, "KEGG", ...)

Note: human_mfn pathway names are not stable KEGG mapIDs. We preserve the
mfn name in ``pathway_id_native`` for paper-supplementary traceability.
"""
from __future__ import annotations

import logging
from typing import Any

from concord.schema.enrichment import (
    EnrichmentMethod,
    EnrichmentResult,
    PathwayDB,
    PathwayHit,
    PATHWAY_NAMESPACES,
    ScoreType,
)

logger = logging.getLogger(__name__)


def _namespace_pathway_id(raw_name: str) -> str:
    """human_mfn pathway name → "KEGG:<name>" (Q05-NEW-4 whitelist requires NS prefix).

    Mummichog v2.7.0 doesn't ship stable KEGG mapIDs; we use the descriptive
    name as the native ID and prefix with KEGG: because the underlying
    reference model is KEGG-based. Sprint W5+ may swap for proper mapIDs.
    """
    if not raw_name:
        return ""
    return f"KEGG:{raw_name.strip()}"


def normalize_mummichog_output(
    mummichog_result: dict[str, Any],
    *,
    top_n: int = 10,
    chebi_lookup: Any | None = None,
) -> EnrichmentResult:
    """Convert ``run_mummichog()`` output dict → ``EnrichmentResult`` v0.3.

    Args:
        mummichog_result: dict from ``concord.wrappers.mummichog_wrapper.run_mummichog``
            with keys: pathways[], empirical_compounds[], stats, errors, parameters
        top_n: how many top pathways to keep (by p-value ASC)
        chebi_lookup: ChebiLookup for KEGG → ChEBI hits_kegg_ids reverse lookup.
            Auto-constructed from default DB path if None.

    Returns:
        EnrichmentResult v0.3 (chebi_canonicalized depends on lookup hit rate)
    """
    if chebi_lookup is None:
        try:
            from concord.lookup.chebi import ChebiLookup
            chebi_lookup = ChebiLookup()
        except (FileNotFoundError, ImportError) as e:
            logger.warning("normalize_mummichog: cannot auto-construct ChebiLookup (%s);"
                           " metabolites_hit will be empty", e)
            chebi_lookup = None

    pathways_raw = mummichog_result.get("pathways", []) or []
    # Sort by p-value ascending
    pathways_sorted = sorted(pathways_raw, key=lambda p: float(p.get("p_value", 1.0)))
    top = pathways_sorted[:top_n]

    from concord.reconcile.id_resolve import resolve_ids_to_compound_refs

    hits: list[PathwayHit] = []
    for rank, p in enumerate(top):
        raw_name = str(p.get("pathway_id") or p.get("pathway_name") or "")
        ns_id = _namespace_pathway_id(raw_name)
        if not ns_id:
            continue
        ns = ns_id.split(":", 1)[0]
        if ns not in PATHWAY_NAMESPACES:
            logger.warning("namespace %r not in whitelist; skipping pathway", ns)
            continue
        pval = float(p.get("p_value", 1.0))
        overlap_size = int(p.get("overlap_size") or 0)
        pathway_size = int(p.get("pathway_size") or 0)
        hits_kegg = list(p.get("hits_kegg_ids") or [])

        resolved, _unresolved = resolve_ids_to_compound_refs(
            hits_kegg, source_namespace="KEGG", chebi_lookup=chebi_lookup,
        )

        try:
            hits.append(PathwayHit(
                pathway_id=ns_id,
                pathway_name=raw_name,
                pathway_id_native=raw_name,
                pathway_db=PathwayDB.KEGG,
                score=pval,
                score_type=ScoreType.P_VALUE,
                rank=rank,
                metabolites_hit=tuple(resolved),
                n_metabolites_in_pathway=pathway_size,
                n_metabolites_input=overlap_size,
                auxiliary_scores={
                    "overlap_size": float(overlap_size),
                    "pathway_size": float(pathway_size),
                },
            ))
        except ValueError as e:
            logger.warning("PathwayHit validator rejected mummichog %r: %s", raw_name, e)
            continue

    stats = mummichog_result.get("stats", {}) or {}
    params = mummichog_result.get("parameters", {}) or {}

    return EnrichmentResult(
        method=EnrichmentMethod.MUMMICHOG,
        pathway_db=PathwayDB.KEGG,
        pathways=tuple(hits),
        parameters=params,
        tool_version=str(mummichog_result.get("tool_version", "mummichog-2.7.0")),
        db_release=f"human_mfn_{params.get('ref_db', 'mfn')}",
        n_input=int(stats.get("n_features_in", 0)),
        n_input_resolved=int(stats.get("n_significant", 0)),
        wall_time_sec=float(mummichog_result.get("wall_time_sec",
                                                 stats.get("wall_time_sec", 0.0))),
        chebi_canonicalized=any(
            r.primary_id.startswith("CHEBI:") for h in hits for r in h.metabolites_hit
        ),
        tautomer_canonicalized=False,
        notes=f"mummichog v2.7.0 + human_mfn; ref_db={params.get('ref_db','mfn')}",
    )
