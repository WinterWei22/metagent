"""RaMP wrapper — wraps existing T1 ``tools.benchmark.sub6.ramp_enrichment``
into the v0.3 EnrichmentResult interface (W4 D4).

Does NOT modify the existing tool (lives outside concord/). This is purely a
ConcordMet-side adapter that takes CompoundRef list and returns v0.3 schema.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Default RaMP sqlite path (Session 3 verified) — caller can override via env.
_DEFAULT_RAMP_DB = "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite"


def _extract_hmdb_ids(compound_refs: list[Any]) -> list[str]:
    """Pull HMDB IDs (without 'HMDB:' prefix) from CompoundRef list."""
    out: list[str] = []
    seen: set[str] = set()
    for ref in compound_refs:
        if ref is None:
            continue
        hmdb = getattr(ref, "hmdb_id", None)
        if not hmdb:
            continue
        s = hmdb.replace("HMDB:", "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _extract_inchikeys(compound_refs: list[Any]) -> list[str]:
    """Pull InChIKey full strings from CompoundRef list (fallback when no HMDB)."""
    out: list[str] = []
    seen: set[str] = set()
    for ref in compound_refs:
        ik = getattr(ref, "inchikey", "") or ""
        if ik and ik not in seen:
            seen.add(ik)
            out.append(ik)
    return out


def run_ramp_enrichment(
    compound_refs: list[Any],
    *,
    top_n: int = 10,
    fdr_threshold: float = 0.05,
    ramp_db_path: str | None = None,
    id_type: Literal["auto", "hmdb", "inchikey", "kegg"] = "auto",
    pathway_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Run RaMP hypergeometric ORA. Returns dict ready for normalize_ramp_output.

    Args:
        compound_refs: list of v0.3 CompoundRef
        top_n: limit
        fdr_threshold: BH-adjusted threshold (passed through to compute_enrichment)
        ramp_db_path: explicit RaMP sqlite path. If None, env $RAMP_DB_PATH or
            default Session-3-verified path.
        id_type: "auto" picks the first available ID source (hmdb > inchikey > kegg).

    Returns:
        dict with keys: report (EnrichmentReport from compute_enrichment),
        wall_time_sec, n_input, n_input_resolved, parameters, tool_version,
        db_release, id_type_used
    """
    if ramp_db_path is None:
        ramp_db_path = os.environ.get("RAMP_DB_PATH") or _DEFAULT_RAMP_DB
    os.environ.setdefault("RAMP_DB_PATH", ramp_db_path)

    # Pick id_type
    chosen_ids: list[str] = []
    chosen_type: str = id_type
    if id_type == "auto":
        chosen_ids = _extract_hmdb_ids(compound_refs)
        chosen_type = "hmdb"
        if not chosen_ids:
            chosen_ids = _extract_inchikeys(compound_refs)
            chosen_type = "inchikey"
    elif id_type == "hmdb":
        chosen_ids = _extract_hmdb_ids(compound_refs)
    elif id_type == "inchikey":
        chosen_ids = _extract_inchikeys(compound_refs)
    elif id_type == "kegg":
        chosen_ids = []
        seen = set()
        for ref in compound_refs:
            k = getattr(ref, "kegg_compound_id", None)
            if k:
                k = k.replace("KEGG:", "").strip()
                if k and k not in seen:
                    seen.add(k); chosen_ids.append(k)

    if not chosen_ids:
        return {
            "report": None,
            "wall_time_sec": 0.0,
            "n_input": 0,
            "n_input_resolved": 0,
            "parameters": {
                "top_n": top_n, "fdr_threshold": fdr_threshold,
                "id_type_requested": id_type,
                "id_type_used": chosen_type,
            },
            "tool_version": "ramp-enrichment-internal",
            "db_release": "unknown",
            "id_type_used": chosen_type,
        }

    from tools.benchmark.sub6.ramp_enrichment import (
        _sources_to_excluded_types,
        compute_enrichment,
    )

    # Optional INCLUDE-semantics source filter (LLM-driven): e.g. ["kegg"] →
    # canonical KEGG metabolic pathways only. None → default multi-DB behaviour
    # (byte-identical to pre-2026-07-03; guardrail: old benchmark unaffected).
    extra: dict[str, Any] = {}
    if pathway_sources:
        extra["excluded_pathway_types"] = _sources_to_excluded_types(pathway_sources)

    t0 = time.time()
    report = compute_enrichment(
        chosen_ids, id_type=chosen_type, top_n=top_n,
        fdr_threshold=fdr_threshold, ramp_db_path=ramp_db_path, **extra,
    )
    return {
        "report": report,
        "wall_time_sec": time.time() - t0,
        "n_input": len(chosen_ids),
        "n_input_resolved": int(report.n_input_resolved),
        "parameters": {
            "top_n": top_n, "fdr_threshold": fdr_threshold,
            "id_type_used": chosen_type,
        },
        "tool_version": "ramp-enrichment-internal",
        "db_release": f"ramp_{report.ramp_snapshot_date}",
        "id_type_used": chosen_type,
    }
