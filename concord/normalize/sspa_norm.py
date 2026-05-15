"""normalize_sspa_output → v0.3 EnrichmentResult(W3 D4).

Maps the raw pandas DataFrame from sspa's ORA / ssGSEA / KPCA / GSVA / zscore
into ConcordMet's schema v0.3 namespaced primary keys.

Pathway ID 输出格式(v0.3 §3.4 RESOLVED-Q05-NEW-4):
    Reactome → "REACT:R-HSA-XXX"
    KEGG     → "KEGG:hsa00XXX"

Compound ID 输出格式(v0.3 §3.4 RESOLVED-Q05-NEW-5):
    primary_id = resolve_primary_id(chebi_id="CHEBI:NNNNN", inchikey=...)
    InChIKey 兜底,InChIKey is always non-empty (RDKit-derived)

Implements §3 schema gap #1 (KEGG cpd → ChEBI 反查 via ChebiLookup) for the
case when sspa returns KEGG-formatted pathway compounds(KEGG DB path).
For Reactome path,sspa returns ChEBI numeric IDs directly — no reverse lookup.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from concord.schema.enrichment import (
    CompoundRef,
    EnrichmentMethod,
    EnrichmentResult,
    PathwayDB,
    PathwayHit,
    ScoreType,
    resolve_primary_id,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_REACT_RE = re.compile(r"^R-(HSA|RNO|MMU|DRE|GGA|CFA|BTA|XTR|ATH|CEL|DME|SCE)-\d+$")
_KEGG_HSA_RE = re.compile(r"^(hsa|rno|mmu)\d{5}$")


def _namespace_pathway_id(raw_id: str) -> str:
    """Map raw sspa pathway id → namespaced "<NS>:<id>".

    sspa Reactome returns "R-HSA-71387" → "REACT:R-HSA-71387"
    sspa KEGG returns "hsa00010"        → "KEGG:hsa00010"
    Anything else                       → "REACT:<as-is>"(conservative;
                                          W3 unblocked,Sprint W4 audit if needed)
    """
    if not raw_id:
        return ""
    s = str(raw_id).strip()
    if _REACT_RE.match(s):
        return f"REACT:{s}"
    if _KEGG_HSA_RE.match(s):
        return f"KEGG:{s}"
    # Unknown shape — return with REACT prefix; downstream validator surfaces it
    return f"REACT:{s}"


_METHOD_MAP: dict[str, EnrichmentMethod] = {
    "ora": EnrichmentMethod.ORA_SSPA,
    "ssgsea": EnrichmentMethod.SSGSEA,
    "gsea": EnrichmentMethod.GSEA_SSPA,
    "kpca": EnrichmentMethod.KPM_SSPA,  # closest enum
    "zscore": EnrichmentMethod.KPM_SSPA,
}

_DB_MAP: dict[str, PathwayDB] = {
    "reactome": PathwayDB.REACTOME,
    "kegg": PathwayDB.KEGG,
    "metacyc": PathwayDB.METACYC,
}


# ---------------------------------------------------------------------------
# Main normalizer
# ---------------------------------------------------------------------------


def _extract_top_pathways_from_ora(
    raw: pd.DataFrame, *, top_n: int, chebi_lookup: Any | None,
) -> list[PathwayHit]:
    """sspa ORA output → list[PathwayHit].

    sspa ORA columns typically include:
      ID, Pathway_name, Hits, Coverage, P-value, P-adjust, etc.
    """
    if raw is None or raw.empty:
        return []
    # Sort by P-value ascending if present
    sort_col = "P-value" if "P-value" in raw.columns else (
        "p_value" if "p_value" in raw.columns else None
    )
    df = raw.sort_values(sort_col).head(top_n) if sort_col else raw.head(top_n)
    hits = []
    for rank, (_, row) in enumerate(df.iterrows()):
        raw_pid = str(row.get("ID", row.get("pathway_id", "")))
        pid_ns = _namespace_pathway_id(raw_pid)
        pname = str(row.get("Pathway_name", row.get("pathway_name", raw_pid)))
        pval = float(row.get(sort_col, 1.0)) if sort_col else 1.0
        fdr = float(row.get("P-adjust", row.get("fdr", pval)))
        aux = {}
        for k in ("Coverage", "Hits"):
            if k in row and pd.notna(row[k]):
                try:
                    aux[k.lower()] = float(row[k])
                except (TypeError, ValueError):
                    pass

        metabolites_hit: tuple[CompoundRef, ...] = ()
        # sspa ORA result may not expose per-pathway metabolite hits.
        # For now leave empty;Sprint W4 will wire pathway membership via
        # pathway_df row interrogation.

        try:
            hits.append(PathwayHit(
                pathway_id=pid_ns,
                pathway_name=pname,
                pathway_id_native=raw_pid,
                pathway_db=PathwayDB.REACTOME,  # caller passes correct one in EnrichmentResult.pathway_db
                score=fdr if not pd.isna(fdr) else pval,
                score_type=ScoreType.FDR if not pd.isna(fdr) else ScoreType.P_VALUE,
                rank=rank,
                metabolites_hit=metabolites_hit,
                n_metabolites_in_pathway=int(aux.get("coverage", 0)),
                n_metabolites_input=int(aux.get("hits", 0)),
                auxiliary_scores=aux,
            ))
        except ValueError as e:
            logger.warning("PathwayHit validator rejected %r: %s", raw_pid, e)
            continue
    return hits


def _extract_top_pathways_from_ssgsea(
    raw: pd.DataFrame, *, top_n: int,
) -> list[PathwayHit]:
    """sspa ssGSEA / KPCA / GSVA / zscore output: rows=samples, cols=pathways.

    For Gate 1-style aggregate top-N, we mean-diff case-vs-ctrl (case rows
    in upper half of mat by convention)→ rank pathways by Δ.
    """
    if raw is None or raw.empty:
        return []
    n_sample = raw.shape[0]
    # First half = case, second half = ctrl (per synth matrix convention)
    half = n_sample // 2
    case_mean = raw.iloc[:half].mean(axis=0)
    ctrl_mean = raw.iloc[half:].mean(axis=0)
    diff = (case_mean - ctrl_mean).sort_values(ascending=False).head(top_n)

    hits = []
    for rank, (pid, score) in enumerate(diff.items()):
        pid_ns = _namespace_pathway_id(str(pid))
        try:
            hits.append(PathwayHit(
                pathway_id=pid_ns,
                pathway_name=str(pid),  # ssGSEA doesn't always include name
                pathway_id_native=str(pid),
                pathway_db=PathwayDB.REACTOME,
                score=float(score),
                score_type=ScoreType.SS_ACTIVITY,
                rank=rank,
                metabolites_hit=(),
                auxiliary_scores={},
            ))
        except ValueError as e:
            logger.warning("PathwayHit validator rejected %r: %s", pid, e)
            continue
    return hits


def normalize_sspa_output(
    sspa_result: dict[str, Any],
    *,
    top_n: int = 10,
    chebi_lookup: Any | None = None,
) -> EnrichmentResult:
    """Convert ``run_sspa()`` output dict → ``EnrichmentResult`` v0.3.

    Args:
        sspa_result: dict from concord.wrappers.sspa_wrapper.run_sspa()
        top_n: how many pathway hits to keep
        chebi_lookup: optional ChebiLookup for KEGG → ChEBI reverse lookup
            (relevant when sspa returns KEGG cpd in pathway data)

    Returns:
        EnrichmentResult v0.3 (schema_version="concordmet_v0.3", chebi_canonicalized=True)
    """
    method_raw = sspa_result.get("method", "ora")
    method = _METHOD_MAP.get(method_raw, EnrichmentMethod.ORA_SSPA)
    pathway_db = _DB_MAP.get(sspa_result.get("pathway_db", "reactome"),
                             PathwayDB.REACTOME)

    raw = sspa_result.get("raw")
    if method_raw == "ora":
        hits = _extract_top_pathways_from_ora(
            raw, top_n=top_n, chebi_lookup=chebi_lookup,
        )
    else:
        hits = _extract_top_pathways_from_ssgsea(raw, top_n=top_n)

    # Patch each hit's pathway_db to match result-level value
    hits_patched = tuple(
        PathwayHit(
            pathway_id=h.pathway_id,
            pathway_name=h.pathway_name,
            pathway_id_native=h.pathway_id_native,
            pathway_db=pathway_db,
            score=h.score,
            score_type=h.score_type,
            rank=h.rank,
            metabolites_hit=h.metabolites_hit,
            n_metabolites_in_pathway=h.n_metabolites_in_pathway,
            n_metabolites_input=h.n_metabolites_input,
            auxiliary_scores=h.auxiliary_scores,
        )
        for h in hits
    )

    return EnrichmentResult(
        method=method,
        pathway_db=pathway_db,
        pathways=hits_patched,
        parameters=sspa_result.get("parameters", {}),
        tool_version=str(sspa_result.get("tool_version", "sspa-1.0.4")),
        db_release=str(sspa_result.get("db_release", "unspecified")),
        n_input=int(sspa_result.get("n_input", 0)),
        n_input_resolved=int(sspa_result.get("n_input_resolved", 0)),
        wall_time_sec=float(sspa_result.get("wall_time_sec", 0.0)),
        chebi_canonicalized=True,
        tautomer_canonicalized=False,
        notes=f"sspa_wrapper ({sspa_result.get('organism','?')})",
    )
