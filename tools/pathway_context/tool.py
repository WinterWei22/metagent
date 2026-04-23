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
  - `cooccurrence_score ∈ [0, 1]`: fraction of *resolvable* co-observed
    metabolites that share at least one pathway with the focal
    metabolite. IDs that don't resolve in RaMP don't count against the
    denominator — they're tallied separately and surfaced in `explain`
    (finding P-6). When `co_observed_ids` is empty the score is 0.0 —
    absence of evidence, not evidence of implausibility; the
    plausibility_summary string spells that out.
  - `PathwayEntry.hit_count` is PER-pathway: it's the number of queried
    metabolites (focal + co-observed) that sit in that specific pathway,
    not a response-wide aggregate (finding P-1).
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
    resolvable_ids: set[str],
) -> tuple[float, int, int]:
    """Fraction of *resolvable* co-observed IDs that share a pathway with focal.

    Returns `(score, n_resolvable, n_total_unique)`. IDs the user supplied
    that RaMP cannot resolve (unknown HMDB accessions, typos, non-human
    metabolites) are not counted in the denominator, so a sample with 1
    real match and 9 unresolvable IDs scores 1.0, not 0.1 (finding P-6).
    Callers surface `n_total_unique - n_resolvable` in the explain string
    so users know how much input was dropped.

    Returns 0.0 with both counts 0 when the input list is empty.
    """
    if not co_observed_ids:
        return 0.0, 0, 0
    unique = {cid.strip() for cid in co_observed_ids if cid and cid.strip()}
    if not unique:
        return 0.0, 0, 0
    resolvable = unique & resolvable_ids
    if not resolvable:
        return 0.0, 0, len(unique)
    hits = sum(1 for cid in resolvable if cid in cooccurring_ids)
    return hits / len(resolvable), len(resolvable), len(unique)


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

        # Resolve every co-observed ID ONCE so we can (a) compute
        # per-pathway hit_count by checking which analytes actually sit in
        # each pathway, and (b) know which co-obs IDs were resolvable so
        # the cooccurrence_score denominator is honest.
        co_obs_clean = [c.strip() for c in req.co_observed_ids if c and c.strip()]
        co_obs_analytes: list[tuple[str, ramp_backend.Analyte]] = []
        resolvable_ids: set[str] = set()
        for cid in co_obs_clean:
            a = ramp_backend.resolve_analyte(conn, cid)
            if a is not None:
                co_obs_analytes.append((cid, a))
                resolvable_ids.add(cid)

        # Per-pathway membership index: one bounded SQL answers "for each
        # pathway in the result set, which of the queried metabolites
        # (focal + each co-obs) are members?"
        all_queried_ramps: set[str] = set(analyte.ramp_ids)
        for _, a in co_obs_analytes:
            all_queried_ramps.update(a.ramp_ids)
        membership = ramp_backend.pathway_membership(
            conn,
            pathway_ramp_ids=[row.pathway_ramp_id for row in pathway_rows],
            metabolite_ramp_ids=all_queried_ramps,
        )

        focal_ramp_set = set(analyte.ramp_ids)
        pathways: list[PathwayEntry] = []
        for row in pathway_rows:
            present = membership.get(row.pathway_ramp_id, set())
            hit = 1 if focal_ramp_set & present else 0
            for _, a in co_obs_analytes:
                if set(a.ramp_ids) & present:
                    hit += 1
            pathways.append(
                PathwayEntry(
                    id=row.external_id or row.pathway_ramp_id,
                    name=row.name,
                    source=row.source,  # type: ignore[arg-type]
                    hit_count=hit,
                    url=row.url,
                )
            )

        upstream, downstream = ramp_backend.network_neighbours(
            conn, analyte, depth=req.neighbour_depth
        )

        cooccurring = ramp_backend.cooccurring_with_focal(conn, analyte, co_obs_clean)
        score, n_resolvable, n_total_unique = _cooccurrence_score(
            co_obs_clean, cooccurring, resolvable_ids
        )
        n_dropped = n_total_unique - n_resolvable

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
        if n_dropped > 0:
            explain += (
                f" ({n_dropped} of {n_total_unique} co-observed IDs could "
                "not be resolved against RaMP and were excluded from the score.)"
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
