"""Phase B1 Stage C — per-layer supported aggregator + Step R extension.

Re-verifies each final_narrative once and produces:
1. Per-task supported counts grouped by claim_type (→ layer mapping).
2. Per-layer aggregate supp_ratio (mean across NORMAL tasks).
3. Per-layer Step R: bucket tasks by hybrid top-1 correct/wrong,
   compute Δ = mean(supp_layer | correct) − mean(supp_layer | wrong).

Layer mapping (claim_type → layer):
  BIOLOGICAL          → 6c (biological_sub6; pathway_membership + metabolite_pathway_link)
  SET_ENRICHMENT      → 6a (set_enrichment_sub6)
  DRIVER_METABOLITE   → 6b (driver_metabolite_sub6)
  CONSISTENCY         → D  (consistency layer)

Output for each run root:
  <root>/per_layer_supported.json — per-seed supp_ratio per layer
  <root>/step_r_per_layer.json    — per-layer Step R correlations

Usage:
    PYTHONPATH=. python scripts/eval_sub6/step_r_per_layer.py \
        --input data/eval/sub6/b1_d5_v3_p0fix
"""
from __future__ import annotations

import argparse
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

# Monkey-patch Layer D before importing agent.py
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

LAYER_BY_TYPE = {
    "biological_claim": "biological_sub6_6c",
    "set_enrichment": "set_enrichment_6a",
    "driver_metabolite": "driver_metabolite_6b",
    "consistency_claim": "consistency_d",
    "pathway_relationship": "pathway_relationship_6d",
    "grounded_claim": "grounded_a",
    "factual_roundtrip_claim": "factual_b",
    "literature_claim": "literature_e",
    "peak_mechanistic_claim": "peak_mechanistic_f",
    "other_claim": "other",
}


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


def per_claim_grouped(narrative, task, driver_lookup):
    """Re-verify and return per-claim-type {verdict: count}."""
    source_report = _build_source_report(task)
    try:
        v = verify_sub6(
            narrative, source_report,
            trace_id=f"{task['task_id']}.step_r_per_layer",
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
    pc = per_claim_grouped(narr, task, driver_lookup)
    if "_error" in pc:
        return None
    by_type = pc["by_type"]

    # Per-layer supp_ratio for this task (None if 0 claims in layer)
    per_layer = {}
    for ct, verds in by_type.items():
        layer = LAYER_BY_TYPE.get(ct, ct)
        n_tot = sum(verds.values())
        n_supp = verds.get("supported", 0)
        per_layer[layer] = {
            "n_claims": n_tot,
            "n_supported": n_supp,
            "ratio": n_supp / n_tot if n_tot > 0 else None,
        }
    return {
        "task_id": result.get("task_id"),
        "top1_hybrid": bool(h["method_c_top1"]),
        "per_layer": per_layer,
        "n_total_claims": sum(sum(v.values()) for v in by_type.values()),
    }


def aggregate_per_layer(rows, layer):
    """Return aggregate stats for one layer across rows."""
    ratios = [r["per_layer"][layer]["ratio"]
              for r in rows
              if layer in r["per_layer"] and r["per_layer"][layer]["ratio"] is not None]
    n_claims = sum(r["per_layer"][layer]["n_claims"]
                   for r in rows if layer in r["per_layer"])
    n_supp = sum(r["per_layer"][layer]["n_supported"]
                 for r in rows if layer in r["per_layer"])
    n_tasks = sum(1 for r in rows
                  if layer in r["per_layer"]
                  and r["per_layer"][layer]["n_claims"] > 0)
    return {
        "n_claims": n_claims,
        "n_supported": n_supp,
        "ratio_aggregate": n_supp / n_claims if n_claims > 0 else None,
        "ratio_per_task_mean": sum(ratios) / len(ratios) if ratios else None,
        "n_tasks_with_layer": n_tasks,
    }


def step_r_per_layer(rows, layer):
    """Bucket tasks by top1, compute Δ on per-task supp_ratio for this layer."""
    correct = [r["per_layer"][layer]["ratio"]
               for r in rows
               if r["top1_hybrid"]
               and layer in r["per_layer"]
               and r["per_layer"][layer]["ratio"] is not None]
    wrong = [r["per_layer"][layer]["ratio"]
             for r in rows
             if not r["top1_hybrid"]
             and layer in r["per_layer"]
             and r["per_layer"][layer]["ratio"] is not None]
    def mean(xs): return sum(xs)/len(xs) if xs else None
    def ci95(xs):
        if len(xs) < 2: return 0.0
        return 1.96 * statistics.stdev(xs) / math.sqrt(len(xs))
    mc = mean(correct); mw = mean(wrong)
    return {
        "n_correct": len(correct),
        "n_wrong": len(wrong),
        "mean_correct_pct": mc * 100 if mc is not None else None,
        "mean_wrong_pct": mw * 100 if mw is not None else None,
        "delta_pp": (mc - mw) * 100 if (mc is not None and mw is not None) else None,
        "ci95_correct_pp": ci95(correct) * 100,
        "ci95_wrong_pp": ci95(wrong) * 100,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    args = ap.parse_args()

    lookup = CompoundLookup.from_curated(CURATED)
    driver_lookup = _build_driver_lookup(Path(CURATED))
    tasks = load_benchmark()

    rows = []
    per_seed = {}
    for seed_dir in sorted(d for d in args.input.iterdir()
                            if d.is_dir() and d.name.startswith("seed_")):
        seed_rows = []
        for td in sorted(os.scandir(seed_dir), key=lambda d: d.name):
            if not td.is_dir(): continue
            rf = Path(td.path) / "result.json"
            if not rf.exists(): continue
            r = json.loads(rf.read_text())
            tid = r.get("task_id", "")
            task = task_from_tid(tasks, tid)
            if task is None: continue
            iters = r.get("iterations") or []
            if not iters or not r.get("final_narrative"):
                continue
            m = per_task_metrics(r, task, lookup, driver_lookup)
            if m is None: continue
            m["seed"] = seed_dir.name
            rows.append(m); seed_rows.append(m)
            if len(rows) % 30 == 0:
                print(f"  processed {len(rows)} tasks...")
        per_seed[seed_dir.name] = seed_rows

    # All layers seen
    all_layers = sorted({l for r in rows for l in r["per_layer"]})

    # Aggregate per-layer per-seed
    out_per_layer_supported = {"per_seed": {}, "n3_total": {}}
    for seed_name, seed_rows in per_seed.items():
        out_per_layer_supported["per_seed"][seed_name] = {
            l: aggregate_per_layer(seed_rows, l) for l in all_layers
        }
    out_per_layer_supported["n3_total"] = {
        l: aggregate_per_layer(rows, l) for l in all_layers
    }

    # Step R per layer (cross-seed pooled, since N=3 task instance count is more important)
    step_r_out = {l: step_r_per_layer(rows, l) for l in all_layers}

    # Also include full-supported reference (all layers combined)
    all_correct = [r for r in rows if r["top1_hybrid"]]
    all_wrong = [r for r in rows if not r["top1_hybrid"]]
    def task_supp_all(r):
        n_tot = sum(r["per_layer"][l]["n_claims"] for l in r["per_layer"])
        n_supp = sum(r["per_layer"][l]["n_supported"] for l in r["per_layer"])
        return n_supp / n_tot if n_tot > 0 else None
    sc = [task_supp_all(r) for r in all_correct if task_supp_all(r) is not None]
    sw = [task_supp_all(r) for r in all_wrong if task_supp_all(r) is not None]
    step_r_out["__full__"] = {
        "n_correct": len(sc),
        "n_wrong": len(sw),
        "mean_correct_pct": (sum(sc)/len(sc) * 100) if sc else 0,
        "mean_wrong_pct": (sum(sw)/len(sw) * 100) if sw else 0,
        "delta_pp": (sum(sc)/len(sc) - sum(sw)/len(sw)) * 100 if (sc and sw) else 0,
    }

    (args.input / "per_layer_supported.json").write_text(
        json.dumps(out_per_layer_supported, indent=2)
    )
    (args.input / "step_r_per_layer.json").write_text(
        json.dumps(step_r_out, indent=2)
    )
    print(f"\nWrote {args.input}/per_layer_supported.json")
    print(f"Wrote {args.input}/step_r_per_layer.json")

    print(f"\nn_total_tasks={len(rows)} correct={sum(1 for r in rows if r['top1_hybrid'])}")
    print(f"\n  {'layer':<28} {'supp_ratio':>10} {'n_claims':>10} {'StepR_Δ_pp':>12} {'n_corr/wrong':>14}")
    for l in all_layers:
        agg = out_per_layer_supported["n3_total"][l]
        sr = step_r_out[l]
        ratio = f"{agg['ratio_aggregate']*100:.1f}%" if agg['ratio_aggregate'] is not None else "n/a"
        delta = f"{sr['delta_pp']:+.2f}" if sr['delta_pp'] is not None else "n/a"
        print(f"  {l:<28} {ratio:>10} {agg['n_claims']:>10} {delta:>12} {sr['n_correct']}/{sr['n_wrong']:<6}")
    print(f"  {'__full__':<28} {'—':>10} {'—':>10} {step_r_out['__full__']['delta_pp']:>+12.2f}")


if __name__ == "__main__":
    main()
