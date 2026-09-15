"""W6 D2 — single-method (RaMP) baseline on the three Tier-A cohorts.

For each TierATask in {tasks_primary, tasks_sens_a, tasks_sens_b}:
  - run RaMP enrichment via concord.wrappers.ramp_wrapper
  - normalise to v0.3 EnrichmentResult
  - record top-10 pathway names + name-fuzzy hit vs ground-truth pathway

Per-cohort aggregate: hit rate, mean rank when hit, wall-time total.
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
from concord.wrappers.ramp_wrapper import run_ramp_enrichment
from concord.normalize.ramp_norm import normalize_ramp_output
from concord.analyze.pathway_match import best_matching_rank

COHORTS_DIR = WORKTREE / "data/concord/tier_a_cooke"
OUT_DIR = WORKTREE / "data/concord/gate2_w6"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _refs_from_task(task: dict, chebi: ChebiLookup) -> list:
    ids = [c["chebi_id"].replace("CHEBI:", "") for c in task["differential_metabolites"]]
    refs, _ = resolve_ids_to_compound_refs(ids, "CHEBI", chebi)
    return refs


def run_cohort(cohort_name: str, chebi: ChebiLookup) -> dict:
    tasks_path = COHORTS_DIR / f"tasks_{cohort_name}.jsonl"
    tasks = [json.loads(l) for l in tasks_path.read_text().splitlines()]
    print(f"\n=== D2 baseline RaMP on cohort={cohort_name} N={len(tasks)} ===")

    out_path = OUT_DIR / f"baseline_ramp_{cohort_name}.jsonl"
    rows = []
    n_hit = 0
    walls = []

    with out_path.open("w") as fout:
        for ti, task in enumerate(tasks):
            refs = _refs_from_task(task, chebi)
            if not refs:
                rec = {"task_id": task["task_id"], "error": "no refs"}
                fout.write(json.dumps(rec) + "\n"); rows.append(rec); continue
            try:
                t0 = time.time()
                raw = run_ramp_enrichment(compound_refs=refs)
                er = normalize_ramp_output(raw, top_n=10, chebi_lookup=chebi)
                wall = time.time() - t0
            except Exception as e:
                rec = {"task_id": task["task_id"], "error": f"{type(e).__name__}: {e}"}
                fout.write(json.dumps(rec) + "\n"); rows.append(rec); continue

            walls.append(wall)
            top_names = [p.pathway_name for p in er.pathways]
            top_ids = [p.pathway_id for p in er.pathways]
            hit_rank = best_matching_rank(task["perturbation_pathway_name"], top_names)
            hit = hit_rank is not None
            n_hit += int(hit)
            rec = {
                "task_id": task["task_id"],
                "ground_truth_pathway_name": task["perturbation_pathway_name"],
                "ground_truth_pathway_id": task["perturbation_pathway_id"],
                "ramp_top10_names": top_names,
                "ramp_top10_ids": top_ids,
                "ramp_hit": hit,
                "ramp_rank": hit_rank,
                "wall_sec": wall,
                "n_refs": len(refs),
            }
            fout.write(json.dumps(rec) + "\n")
            rows.append(rec)
            if ti < 3 or ti % 10 == 0:
                print(f"  [{ti+1:2d}/{len(tasks)}] {task['task_id'][:55]:55s} hit={hit} rank={hit_rank}")

    hit_rate = n_hit / max(len(tasks), 1)
    print(f"  cohort={cohort_name} hit_rate={hit_rate:.1%} ({n_hit}/{len(tasks)})  "
          f"wall_total={sum(walls):.1f}s")
    return {
        "cohort": cohort_name,
        "n_tasks": len(tasks),
        "n_hit": n_hit,
        "hit_rate": hit_rate,
        "wall_total_sec": sum(walls),
        "wall_median_sec": sorted(walls)[len(walls)//2] if walls else 0.0,
        "out_path": str(out_path),
    }


def main() -> int:
    chebi = ChebiLookup()
    summary = {c: run_cohort(c, chebi) for c in ("primary", "sens_a", "sens_b")}
    (OUT_DIR / "baseline_ramp_summary.json").write_text(json.dumps(summary, indent=2))
    print("\n=== D2 summary ===")
    for c, s in summary.items():
        print(f"  {c:8s} N={s['n_tasks']:2d} hit_rate={s['hit_rate']:.1%} ({s['n_hit']}/{s['n_tasks']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
