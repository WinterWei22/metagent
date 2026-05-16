"""W6 D3 — 5-axis run on the three pre-registered Tier-A cohorts.

Runs sspa_ora + mummichog + ramp + PSEA + FELLA on each TierATask in
{tasks_primary, tasks_sens_a, tasks_sens_b}. Persists EnrichmentResult
dicts so D4 Gate-2 metric layer can read top-10 pathways + per-pathway
metabolites_hit without re-running the wrappers.

Per-cohort K=10 concurrency for the R-side methods (PSEA + FELLA) via
ThreadPoolExecutor, since W5 D3 spike showed perfect 10× scaling
(11.8s sequential vs 12.8s for 10 concurrent calls).
"""
from __future__ import annotations
import concurrent.futures
import json
import sys
import time
import traceback
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup
from concord.reconcile.id_resolve import resolve_ids_to_compound_refs

from concord.wrappers.sspa_wrapper import run_sspa
from concord.wrappers.ramp_wrapper import run_ramp_enrichment
from concord.wrappers.mummichog_wrapper import run_mummichog_for_compound_set
from concord.wrappers.metaboanalystr_wrapper import run_metaboanalystr_psea
from concord.wrappers.fella_wrapper import run_fella_diffusion

from concord.normalize.sspa_norm import normalize_sspa_output
from concord.normalize.ramp_norm import normalize_ramp_output
from concord.normalize.mummichog_norm import normalize_mummichog_output
from concord.normalize.metaboanalystr_norm import normalize_metaboanalystr_output
from concord.normalize.fella_norm import normalize_fella_output

COHORTS_DIR = WORKTREE / "data/concord/tier_a_cooke"
OUT_DIR = WORKTREE / "data/concord/gate2_w6"
OUT_DIR.mkdir(parents=True, exist_ok=True)

METHODS = ["sspa_ora", "mummichog", "ramp", "PSEA", "FELLA"]


def _pathway_to_dict(h) -> dict:
    return {
        "pathway_id": h.pathway_id,
        "pathway_name": h.pathway_name,
        "score": h.score,
        "rank": h.rank,
        "metabolites_hit": [
            {"primary_id": r.primary_id, "inchikey": r.inchikey}
            for r in (h.metabolites_hit or [])
        ],
    }


def _run_method(method: str, refs, chebi, seed: int) -> dict:
    try:
        t0 = time.time()
        if method == "sspa_ora":
            raw = run_sspa(compound_refs=refs, method="ora", pathway_db="reactome")
            er = normalize_sspa_output(raw, top_n=10, chebi_lookup=chebi)
        elif method == "mummichog":
            raw = run_mummichog_for_compound_set(refs, mode="positive",
                                                   n_background=250, seed=seed)
            er = normalize_mummichog_output(raw, top_n=10, chebi_lookup=chebi)
        elif method == "ramp":
            raw = run_ramp_enrichment(compound_refs=refs)
            er = normalize_ramp_output(raw, top_n=10, chebi_lookup=chebi)
        elif method == "PSEA":
            raw = run_metaboanalystr_psea(refs, library="kegg", id_type="hmdb",
                                            timeout=180)
            er = normalize_metaboanalystr_output(raw, top_n=10, chebi_lookup=chebi)
        elif method == "FELLA":
            raw = run_fella_diffusion(refs, organism="hsa", timeout=180)
            er = normalize_fella_output(raw, top_n=10, chebi_lookup=chebi)
        else:
            raise ValueError(method)
        wall = time.time() - t0
        return {
            "method": method,
            "n_pathways": len(er.pathways),
            "pathways": [_pathway_to_dict(h) for h in er.pathways],
            "wall_sec": wall,
            "schema_version": er.schema_version,
        }
    except Exception as e:
        return {
            "method": method,
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc(limit=2),
            "n_pathways": 0,
            "pathways": [],
        }


def _refs_from_task(task: dict, chebi: ChebiLookup) -> list:
    ids = [c["chebi_id"].replace("CHEBI:", "") for c in task["differential_metabolites"]]
    refs, _ = resolve_ids_to_compound_refs(ids, "CHEBI", chebi)
    return refs


def run_cohort(cohort: str, chebi: ChebiLookup, k_concurrent: int = 10) -> dict:
    tasks_path = COHORTS_DIR / f"tasks_{cohort}.jsonl"
    tasks = [json.loads(l) for l in tasks_path.read_text().splitlines()]
    print(f"\n=== D3 5-axis on cohort={cohort} N={len(tasks)} ===")

    out_path = OUT_DIR / f"5axis_results_{cohort}.jsonl"
    fail_count = {m: 0 for m in METHODS}
    cohort_t0 = time.time()

    with out_path.open("w") as fout:
        # Single ThreadPool: enqueue ALL (task, method) pairs at once so
        # PSEA + FELLA — the only thread-safe-via-docker-exec heavyweights —
        # parallelise across tasks freely. sspa/ramp/mummichog also overlap
        # cheaply.
        all_jobs = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=k_concurrent) as exe:
            futures = {}
            for ti, task in enumerate(tasks):
                refs = _refs_from_task(task, chebi)
                if not refs:
                    fout.write(json.dumps({"task_id": task["task_id"], "error": "no refs"}) + "\n")
                    continue
                for method in METHODS:
                    fut = exe.submit(_run_method, method, refs, chebi,
                                       seed=hash(task["task_id"]) & 0xffffffff)
                    futures[fut] = (ti, task, method)

            results_by_task: dict[int, dict] = {}
            for fut in concurrent.futures.as_completed(futures):
                ti, task, method = futures[fut]
                row = fut.result()
                if row.get("error"):
                    fail_count[method] += 1
                results_by_task.setdefault(ti, {
                    "task_id": task["task_id"],
                    "ground_truth_pathway_name": task["perturbation_pathway_name"],
                    "ground_truth_pathway_id": task["perturbation_pathway_id"],
                    "cohort": cohort,
                })
                results_by_task[ti][method] = row

            for ti in sorted(results_by_task.keys()):
                fout.write(json.dumps(results_by_task[ti]) + "\n")

    cohort_wall = time.time() - cohort_t0
    print(f"  cohort={cohort} wall={cohort_wall:.1f}s  failures by method: {fail_count}")
    return {"cohort": cohort, "n_tasks": len(tasks),
            "wall_sec": cohort_wall, "fail_count": fail_count,
            "out_path": str(out_path)}


def main() -> int:
    chebi = ChebiLookup()
    summary = {}
    for cohort in ("primary", "sens_a", "sens_b"):
        summary[cohort] = run_cohort(cohort, chebi, k_concurrent=10)
    (OUT_DIR / "5axis_summary.json").write_text(json.dumps(summary, indent=2))
    print("\n=== D3 summary ===")
    for c, s in summary.items():
        n_fail_total = sum(s["fail_count"].values())
        print(f"  {c:8s} N={s['n_tasks']:2d}  wall={s['wall_sec']:.1f}s  "
              f"failures={n_fail_total} {s['fail_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
