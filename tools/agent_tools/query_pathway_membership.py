"""Tool 2 — Pathway membership and co-occurrence plausibility for one metabolite.

Wraps :func:`tools.pathway_context.tool.pathway_context`.
"""
from __future__ import annotations

import logging
from typing import Any

from schemas.pathway import PathwayContextRequest
from tools.agent_tools.schemas import (
    PathwayMembershipInput,
    truncate_to_budget,
)
from tools.pathway_context import pathway_context
from tools.pathway_context.errors import (
    MetaboliteNotInNetworkError,
    RampUnavailableError,
)

logger = logging.getLogger(__name__)


def query_pathway_membership(payload: dict[str, Any]) -> dict[str, Any]:
    """Look up pathway membership; return slim dict.

    Output shape (success):
        {
            "metabolite_id": str,
            "n_pathways": int,
            "pathways": [
                {"id": str, "name": str, "source": str, "hit_count": int},
                ...
            ],
            "upstream_neighbours": [str, ...],     # capped
            "downstream_neighbours": [str, ...],
            "cooccurrence_score": float,
            "plausibility_summary": str,
        }
    """
    args = PathwayMembershipInput.model_validate(payload)

    try:
        req = PathwayContextRequest(
            metabolite_id=args.metabolite_id,
            co_observed_ids=args.co_observed_ids,
            max_pathways=args.max_pathways,
            neighbour_depth=1,
        )
        resp = pathway_context(req)
    except RampUnavailableError as exc:
        logger.warning("query_pathway_membership: RaMP unavailable: %s", exc)
        return {
            "error": f"ramp_unavailable: {exc}",
            "fallback_suggested": (
                "RaMP-DB not configured in this run; rely on "
                "query_ramp_enrichment output you already have, or skip "
                "membership verification for this claim"
            ),
        }
    except MetaboliteNotInNetworkError as exc:
        return {
            "error": "metabolite_not_in_network",
            "explain": str(exc),
            "fallback_suggested": (
                "this ID either doesn't resolve in RaMP or has no pathway "
                "rows; try lookup_compound_info to confirm the ID is valid, "
                "or use search_literature for biological context"
            ),
        }
    except Exception as exc:  # pragma: no cover
        logger.exception("query_pathway_membership: unexpected failure")
        return {
            "error": f"unexpected_error: {type(exc).__name__}: {exc}",
            "fallback_suggested": "retry once; if it persists, drop the membership claim",
        }

    pathways = [
        {
            "id": p.id,
            "name": p.name,
            "source": p.source,
            "hit_count": p.hit_count,
        }
        for p in resp.pathways
    ]

    out: dict[str, Any] = {
        "metabolite_id": args.metabolite_id,
        "n_pathways": len(pathways),
        "pathways": pathways,
        "upstream_neighbours": resp.upstream_neighbours[:10],
        "downstream_neighbours": resp.downstream_neighbours[:10],
        "cooccurrence_score": round(resp.cooccurrence_score, 3),
        "plausibility_summary": resp.plausibility_summary,
    }
    return truncate_to_budget(
        out,
        truncatable_key="pathways",
        more_hint=(
            "more pathways available; lower max_pathways or filter by source "
            "(e.g. only KEGG) on the next call"
        ),
    )
