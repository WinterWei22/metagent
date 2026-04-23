"""pathway_context — Track D, Tool 6.

Given a metabolite (HMDB or KEGG) and an optional list of co-observed
metabolites, return pathway membership, immediate reaction neighbours,
and a co-occurrence plausibility score. The plausibility_summary string
is templated, NOT LLM-generated.

Contract reminders (docs/TOOL_CONTRACTS.md § Tool 6):
  - `neighbour_depth=0` ⇒ both neighbour lists are empty.
  - A metabolite that resolves but has no pathway rows raises
    MetaboliteNotInNetworkError.
  - A missing / unopenable RaMP DB raises RampUnavailableError.
  - `cooccurrence_score ∈ [0, 1]`: fraction of co-observed metabolites
    that share at least one pathway with the focal metabolite. When
    `co_observed_ids` is empty the score is 0.0 (the schema requires a
    concrete number; an empty sample context is not evidence of
    implausibility, it is absence of evidence — the plausibility_summary
    string is where we explain the distinction).
"""
from __future__ import annotations

import logging

from schemas.common import PathwayEntry
from schemas.pathway import PathwayContextRequest, PathwayContextResponse
from tools.pathway_context import ramp_backend, templates
from tools.pathway_context.errors import (
    MetaboliteNotInNetworkError,
    RampUnavailableError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------


def _cooccurrence_score(
    co_observed_ids: list[str],
    cooccurring_ids: set[str],
) -> float:
    """Fraction of supplied co-observed IDs that share a pathway with focal.

    Returns 0.0 when the input list is empty. Scores are capped at 1.0 by
    construction (numerator ≤ denominator).
    """
    if not co_observed_ids:
        return 0.0
    # De-duplicate the denominator so repeated IDs don't deflate the score.
    unique = {cid.strip() for cid in co_observed_ids if cid and cid.strip()}
    if not unique:
        return 0.0
    hits = sum(1 for cid in unique if cid in cooccurring_ids)
    return hits / len(unique)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def pathway_context(req: PathwayContextRequest) -> PathwayContextResponse:
    """Resolve a metabolite into pathway + neighbour + plausibility context.

    Raises:
        RampUnavailableError: METAGENT_RAMP_PATH is unset or points at a
            missing file.
        MetaboliteNotInNetworkError: the ID resolves but has no pathway
            membership (or does not resolve at all).
    """
    db_path = ramp_backend.resolve_db_path()
    if db_path is None:
        raise RampUnavailableError(
            "RaMP-DB SQLite is not configured. "
            f"Set {ramp_backend.RAMP_ENV_VAR} to the dump path."
        )

    conn = ramp_backend.open_connection(db_path)
    try:
        analyte = ramp_backend.resolve_analyte(conn, req.metabolite_id)
        if analyte is None:
            # Unknown ID is indistinguishable from "known but no pathways"
            # for reporting purposes. We surface the same error so the
            # orchestrator doesn't need to branch.
            raise MetaboliteNotInNetworkError(
                f"No RaMP analyte found for identifier {req.metabolite_id!r}."
            )

        pathway_rows = ramp_backend.pathways_for_analyte(
            conn, analyte, limit=req.max_pathways
        )
        if not pathway_rows:
            raise MetaboliteNotInNetworkError(
                f"Identifier {req.metabolite_id!r} resolves but has "
                f"no pathway membership in RaMP."
            )

        # Build PathwayEntry objects. `hit_count` sums the focal
        # metabolite (always 1) and the number of co-observed IDs present
        # in this pathway.
        co_obs_clean = [c.strip() for c in req.co_observed_ids if c and c.strip()]
        cooccurring = ramp_backend.cooccurring_with_focal(conn, analyte, co_obs_clean)
        pathways: list[PathwayEntry] = []
        for row in pathway_rows:
            # hit_count: focal always counted; co-observed only counted if
            # they co-occur in ANY pathway with focal — this is the
            # whole-response aggregate, not per-pathway, to keep the join
            # cheap. Per-pathway would need a separate query each.
            hit_count = 1 + len(cooccurring)
            pathways.append(
                PathwayEntry(
                    id=row.external_id or row.pathway_ramp_id,
                    name=row.name,
                    source=row.source,  # type: ignore[arg-type]
                    hit_count=hit_count,
                    url=row.url,
                )
            )

        upstream, downstream = ramp_backend.network_neighbours(
            conn, analyte, depth=req.neighbour_depth
        )

        score = _cooccurrence_score(co_obs_clean, cooccurring)

        metabolite_name = analyte.common_name or req.metabolite_id.strip()
        plausibility = templates.render_plausibility_summary(
            metabolite_name=metabolite_name,
            pathways=pathways,
            upstream_neighbours=upstream,
            downstream_neighbours=downstream,
            co_observed_ids=co_obs_clean,
            cooccurring_ids=sorted(cooccurring),
            cooccurrence_score=score,
        )
        explain = templates.render_explain(
            metabolite_name=metabolite_name,
            n_pathways=len(pathways),
            n_upstream=len(upstream),
            n_downstream=len(downstream),
            cooccurrence_score=score,
        )

        return PathwayContextResponse(
            pathways=pathways,
            upstream_neighbours=upstream,
            downstream_neighbours=downstream,
            cooccurrence_score=score,
            plausibility_summary=plausibility,
            explain=explain,
        )
    finally:
        conn.close()
