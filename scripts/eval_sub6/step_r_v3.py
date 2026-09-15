"""Phase B1 verification — Step R driver-filtered correlation on v3 N=3.

Replicates the v2 Step R logic (`reports/agent/phase_b1_d6_step_r.md`)
on the v3 P0-fix N=3 data, to address red-line #4 (driver-filtered
supported<->correct correlation Delta >= +18 pp).

Method:
  1. For each NORMAL task across 3 seeds: re-run verify_sub6 on the
     saved final_narrative (Layer D consistency check mocked out to
     avoid LLM calls).
  2. Aggregate per-claim verdicts grouped by claim_type.
  3. Compute supp_ratio_driver per task (None if 0 driver claims).
  4. Use hybrid extractor's c_top1 to bucket tasks (correct vs wrong).
  5. Delta = mean(supp_driver | correct) - mean(supp_driver | wrong).

Cost: ~$0 (Layer D mocked; only RaMP-lookup verifiers fire).
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Monkey-patch Layer D BEFORE importing agent.py
import verifier.layers.consistency as _layer_d
_layer_d.detect_consistency_contradictions = (
    lambda classified, trace_id=None, **kw: ([], 0, [])
)

from evaluation.sub6.compound_lookup import CompoundLookup
from scripts.eval_sub6.analyze_d4_efficacy import hybrid_top1
from scripts.eval_sub6.grade_with_verifier import _build_driver_lookup, _build_source_report
from verifier.agent import verify_sub6


BENCH = "data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl"
CURATED = "data/benchmark/sub6/curated_hmdb_mammalian.jsonl"
RAMP_DB = os.environ.get(
    "METAGENT_RAMP_PATH",
    "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite",
)
INPUT_ROOT = Path("data/eval/sub6/b1_d5_v3_p0fix")


def load_benchmark():
    tasks = {}
    with open(BENCH) as f:
        for line in f:
            line = line.strip()
            if line:
                t = json.loads(line)
                tasks[t["task_id"]] = t
    return tasks


def task_from_tid(tasks, tid):
    t = tasks.get(tid)
    if t is None:
        for pre in ("compound_only_enrich_mammalian_", "compound_only_enrich_lipid_"):
            if tid.startswith(pre):
                t = tasks.get(tid[len(pre):])
                if t:
                    break
    return t


def per_claim_verdicts(narrative, task, driver_lookup):
    source_report = _build_source_report(task)
    try:
        v = verify_sub6(
            narrative, source_report,
            trace_id=f"{task['task_id']}.step_r_v3",
            ramp_db_path=RAMP_DB,
            driver_lookup=driver_lookup,
        )
    except Exception as e:
        return {"_error": str(e)}
    by_type = {}
    for c in v.claims_v2:
        ct = c.claim_type.value if hasattr(c.claim_type, "value") else str(c.claim_type)
        by_type.setdefault(ct, Counter())[c.verdict.value] += 1
    return {"by_type": {k: dict(v) for k, v in by_type.items()}}


def per_task_metrics(result, task, lookup, driver_lookup):
    narr = result.get("final_narrative") or ""
    if not narr:
        return None
    h = hybrid_top1(narr, task, lookup)
    per_claim = per_claim_verdicts(narr, task, driver_lookup)
    if "_error" in per_claim:
        return None
    by_type = per_claim["by_type"]
    drv = by_type.get("driver_metabolite", {})
    n_drv_total = sum(drv.values())
    n_drv_supp = drv.get("supported", 0)
    supp_driver = n_drv_supp / n_drv_total if n_drv_total > 0 else None
    total_all = sum(sum(v.values()) for v in by_type.values())
    total_supp = sum(v.get("supported", 0) for v in by_type.values())
    supp_all = total_supp / total_all if total_all > 0 else 0
    return {
        "task_id": result.get("task_id"),
        "top1_hybrid": bool(h["method_c_top1"]),
        "supp_all": supp_all,
        "supp_driver": supp_driver,
        "n_driver": n_drv_total,
    }


def main():
    lookup = CompoundLookup.from_curated(CURATED)
    driver_lookup = _build_driver_lookup(Path(CURATED))
    tasks = load_benchmark()

    rows = []
    for seed in ["seed_0", "seed_1", "seed_2"]:
        seed_dir = INPUT_ROOT / seed
        for td in sorted(os.scandir(seed_dir), key=lambda d: d.name):
            if not td.is_dir():
                continue
            rf = Path(td.path) / "result.json"
            if not rf.exists():
                continue
            r = json.loads(rf.read_text())
            tid = r.get("task_id", "")
            task = task_from_tid(tasks, tid)
            if task is None:
                continue
            iters = r.get("iterations") or []
            if not iters or not r.get("final_narrative"):
                continue
            m = per_task_metrics(r, task, lookup, driver_lookup)
            if m is None:
                continue
            m["seed"] = seed
            rows.append(m)
            if len(rows) % 20 == 0:
                print(f"  processed {len(rows)} tasks...")

    correct = [r for r in rows if r["top1_hybrid"]]
    wrong = [r for r in rows if not r["top1_hybrid"]]
    cwd = [r for r in correct if r["supp_driver"] is not None]
    wwd = [r for r in wrong if r["supp_driver"] is not None]

    def mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    def ci95(xs):
        if len(xs) < 2:
            return 0.0
        return 1.96 * statistics.stdev(xs) / math.sqrt(len(xs))

    sd_c = mean([r["supp_driver"] for r in cwd])
    sd_w = mean([r["supp_driver"] for r in wwd])
    sa_c = mean([r["supp_all"] for r in correct])
    sa_w = mean([r["supp_all"] for r in wrong])

    out = {
        "n_total": len(rows),
        "n_correct": len(correct),
        "n_wrong": len(wrong),
        "n_correct_with_driver": len(cwd),
        "n_wrong_with_driver": len(wwd),
        "supp_driver_correct_mean": sd_c,
        "supp_driver_wrong_mean": sd_w,
        "supp_driver_delta_pp": (sd_c - sd_w) * 100,
        "supp_all_correct_mean": sa_c,
        "supp_all_wrong_mean": sa_w,
        "supp_all_delta_pp": (sa_c - sa_w) * 100,
        "ci95_supp_driver_correct_pp": ci95([r["supp_driver"] for r in cwd]) * 100,
        "ci95_supp_driver_wrong_pp": ci95([r["supp_driver"] for r in wwd]) * 100,
    }

    out_path = INPUT_ROOT / "step_r_v3_driver_filtered.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {out_path}")
    print(f"n_total={out['n_total']} n_correct={out['n_correct']} n_wrong={out['n_wrong']}")
    print(f"driver delta = {out['supp_driver_delta_pp']:+.2f} pp")
    print(f"full   delta = {out['supp_all_delta_pp']:+.2f} pp")
    print(f"v2 Step R baseline: driver +5.00 pp, full -0.79 pp")
    gate = "PASS" if out["supp_driver_delta_pp"] >= 18 else (
        "DIRECTIONAL" if out["supp_driver_delta_pp"] >= 10 else "FAIL"
    )
    print(f"Red line #4 threshold: >= +18 pp -> {gate}")


if __name__ == "__main__":
    main()
