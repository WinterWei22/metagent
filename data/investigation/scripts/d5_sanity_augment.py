"""W5 D5 sanity Check 2 + 5 — augment per_task_results with metabolites_hit.

The D4 driver only persisted top-10 pathway_id strings per (task, method);
the sanity-check needs per-pathway metabolites_hit (CompoundRef primary
IDs) to compute compound-level Jaccard and to verify no vacuous PathwayHit
slipped through. Re-runs the wrappers and dumps an augmented jsonl.
"""
from __future__ import annotations
import dataclasses
import json
import sys
import time
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup
from concord.reconcile.id_resolve import resolve_ids_to_compound_refs
from concord.wrappers.sspa_wrapper import run_sspa
from concord.wrappers.ramp_wrapper import run_ramp_enrichment
from concord.wrappers.metaboanalystr_wrapper import run_metaboanalystr_psea
from concord.wrappers.fella_wrapper import run_fella_diffusion
from concord.normalize.sspa_norm import normalize_sspa_output
from concord.normalize.ramp_norm import normalize_ramp_output
from concord.normalize.metaboanalystr_norm import normalize_metaboanalystr_output
from concord.normalize.fella_norm import normalize_fella_output

BENCHMARK = WORKTREE / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks_v3.jsonl"
OUT = WORKTREE / "data" / "concord" / "gate1_w5_5axis" / "per_task_results_n30_augmented.jsonl"
N = 30


def _pathway_hit_to_dict(h):
    return {
        "pathway_id": h.pathway_id,
        "pathway_name": h.pathway_name,
        "score": h.score,
        "rank": h.rank,
        "metabolites_hit": [
            {"primary_id": r.primary_id, "inchikey": r.inchikey}
            for r in (h.metabolites_hit or [])
        ],
        "n_metabolites_in_pathway": h.n_metabolites_in_pathway,
        "n_metabolites_input": h.n_metabolites_input,
    }


def main() -> int:
    tasks = [json.loads(l) for l in BENCHMARK.read_text().splitlines()]
    tasks = [t for t in tasks if "RAMP_P_000052855" not in t["task_id"]][:N]
    chebi = ChebiLookup()

    with OUT.open("w") as fout:
        for ti, task in enumerate(tasks):
            hmdb_ids = [m["hmdb_id"] for m in task["differential_metabolites"]
                        if m.get("hmdb_id")]
            refs, _ = resolve_ids_to_compound_refs(
                hmdb_ids, source_namespace="HMDB", chebi_lookup=chebi)

            print(f"[{ti+1}/{N}] {task['task_id'][:55]}  refs={len(refs)}")
            row = {"task_id": task["task_id"], "n_refs": len(refs)}

            for method_name, fn, normfn, fn_kwargs, norm_kwargs in [
                ("sspa_ora",
                 lambda r: run_sspa(compound_refs=r, method="ora", pathway_db="reactome"),
                 normalize_sspa_output, {}, {}),
                ("ramp",
                 lambda r: run_ramp_enrichment(compound_refs=r),
                 normalize_ramp_output, {}, {}),
                ("PSEA",
                 lambda r: run_metaboanalystr_psea(r, library="kegg", id_type="hmdb", timeout=180),
                 normalize_metaboanalystr_output, {}, {}),
                ("FELLA",
                 lambda r: run_fella_diffusion(r, organism="hsa", timeout=180),
                 normalize_fella_output, {}, {}),
            ]:
                try:
                    t0 = time.time()
                    raw = fn(refs)
                    er = normfn(raw, top_n=10, chebi_lookup=chebi)
                    pathways = [_pathway_hit_to_dict(h) for h in er.pathways]
                    row[method_name] = {
                        "n_pathways": len(pathways),
                        "pathways": pathways,
                        "wall_sec": time.time() - t0,
                    }
                    n_mhit = sum(len(p["metabolites_hit"]) for p in pathways)
                    print(f"  {method_name}: {len(pathways)} pathways, {n_mhit} mhit, {row[method_name]['wall_sec']:.1f}s")
                except Exception as e:
                    row[method_name] = {"error": f"{type(e).__name__}: {e}",
                                          "n_pathways": 0, "pathways": []}
                    print(f"  {method_name}: ERROR {row[method_name]['error'][:80]}")
            fout.write(json.dumps(row) + "\n")
            fout.flush()

    print(f"\nDONE → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
