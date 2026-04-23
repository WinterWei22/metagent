"""Templated summary strings for pathway_context.

Zero LLM usage. Everything here is an f-string over database-derived
facts. The `plausibility_summary` field on PathwayContextResponse is
capped at 800 chars by the schema and we target ~120 words or fewer so
that the orchestrator can embed it verbatim in the final report without
further truncation.
"""
from __future__ import annotations

from schemas.common import PathwayEntry


# Soft word cap. 120 is the contract limit; we stop growing the string
# around 100 words to leave room for punctuation + rounding.
_MAX_WORDS = 115


def _join_with_and(items: list[str], limit: int = 3) -> str:
    """Natural-language list with a trailing 'and'. Collapses past `limit`."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    visible = items[:limit]
    head = ", ".join(visible[:-1])
    tail = visible[-1]
    suffix = f", and {len(items) - limit} other" + ("s" if len(items) - limit != 1 else "") if len(items) > limit else ""
    return f"{head}, and {tail}{suffix}" if head else f"{tail}{suffix}"


def _truncate_words(text: str, max_words: int = _MAX_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",") + "…"


def render_plausibility_summary(
    *,
    metabolite_name: str,
    pathways: list[PathwayEntry],
    upstream_neighbours: list[str],
    downstream_neighbours: list[str],
    co_observed_ids: list[str],
    cooccurring_ids: list[str],
    cooccurrence_score: float,
) -> str:
    """Write the natural-language plausibility paragraph.

    `metabolite_name` MUST be non-empty — the tool guarantees it by
    falling back to the raw external ID when the DB has no common name.
    The rendered string always contains that name, which lets the
    verifier match the summary against the focal candidate.
    """
    parts: list[str] = []

    # 1. Pathway membership, broken down by source so the reader can see
    #    evidence diversity (KEGG + Reactome vs. a single-source hit).
    if pathways:
        sources = sorted({p.source for p in pathways})
        top_names = _join_with_and([p.name for p in pathways[:3]], limit=3)
        parts.append(
            f"{metabolite_name} is annotated in {len(pathways)} pathway"
            f"{'s' if len(pathways) != 1 else ''} across "
            f"{', '.join(sources)} (e.g. {top_names})."
        )
    else:
        parts.append(
            f"{metabolite_name} has no pathway membership in the integrated RaMP network."
        )

    # 2. Network neighbours — kept terse; the full lists are in the
    #    structured fields of the response.
    neigh_up = len(upstream_neighbours)
    neigh_down = len(downstream_neighbours)
    if neigh_up or neigh_down:
        parts.append(
            f"It has {neigh_up} upstream and {neigh_down} downstream immediate neighbour"
            f"{'s' if (neigh_up + neigh_down) != 1 else ''} in the reaction network."
        )

    # 3. Co-occurrence evidence against the sample context.
    if co_observed_ids:
        matched = len(cooccurring_ids)
        parts.append(
            f"Of {len(co_observed_ids)} co-observed metabolite"
            f"{'s' if len(co_observed_ids) != 1 else ''}, "
            f"{matched} share a pathway with {metabolite_name} "
            f"(plausibility {cooccurrence_score:.2f}/1.00)."
        )
    else:
        parts.append("No co-observed metabolites were supplied, so no co-occurrence evidence was computed.")

    summary = " ".join(parts)
    return _truncate_words(summary)


def render_explain(
    *,
    metabolite_name: str,
    n_pathways: int,
    n_upstream: int,
    n_downstream: int,
    cooccurrence_score: float,
) -> str:
    """One-line explain string for the outer response."""
    return (
        f"Resolved {metabolite_name} to {n_pathways} pathway(s), "
        f"{n_upstream} upstream / {n_downstream} downstream neighbour(s); "
        f"co-occurrence score {cooccurrence_score:.2f}."
    )
