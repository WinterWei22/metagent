"""Tool 1 — RaMP-DB hypergeometric pathway enrichment for a compound list.

Wraps :func:`tools.benchmark.sub6.ramp_enrichment.compute_enrichment` with
a slim, LLM-friendly projection.
"""
from __future__ import annotations

import logging
from typing import Any

from tools.agent_tools.schemas import (
    RampEnrichmentInput,
    truncate_to_budget,
)
from tools.benchmark.sub6.ramp_enrichment import (
    EnrichmentError,
    compute_enrichment,
)

logger = logging.getLogger(__name__)


def query_ramp_enrichment(payload: dict[str, Any]) -> dict[str, Any]:
    """Run pathway enrichment, return a slim dict.

    Output shape (success):
        {
            "n_input": int,
            "n_resolved": int,
            "unresolved_examples": [str, ...],   # up to 5
            "background_size": int,
            "ramp_snapshot_date": str,
            "top_pathways": [
                {
                    "name": str,
                    "source": str,
                    "external_id": str | None,
                    "fdr": float,
                    "fold_enrichment": float,
                    "matched_compounds": [str, ...],
                    "pathway_size": int,
                },
                ...
            ],
        }
    """
    args = RampEnrichmentInput.model_validate(payload)

    # Strip 'cpd:' prefixes — RaMP source table accepts both forms but the
    # KEGG canonical without prefix matches more reliably across versions.
    cleaned = [
        cid[4:] if cid.lower().startswith("cpd:") else cid
        for cid in args.compound_kegg_ids
    ]

    try:
        report = compute_enrichment(
            cleaned,
            id_type="kegg",
            top_n=args.top_k,
        )
    except EnrichmentError as exc:
        logger.warning("query_ramp_enrichment: EnrichmentError: %s", exc)
        return {
            "error": f"enrichment_error: {exc}",
            "fallback_suggested": (
                "verify the input IDs are valid KEGG compound IDs (e.g. "
                "'C00031'); use lookup_compound_info to confirm a single ID "
                "before retrying"
            ),
        }
    except Exception as exc:  # pragma: no cover — unexpected DB failure
        logger.exception("query_ramp_enrichment: unexpected failure")
        return {
            "error": f"unexpected_error: {type(exc).__name__}: {exc}",
            "fallback_suggested": "retry once; if the error persists, abandon enrichment for this task",
        }

    top_payload: list[dict[str, Any]] = []
    for r in report.top_pathways:
        top_payload.append(
            {
                "name": r.pathway_name,
                "source": r.pathway_source,
                "external_id": r.pathway_external_id,
                "fdr": round(r.fdr, 6),
                "fold_enrichment": round(r.fold_enrichment, 3),
                "matched_compounds": r.matched_compounds,
                "pathway_size": r.total_pathway_compounds,
            }
        )

    out: dict[str, Any] = {
        "n_input": len(report.input_compounds),
        "n_resolved": report.n_input_resolved,
        "unresolved_examples": report.unresolved_compounds[:5],
        "background_size": report.background_size,
        "ramp_snapshot_date": report.ramp_snapshot_date,
        "top_pathways": top_payload,
    }
    return truncate_to_budget(
        out,
        truncatable_key="top_pathways",
        more_hint=(
            "more pathways available; rerun with a smaller top_k to see "
            "compact summaries, or call query_pathway_membership on a "
            "specific pathway you care about"
        ),
    )
