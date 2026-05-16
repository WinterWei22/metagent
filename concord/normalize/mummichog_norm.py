"""normalize_mummichog_output → v0.3 EnrichmentResult.

Mummichog v2.7.0 outputs human_mfn pathway names + comma-separated KEGG cpd
IDs per pathway (hits_kegg_ids). W6 D1.3 normalizer:
  - pathway_id = ``MUMM:<slug>`` — mummichog model.json has 119 human_mfn
    pathway objects with ``id`` like ``mfn1v10path215`` and ``name`` like
    "Vitamin D3 (cholecalciferol) metabolism", but **no KEGG hsa-counterpart
    is recorded in the model**, so no fallback to KEGG: namespace is possible
    at the pathway-id level. Pathway membership *does* live in KEGG cpd
    space — that surface continues to use the KEGG: namespace for
    metabolites_hit (the W4 D2 path).
  - metabolites_hit via ``concord.reconcile.id_resolve(hits_kegg_ids, "KEGG", …)``
  - pathway_db = MUMMICHOG_MFN (faithful to the actual reference DB)
  - pathway_id_native = original human_mfn name (paper-supplementary trace)

Prior wiring (W4 D2) used ``KEGG:<name>`` which inflated the apparent
within-namespace KEGG overlap with PSEA / FELLA. The MUMM dispatch lets
the W6 D3 paradigm analysis classify mummichog as the m/z-direct
paradigm and the 4×4 / 5×5 Jaccard matrix to attribute cross-paradigm
disagreement correctly.
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


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()[:80]


def _namespace_pathway_id(raw_name: str) -> str:
    """human_mfn pathway name → "MUMM:<slug>" (W6 D1.3).

    Mummichog v2.7.0 model.json does not carry KEGG ``hsa00XXX`` cross-
    references for its 119 human_mfn pathways, so we emit the MUMM:
    namespace whitelisted in W6 D1.3 and let the W6 D4 Gate-2 metric
    layer do name-fuzzy-match if KEGG bridging is needed.
    """
    if not raw_name:
        return ""
    return f"MUMM:{_slug(raw_name)}"


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
        pathway_db=PathwayDB.MUMMICHOG_MFN,
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
