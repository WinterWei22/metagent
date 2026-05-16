"""W5 D2: FELLA RWR + Diffusion real-task smoke.

Tests both fella_rwr (pagerank-based) and fella_diffusion methods
against one Gate-1 panel task. Sanity bar (same as D1下):
  - pathway_ids namespace-prefixed (KEGG:)
  - wall_time per call < 30s
  - metabolites_hit non-empty
  - chebi_canonicalized ≥ 30%
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup
from concord.reconcile.id_resolve import resolve_ids_to_compound_refs
from concord.schema.enrichment import PATHWAY_NAMESPACES
from concord.wrappers.fella_wrapper import run_fella_rwr, run_fella_diffusion
from concord.normalize.fella_norm import normalize_fella_output

BENCHMARK = WORKTREE / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks_v3.jsonl"


def _run_one(name: str, fn, refs, chebi) -> tuple[float, bool]:
    print(f"\n=== {name} ===")
    t0 = time.time()
    raw = fn(refs, organism="hsa", timeout=120)
    wall = time.time() - t0
    print(f"wall_time_sec: {wall:.2f}")
    print(f"raw keys: {list(raw.keys())}")
    print(f"raw['method']: {raw.get('method')}")
    print(f"raw['n_input']: {raw.get('n_input')}")
    print(f"raw['n_input_resolved']: {raw.get('n_input_resolved')}")
    pathways_raw = raw.get("raw", [])
    print(f"raw['raw'] (pathway rows): {len(pathways_raw)}")
    if pathways_raw:
        print(f"  sample[0]: {pathways_raw[0]}")
    if raw.get("error"):
        print(f"ERROR: {raw['error']}", file=sys.stderr)
        return wall, False

    er = normalize_fella_output(raw, top_n=10, chebi_lookup=chebi)
    print(f"  schema_version: {er.schema_version}")
    print(f"  n pathways: {len(er.pathways)}")
    print(f"  chebi_canonicalized: {er.chebi_canonicalized}")
    for h in er.pathways[:3]:
        print(f"  {h.pathway_id} ({h.pathway_name[:25]}) "
              f"score={h.score:.4g} mhit={len(h.metabolites_hit)}")

    # Sanity
    fails = []
    bad_ns = [h.pathway_id for h in er.pathways
              if h.pathway_id.split(":", 1)[0] not in PATHWAY_NAMESPACES]
    if bad_ns:
        fails.append(f"bad ns: {bad_ns[:3]}")
    if wall > 30:
        fails.append(f"wall {wall:.2f}s > 30s")
    total_hits = sum(len(h.metabolites_hit) for h in er.pathways)
    if er.pathways and total_hits == 0:
        fails.append("vacuous: 0 metabolites_hit")
    if er.pathways:
        n_chebi = sum(1 for h in er.pathways for r in h.metabolites_hit
                      if r.primary_id.startswith("CHEBI:"))
        pct = n_chebi / max(total_hits, 1) * 100
        if pct < 30:
            fails.append(f"CHEBI {pct:.1f}% < 30%")
        else:
            print(f"  CHEBI primary: {n_chebi}/{total_hits} = {pct:.1f}%")

    if fails:
        print("  SANITY FAILS:", fails)
        return wall, False
    print("  sanity: PASS")
    return wall, True


def main() -> int:
    tasks = [json.loads(line) for line in BENCHMARK.read_text().splitlines()]
    task = next(t for t in tasks if "RAMP_P_000052855" not in t["task_id"])
    print(f"task: {task['task_id']}")
    hmdb_ids = [m["hmdb_id"] for m in task["differential_metabolites"]
                if m.get("hmdb_id")]
    chebi = ChebiLookup()
    refs, _ = resolve_ids_to_compound_refs(
        hmdb_ids, source_namespace="HMDB", chebi_lookup=chebi)
    print(f"refs: {len(refs)}, with KEGG: "
          f"{sum(1 for r in refs if getattr(r, 'kegg_compound_id', None))}")

    # NOTE: pagerank (RWR) requires pagerank.matrix.RData /
    # pagerank.rowSums.RData in /opt/fella_kegg_hsa, which the current
    # Dockerfile pre-warm does not build (matrices="diffusion" only).
    # Adding pagerank matrices would push the build by another ~10-15 min
    # of KEGG-graph computation; OQ deferred to W5 D5 polish if K=10
    # spike shows RWR adds signal beyond diffusion. For W5 D2 we
    # validate only the diffusion path; this still gives us the 5th
    # axis (FELLA) at Gate 1, because RaMP-DB already covers KEGG ORA
    # and the diffusion-vs-RWR split is largely a sensitivity question.
    diff_wall, diff_ok = _run_one("fella_diffusion", run_fella_diffusion, refs, chebi)

    print(f"\n=== D2 summary ===")
    print(f"  Diffusion: wall={diff_wall:.2f}s ok={diff_ok}")
    print(f"  RWR:       SKIPPED (pagerank matrices not in image — see OQ-3)")
    return 0 if diff_ok else 1


if __name__ == "__main__":
    sys.exit(main())
