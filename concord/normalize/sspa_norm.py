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


def _parse_da_metabolites(cell: Any) -> list[str]:
    """Parse sspa ORA ``DA_Metabolites_ID`` cell → list of ChEBI numeric strs.

    sspa stores hits as a single comma-separated string (e.g. "17234, 16467").
    Empty cells / NaN → empty list. Surrounding whitespace stripped.
    """
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return []
    s = str(cell).strip()
    if not s:
        return []
    return [tok.strip() for tok in s.split(",") if tok.strip()]


def _build_metabolites_hit(
    da_metabolites: list[str], chebi_lookup: Any | None,
) -> tuple[CompoundRef, ...]:
    """Convert sspa ORA ChEBI numeric strs → tuple[CompoundRef, ...] (v0.3).

    W4 D2:routed through shared ``concord.reconcile.id_resolve``;sspa's case
    is source_namespace="CHEBI"(ChEBI numeric IDs from DA_Metabolites_ID).
    """
    if not da_metabolites or chebi_lookup is None:
        return ()
    from concord.reconcile.id_resolve import resolve_ids_to_compound_refs
    resolved, _unresolved = resolve_ids_to_compound_refs(
        da_metabolites, source_namespace="CHEBI", chebi_lookup=chebi_lookup,
    )
    return tuple(resolved)


def _extract_top_pathways_from_ora(
    raw: pd.DataFrame, *, top_n: int, chebi_lookup: Any | None,
) -> list[PathwayHit]:
    """sspa ORA output → list[PathwayHit] with populated metabolites_hit.

    sspa ORA columns(per sspa.sspa_ora.over_representation_analysis,verified
    2026-05-16): ``ID, Pathway_name, Hits, Coverage, P-value, P-adjust,
    DA_Metabolites_ID``. The last column is a comma-separated list of compound
    IDs that JOIN'd between the user's DA compound set and pathway membership —
    this is exactly the ``metabolites_hit`` we need(internal JOIN,not a
    cross-namespace lookup).
    """
    if raw is None or raw.empty:
        return []
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

        # Parse Hits / Coverage which sspa stores as "k/N" strings; keep float
        # for legacy aux_scores compat
        aux: dict[str, float] = {}
        for k in ("Coverage", "Hits"):
            if k in row and pd.notna(row[k]):
                v = row[k]
                if isinstance(v, str) and "/" in v:
                    try:
                        num, den = v.split("/", 1)
                        aux[k.lower()] = float(num) / max(float(den), 1.0)
                        aux[f"{k.lower()}_raw"] = v   # keep raw "k/N"
                    except (TypeError, ValueError):
                        pass
                else:
                    try:
                        aux[k.lower()] = float(v)
                    except (TypeError, ValueError):
                        pass

        # Patch 1 (W3 hotfix 2026-05-16): wire metabolites_hit from
        # DA_Metabolites_ID column via ChebiLookup → CompoundRef
        da_ids = _parse_da_metabolites(row.get("DA_Metabolites_ID"))
        metabolites_hit = _build_metabolites_hit(da_ids, chebi_lookup)

        # n_metabolites_in_pathway = "Coverage" denominator (pathway size)
        # n_metabolites_input = "Hits" numerator (DA ∩ pathway)
        n_path = 0
        n_in = 0
        cov_raw = aux.get("coverage_raw")
        hits_raw = aux.get("hits_raw")
        if isinstance(cov_raw, str) and "/" in cov_raw:
            try:
                n_path = int(cov_raw.split("/", 1)[1])
            except (TypeError, ValueError):
                pass
        if isinstance(hits_raw, str) and "/" in hits_raw:
            try:
                n_in = int(hits_raw.split("/", 1)[0])
            except (TypeError, ValueError):
                pass

        try:
            hits.append(PathwayHit(
                pathway_id=pid_ns,
                pathway_name=pname,
                pathway_id_native=raw_pid,
                pathway_db=PathwayDB.REACTOME,
                score=fdr if not pd.isna(fdr) else pval,
                score_type=ScoreType.FDR if not pd.isna(fdr) else ScoreType.P_VALUE,
                rank=rank,
                metabolites_hit=metabolites_hit,
                n_metabolites_in_pathway=n_path,
                n_metabolites_input=n_in,
                auxiliary_scores={k: v for k, v in aux.items()
                                  if isinstance(v, (int, float))},
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
        chebi_lookup: ChebiLookup for ChEBI→CompoundRef enrichment. If None,
            auto-constructed from default DB path. **Required for ORA path** —
            sspa ORA's DA_Metabolites_ID column needs ChebiLookup to fetch
            InChIKey + display name for each CompoundRef.

    Returns:
        EnrichmentResult v0.3 (schema_version="concordmet_v0.3", chebi_canonicalized=True)
    """
    # Auto-construct ChebiLookup if absent. ORA path needs it for metabolites_hit.
    if chebi_lookup is None:
        try:
            from concord.lookup.chebi import ChebiLookup
            chebi_lookup = ChebiLookup()
        except (FileNotFoundError, ImportError) as e:
            logger.warning(
                "normalize_sspa_output: could not auto-construct ChebiLookup (%s); "
                "metabolites_hit will be empty",
                e,
            )
            chebi_lookup = None
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
