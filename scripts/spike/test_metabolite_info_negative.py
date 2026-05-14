"""§2.6 + §2.7 — fetch_metabolite_info and pathway_context on the
negative-mode fixtures.

These tools should be ion-mode agnostic (they query HMDB / RaMP by
InChIKey or SMILES, not by spectrum). The spike confirms this:

  - same compound query returns same response regardless of polarity
  - the call path doesn't reference ionization_mode at all
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.molecule import MetaboliteInfoRequest  # noqa: E402
from schemas.pathway import PathwayContextRequest  # noqa: E402
from tools.metabolite_info.tool import fetch_metabolite_info  # noqa: E402
from tools.pathway_context.tool import pathway_context  # noqa: E402

CASES = [
    {"label": "citric acid", "inchikey": "KRKNYBCHXYNGOX-UHFFFAOYSA-N", "hmdb": "HMDB0000094"},
    {"label": "glutamyltyrosine", "inchikey": "VVLXCWVSSLFQDS-UHFFFAOYSA-N", "hmdb": "HMDB0011741"},
]


def run_metabolite_info(case: dict) -> dict:
    req = MetaboliteInfoRequest(identifier=case["inchikey"], id_type="inchikey")
    t0 = time.perf_counter()
    try:
        resp = fetch_metabolite_info(req)
    except Exception as e:
        return {"label": case["label"], "crashed": True, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    dt = time.perf_counter() - t0

    return {
        "label": case["label"],
        "crashed": False,
        "wall_seconds": round(dt, 2),
        "found": resp.found,
        "primary_name": resp.primary_name,
        "molecular_formula": resp.molecular_formula,
        "exact_mass": resp.exact_mass,
        "inchikey": resp.inchikey,
        "source": resp.source,
        "n_synonyms": len(resp.synonyms),
        "n_cross_refs": len(resp.cross_refs),
        "cross_refs_keys": sorted(resp.cross_refs.keys()),
        "explain": resp.explain,
    }


def run_pathway_context(case: dict) -> dict:
    req = PathwayContextRequest(
        metabolite_id=case["hmdb"],
        organism="hsa",
        co_observed_ids=[],
        neighbour_depth=1,
        max_pathways=5,
    )
    t0 = time.perf_counter()
    try:
        resp = pathway_context(req)
    except Exception as e:
        return {"label": case["label"], "crashed": True, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    dt = time.perf_counter() - t0

    return {
        "label": case["label"],
        "crashed": False,
        "wall_seconds": round(dt, 2),
        "n_pathways": len(resp.pathways),
        "pathway_names": [p.name for p in resp.pathways[:5]],
        "n_upstream": len(resp.upstream_neighbours),
        "n_downstream": len(resp.downstream_neighbours),
        "cooccurrence_score": resp.cooccurrence_score,
        "explain": resp.explain[:200],
    }


def main() -> None:
    print("§2.6 fetch_metabolite_info on negative-mode targets")
    print("-" * 60)
    for case in CASES:
        print(f"\n--- {case['label']} ---")
        result = run_metabolite_info(case)
        for k, v in result.items():
            print(f"  {k}: {v}")

    print("\n\n§2.7 pathway_context on negative-mode targets")
    print("-" * 60)
    for case in CASES:
        print(f"\n--- {case['label']} ---")
        result = run_pathway_context(case)
        for k, v in result.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
