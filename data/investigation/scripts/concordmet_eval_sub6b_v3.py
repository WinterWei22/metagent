"""ConcordMet evaluation on Sub-6B v3 — per-method + 4 metric variants.

Adapts the W6 D3 5-axis driver and the W7 D4 Gate-2 compute to Sub-6B
v3 tasks. For each task:

  1. differential_metabolites → CompoundRef list (via HMDB → ChEBI)
  2. ground truth pathway name = task.ground_truth_pathway.pathway_name
  3. run 5 wrappers (sspa_ora, ramp, PSEA, mummichog, FELLA) K=10
     concurrent
  4. per-method top-10 vs ground truth (name-fuzzy + strict)
  5. V0 / V1 / V2 / V3 cohort verdicts + per-task precision

Read-only — no benchmark file modified.
"""
from __future__ import annotations
import concurrent.futures
import json
import re
import statistics
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

WORKTREE = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5_investigation")
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

from concord.analyze.pathway_match import best_matching_rank, pathway_name_overlap
from concord.analyze.gate2_variants import (
    metric_v1_cohort, metric_v2_cohort, metric_v3_cohort,
    _weighted_top_v3, variant_verdict,
)
from concord.analyze.paradigm_consensus import metric_2_cohort as metric_v0_cohort

OUT_DIR = WORKTREE / "data/concord/eval_sub6b_v3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

METHODS = ["sspa_ora", "mummichog", "ramp", "PSEA", "FELLA"]


def _refs_from_v3_task(t: dict, chebi: ChebiLookup) -> list:
    """v3 dm carries hmdb_id + inchikey + kegg_id all populated.
    Resolve via HMDB → ChEBI for the highest ChEBI primary-id hit rate."""
    ids = [m["hmdb_id"] for m in (t.get("differential_metabolites") or [])
            if m.get("hmdb_id")]
    refs, _ = resolve_ids_to_compound_refs(ids, "HMDB", chebi)
    return refs


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
        }
    except Exception as e:
        return {"method": method, "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc(limit=2),
                "n_pathways": 0, "pathways": []}


def run_5axis(tasks: list[dict], chebi: ChebiLookup, k_concurrent: int = 10) -> str:
    out_path = OUT_DIR / "5axis_results_v3.jsonl"
    fail_count: dict[str, int] = {m: 0 for m in METHODS}
    no_ref_tasks = 0

    print(f"\n=== Running 5-axis on Sub-6B v3 (N={len(tasks)}, K={k_concurrent}) ===")
    cohort_t0 = time.time()
    with out_path.open("w") as fout:
        with concurrent.futures.ThreadPoolExecutor(max_workers=k_concurrent) as exe:
            futures = {}
            for ti, task in enumerate(tasks):
                refs = _refs_from_v3_task(task, chebi)
                if not refs:
                    no_ref_tasks += 1
                    fout.write(json.dumps({"task_id": task["task_id"], "error": "no refs"}) + "\n")
                    continue
                for m in METHODS:
                    fut = exe.submit(_run_method, m, refs, chebi,
                                       seed=hash(task["task_id"]) & 0xffffffff)
                    futures[fut] = (ti, task, m)

            results_by_task: dict[int, dict] = {}
            for fut in concurrent.futures.as_completed(futures):
                ti, task, m = futures[fut]
                row = fut.result()
                if row.get("error"):
                    fail_count[m] += 1
                results_by_task.setdefault(ti, {
                    "task_id": task["task_id"],
                    "ground_truth_pathway_name": task["ground_truth_pathway"]["pathway_name"],
                    "ground_truth_pathway_id": task["ground_truth_pathway"]["pathway_id"],
                    "ground_truth_pathway_source": task["ground_truth_pathway"]["pathway_source"],
                })
                results_by_task[ti][m] = row

            for ti in sorted(results_by_task.keys()):
                fout.write(json.dumps(results_by_task[ti]) + "\n")

    wall = time.time() - cohort_t0
    print(f"5-axis wall {wall:.1f}s · no_ref={no_ref_tasks} · failures {fail_count}")
    return str(out_path)


def _strict_match(gt: str, candidate: str) -> bool:
    def clean(s):
        s = s.lower()
        s = re.sub(r"\s+-\s+homo sapiens.*$", "", s)
        s = re.sub(r"[(),:\-_/]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s
    return clean(gt) == clean(candidate)


def _per_method_hit_rates(rows: list[dict]) -> dict:
    """Per-wrapper hit-rate against ground truth, both strict + fuzzy."""
    out = {}
    for m in METHODS:
        n_strict, n_fuzzy, n_total = 0, 0, 0
        ranks = []
        walls = []
        n_empty = 0
        for r in rows:
            block = r.get(m)
            if not block or block.get("error"): continue
            n_total += 1
            walls.append(block.get("wall_sec", 0))
            top_names = [p["pathway_name"] for p in (block.get("pathways") or [])]
            if not top_names:
                n_empty += 1; continue
            gt = r["ground_truth_pathway_name"]
            if any(_strict_match(gt, n) for n in top_names):
                n_strict += 1
            fr = best_matching_rank(gt, top_names)
            if fr is not None:
                n_fuzzy += 1; ranks.append(fr)
        out[m] = {
            "n_total": n_total, "n_empty_top10": n_empty,
            "n_strict_hit": n_strict, "n_fuzzy_hit": n_fuzzy,
            "strict_precision": n_strict / n_total if n_total else 0,
            "fuzzy_precision": n_fuzzy / n_total if n_total else 0,
            "median_rank_when_fuzzy_hit": statistics.median(ranks) if ranks else None,
            "wall_median_sec": statistics.median(walls) if walls else 0,
        }
    return out


def _task_input_chebi(tasks: list[dict]) -> dict[str, set[str]]:
    """task_id → set of ChEBI primary IDs (for V2 metric)."""
    chebi = ChebiLookup()
    out = {}
    for t in tasks:
        refs = _refs_from_v3_task(t, chebi)
        out[t["task_id"]] = {r.primary_id for r in refs if r.primary_id.startswith("CHEBI:")}
    return out


def main():
    chebi = ChebiLookup()
    tasks = [json.loads(l) for l in (WORKTREE / "data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl").read_text().splitlines()]
    print(f"Sub-6B v3 tasks: {len(tasks)}")
    print(f"pathway sources: {Counter(t['ground_truth_pathway']['pathway_source'] for t in tasks)}")

    # 1. Run 5-axis
    out_path = run_5axis(tasks, chebi, k_concurrent=10)

    # 2. Load
    rows = [json.loads(l) for l in Path(out_path).read_text().splitlines() if "error" not in json.loads(l).keys() or "task_id" in json.loads(l)]
    rows = [r for r in rows if r.get("ground_truth_pathway_name")]  # filter no-ref tasks
    print(f"\nrows with 5-axis output: {len(rows)}")

    # 3. Per-method hit rates
    per_method = _per_method_hit_rates(rows)
    print("\n=== Per-method hit rates (vs ground truth pathway name) ===")
    print(f"{'method':<14}{'n':>4}{'empty':>6}{'strict':>8}{'fuzzy':>8}{'med_rank':>10}{'wall_med':>10}")
    for m in METHODS:
        s = per_method[m]
        print(f"{m:<14}{s['n_total']:>4}{s['n_empty_top10']:>6}"
              f"{s['strict_precision']:>8.1%}{s['fuzzy_precision']:>8.1%}"
              f"  {str(s['median_rank_when_fuzzy_hit']):>7}  {s['wall_median_sec']:>8.1f}s")

    # 4. 4-variant Gate-2
    print("\n=== 4-variant Gate-2 metrics (Cond A=RaMP baseline / Cond B=consensus) ===")
    inp = _task_input_chebi(tasks)
    v0 = metric_v0_cohort(rows)
    v1 = metric_v1_cohort(rows)
    v2 = metric_v2_cohort(rows, task_input_chebi=inp)
    v3 = metric_v3_cohort(rows)
    print(f"{'variant':<24}{'A_prec':>8}{'B_prec':>8}{'Δpp':>8}{'sign_p':>9}{'+/-':>7}  verdict")
    for label, m in [("V0_strict", v0), ("V1_fuzzy_inter", v1),
                      ("V2_compound_member", v2), ("V3_soft_union", v3)]:
        if "metric_2_pass" in m and "metric_pass" not in m:
            m["metric_pass"] = m["metric_2_pass"]
        verdict = variant_verdict(m)
        print(f"{label:<24}{m['cond_a']['mean_precision']:>8.3f}"
              f"{m['cond_b']['mean_precision']:>8.3f}"
              f"{m['delta_precision_mean']*100:>+8.2f}"
              f"{m['sign_test_p']:>9.3f}"
              f"  {m['sign_test_pos']}/{m['sign_test_neg']:>3}  {verdict}")

    # 5. Per-source bucket
    print("\n=== Per-pathway-source breakdown (V3) ===")
    source_rows = {}
    for r in rows:
        src = next((t["ground_truth_pathway"]["pathway_source"]
                     for t in tasks if t["task_id"] == r["task_id"]), "?")
        source_rows.setdefault(src, []).append(r)
    for src, srs in source_rows.items():
        gts = [r["ground_truth_pathway_name"] for r in srs]
        ramp_hits = sum(1 for r in srs if best_matching_rank(r["ground_truth_pathway_name"],
                          [p["pathway_name"] for p in r.get("ramp", {}).get("pathways", [])]) is not None)
        v3_hits = sum(1 for r in srs if best_matching_rank(r["ground_truth_pathway_name"],
                        _weighted_top_v3(r, top_n=10)) is not None)
        n = len(srs)
        print(f"  {src:<14} n={n:2d}  ramp={ramp_hits}/{n} ({100*ramp_hits/n:.0f}%)  "
              f"V3={v3_hits}/{n} ({100*v3_hits/n:.0f}%)  Δ={(v3_hits-ramp_hits)/n*100:+.1f}pp")

    # 6. Save full summary
    summary = {
        "n_tasks": len(tasks), "n_rows_with_output": len(rows),
        "per_method": per_method,
        "variants": {
            "V0_strict": {"cond_a": v0["cond_a"]["mean_precision"],
                            "cond_b": v0["cond_b"]["mean_precision"],
                            "delta_pp": v0["delta_precision_mean"]*100,
                            "sign_p": v0["sign_test_p"]},
            "V1_fuzzy_inter": {"cond_a": v1["cond_a"]["mean_precision"],
                                "cond_b": v1["cond_b"]["mean_precision"],
                                "delta_pp": v1["delta_precision_mean"]*100,
                                "sign_p": v1["sign_test_p"]},
            "V2_compound_member": {"cond_a": v2["cond_a"]["mean_precision"],
                                   "cond_b": v2["cond_b"]["mean_precision"],
                                   "delta_pp": v2["delta_precision_mean"]*100,
                                   "sign_p": v2["sign_test_p"]},
            "V3_soft_union": {"cond_a": v3["cond_a"]["mean_precision"],
                                "cond_b": v3["cond_b"]["mean_precision"],
                                "delta_pp": v3["delta_precision_mean"]*100,
                                "sign_p": v3["sign_test_p"]},
        },
    }
    (OUT_DIR / "summary_v3.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nwrote {OUT_DIR}/summary_v3.json + {out_path}")


if __name__ == "__main__":
    main()
