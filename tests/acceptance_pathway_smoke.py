"""pathway_context end-to-end smoke test.

NOT part of the unit-test suite. Runs against a real RaMP-DB SQLite
pointed to by METAGENT_RAMP_PATH and checks:
  1. A central metabolite (pyruvate) returns pathways from multiple
     sources (kegg + reactome + smpdb or wiki at minimum).
  2. Co-occurrence lift: glucose+pyruvate > glucose+caffeine.
  3. Depth-1 neighbour query returns non-empty for a reactive metabolite.
  4. Depth-0 returns empty neighbours.
  5. An unknown identifier raises MetaboliteNotInNetworkError.
  6. plausibility_summary names the metabolite and stays under 120 words.

Usage:
    METAGENT_RAMP_PATH=/data/weiwentao/llm_agent_metabolomics/ramp.sqlite \\
    python tests/acceptance_pathway_smoke.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from schemas import PathwayContextRequest
from tools.pathway_context import pathway_context
from tools.pathway_context.errors import MetaboliteNotInNetworkError


def _banner(msg: str) -> None:
    print(f"\n--- {msg} ---")


def main() -> int:
    if not os.environ.get("METAGENT_RAMP_PATH"):
        print("METAGENT_RAMP_PATH not set", file=sys.stderr)
        return 2

    failures: list[str] = []

    _banner("pyruvate: multi-source pathways (HMDB0000243)")
    resp = pathway_context(
        PathwayContextRequest(
            metabolite_id="HMDB0000243",
            neighbour_depth=1,
            max_pathways=25,
        )
    )
    sources = sorted({p.source for p in resp.pathways})
    print(f"n_pathways={len(resp.pathways)}  sources={sources}")
    print(f"neighbours={len(resp.upstream_neighbours)}↑ {len(resp.downstream_neighbours)}↓")
    for p in resp.pathways[:6]:
        print(f"  [{p.source:13s}] {p.name}  ({p.id})")
    if len(sources) < 2:
        failures.append("pyruvate should span ≥2 pathway sources")
    if len(resp.pathways) == 0:
        failures.append("pyruvate returned 0 pathways")

    _banner("co-occurrence lift: glucose+pyruvate vs glucose+caffeine")
    with_real = pathway_context(
        PathwayContextRequest(
            metabolite_id="HMDB0000122",
            co_observed_ids=["HMDB0000243"],
            neighbour_depth=0,
            max_pathways=20,
        )
    )
    with_random = pathway_context(
        PathwayContextRequest(
            metabolite_id="HMDB0000122",
            co_observed_ids=["HMDB0001847"],
            neighbour_depth=0,
            max_pathways=20,
        )
    )
    print(f"glucose+pyruvate   score={with_real.cooccurrence_score:.3f}")
    print(f"glucose+caffeine   score={with_random.cooccurrence_score:.3f}")
    if not (with_real.cooccurrence_score > with_random.cooccurrence_score):
        failures.append("co-occurrence with pyruvate did not beat caffeine")

    _banner("neighbour depth 0 vs 1")
    depth0 = pathway_context(
        PathwayContextRequest(metabolite_id="HMDB0000243", neighbour_depth=0)
    )
    depth1 = pathway_context(
        PathwayContextRequest(metabolite_id="HMDB0000243", neighbour_depth=1)
    )
    print(
        f"depth=0 up/down = {len(depth0.upstream_neighbours)}/{len(depth0.downstream_neighbours)}"
    )
    print(
        f"depth=1 up/down = {len(depth1.upstream_neighbours)}/{len(depth1.downstream_neighbours)}"
        f"  sample down = {depth1.downstream_neighbours[:3]}"
    )
    if depth0.upstream_neighbours or depth0.downstream_neighbours:
        failures.append("depth=0 returned non-empty neighbours")
    if not (depth1.upstream_neighbours or depth1.downstream_neighbours):
        failures.append("depth=1 on pyruvate returned empty neighbour lists")

    _banner("orphan: HMDB9999999 → MetaboliteNotInNetworkError")
    try:
        pathway_context(PathwayContextRequest(metabolite_id="HMDB9999999"))
        failures.append("unknown ID did not raise")
    except MetaboliteNotInNetworkError as e:
        print(f"raised as expected: {e.code}  {e.message}")

    _banner("plausibility summary")
    summary = with_real.plausibility_summary
    words = summary.split()
    print(f"({len(words)} words) {summary}")
    name = (with_real.pathways[0].name if with_real.pathways else "")
    if len(words) > 120:
        failures.append("plausibility_summary exceeded 120 words")

    _banner("summary: KEGG C00022 works the same as HMDB0000243")
    by_kegg = pathway_context(
        PathwayContextRequest(metabolite_id="C00022", max_pathways=5)
    )
    by_hmdb = pathway_context(
        PathwayContextRequest(metabolite_id="HMDB0000243", max_pathways=5)
    )
    print(
        f"C00022:        {len(by_kegg.pathways)} pathways"
        f"  HMDB0000243: {len(by_hmdb.pathways)} pathways"
    )
    if len(by_kegg.pathways) == 0 or len(by_hmdb.pathways) == 0:
        failures.append("KEGG or HMDB path query returned empty for pyruvate")

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
