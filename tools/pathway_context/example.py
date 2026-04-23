"""Minimal runnable demo of pathway_context.

Run from the repo root:

    METAGENT_RAMP_PATH=/path/to/ramp.sqlite \\
    python -m tools.pathway_context.example

If METAGENT_RAMP_PATH is unset the script prints the ToolError message
rather than crashing, so you can sanity-check the invocation path even
without a RaMP dump on disk.
"""
from schemas import PathwayContextRequest
from schemas.common import ToolError
from tools.pathway_context import pathway_context


if __name__ == "__main__":
    req = PathwayContextRequest(
        metabolite_id="HMDB0000243",           # pyruvate
        co_observed_ids=["HMDB0000122"],       # glucose — shares glycolysis
        neighbour_depth=1,
        max_pathways=10,
    )
    try:
        resp = pathway_context(req)
    except ToolError as e:
        print(f"pathway_context failed ({e.code}): {e.message}")
    else:
        print(
            f"n_pathways={len(resp.pathways)}  "
            f"neighbours={len(resp.upstream_neighbours)}↑ "
            f"{len(resp.downstream_neighbours)}↓  "
            f"cooccurrence={resp.cooccurrence_score:.2f}"
        )
        for p in resp.pathways[:3]:
            print(f"  [{p.source:12s}] {p.name}  ({p.url})")
        print()
        print(resp.plausibility_summary)
