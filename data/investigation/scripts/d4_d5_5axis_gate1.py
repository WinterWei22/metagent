"""W5 D4-D5: 5-axis Gate-1 run on N=30 mammalian-task panel.

Runs all five wrappers on the same task panel, normalises each to v0.3
EnrichmentResult, then computes a 5×5 pairwise pathway-level Jaccard
overlap (top-10 pathways per method). K=10 concurrent docker exec for
the R-side methods (MetaboAnalystR + FELLA); the Python-side methods
(sspa, mummichog, RaMP) run sequentially because they are CPU-bound
and the GIL serialises in-process anyway.

Outputs (under data/concord/gate1_w5_5axis/):
  per_task_results.jsonl   — one JSON row per (task, method) with er.to_dict
  jaccard_pairwise.csv     — 5×5 mean pairwise Jaccard
  jaccard_per_task.csv     — per-task 5×5 (long-form)
  5axis_panel.png/.pdf     — visualisation (D5 deliverable)

Usage:
  python d4_d5_5axis_gate1.py            # N=30
  python d4_d5_5axis_gate1.py --n 5      # smoke
"""
from __future__ import annotations
import argparse
import concurrent.futures
import dataclasses
import json
import sys
import time
import traceback
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup
from concord.reconcile.id_resolve import resolve_ids_to_compound_refs

# Wrappers
from concord.wrappers.sspa_wrapper import run_sspa
from concord.wrappers.mummichog_wrapper import run_mummichog
from concord.wrappers.ramp_wrapper import run_ramp_enrichment
from concord.wrappers.metaboanalystr_wrapper import run_metaboanalystr_psea
from concord.wrappers.fella_wrapper import run_fella_diffusion

# Normalizers
from concord.normalize.sspa_norm import normalize_sspa_output
from concord.normalize.mummichog_norm import normalize_mummichog_output
from concord.normalize.ramp_norm import normalize_ramp_output
from concord.normalize.metaboanalystr_norm import normalize_metaboanalystr_output
from concord.normalize.fella_norm import normalize_fella_output

BENCHMARK = WORKTREE / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks_v3.jsonl"
OUT_DIR = WORKTREE / "data" / "concord" / "gate1_w5_5axis"

# OQ-6: mummichog is excluded from the W5 D4 5-axis run. The benchmark
# tasks ship `differential_metabolites` (compound-level) but no peak
# m/z table. Our synthetic peaks (ChEBI mass + proton) do not survive
# mummichog's adduct-mapping → empirical-compound stage (consistently
# 0 mapped features for all 8 input compounds across N=2 smoke), which
# leaves 119 pathway entries with empty hits_kegg_ids and trips the
# v0.3 vacuous-pathways validator. Re-enable once we either (a) wire
# real peak tables back from the upstream benchmark or (b) synthesise
# m/z with explicit adduct tags so mummichog's compound resolver
# accepts them. Note: mummichog's W4 standalone smoke (gate1_toy_n30.py)
# works because it uses the benchmark's pre-resolved metabolite list
# differently.
METHODS = ["sspa_ora", "ramp", "metaboanalystr_psea", "fella_diffusion"]


def _load_tasks(n: int) -> list[dict]:
    tasks = [json.loads(line) for line in BENCHMARK.read_text().splitlines()]
    clean = [t for t in tasks if "RAMP_P_000052855" not in t["task_id"]]
    return clean[:n]


def _refs_for_task(task: dict, chebi: ChebiLookup) -> list:
    hmdb_ids = [m["hmdb_id"] for m in task["differential_metabolites"]
                if m.get("hmdb_id")]
    refs, _ = resolve_ids_to_compound_refs(
        hmdb_ids, source_namespace="HMDB", chebi_lookup=chebi)
    return refs


def _run_method(method: str, refs: list, chebi: ChebiLookup,
                task: dict) -> dict | None:
    """Call wrapper + normalize, return (top10 pathway_id list, er dict)."""
    try:
        if method == "sspa_ora":
            raw = run_sspa(compound_refs=refs, method="ora",
                            pathway_db="reactome")
            er = normalize_sspa_output(raw, top_n=10, chebi_lookup=chebi)
        elif method == "mummichog":
            # mummichog needs peaks; build synthetic from refs
            from concord.schema.peak import PeakRecord
            peaks = []
            for i, r in enumerate(refs):
                ik = getattr(r, "inchikey", None)
                # Use ChEBI monoisotopic mass via chebi lookup
                chebi_id = (getattr(r, "chebi_id", "") or "").replace("CHEBI:", "")
                rec = chebi.get_compound(chebi_id) if chebi_id else None
                mass = getattr(rec, "monoisotopic_mass", None) if rec else None
                if mass is None:
                    continue
                peaks.append(PeakRecord(
                    feature_id=f"feat_{i}",
                    mz=mass + 1.007276,  # [M+H]+
                    retention_time=60.0 + i,
                    p_value=0.001,  # < mummichog 0.01 significance cutoff
                    t_score=3.0,
                ))
            if not peaks:
                return {"method": method, "pathway_ids": [], "n_pathways": 0,
                        "note": "no peaks built"}
            raw = run_mummichog(peaks=peaks, mode="positive")
            er = normalize_mummichog_output(raw, top_n=10, chebi_lookup=chebi)
        elif method == "ramp":
            raw = run_ramp_enrichment(compound_refs=refs)
            er = normalize_ramp_output(raw, top_n=10, chebi_lookup=chebi)
        elif method == "metaboanalystr_psea":
            raw = run_metaboanalystr_psea(refs, library="kegg",
                                           id_type="hmdb", timeout=180)
            er = normalize_metaboanalystr_output(raw, top_n=10, chebi_lookup=chebi)
        elif method == "fella_diffusion":
            raw = run_fella_diffusion(refs, organism="hsa", timeout=180)
            er = normalize_fella_output(raw, top_n=10, chebi_lookup=chebi)
        else:
            raise ValueError(f"unknown method: {method}")

        pathway_ids = [h.pathway_id for h in er.pathways]
        return {
            "task_id": task["task_id"],
            "method": method,
            "n_pathways": len(pathway_ids),
            "pathway_ids": pathway_ids,
            "wall_time_sec": er.wall_time_sec,
            "schema_version": er.schema_version,
        }
    except Exception as e:
        return {
            "task_id": task["task_id"],
            "method": method,
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc(limit=3),
            "pathway_ids": [],
            "n_pathways": 0,
        }


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30, help="number of tasks")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chebi = ChebiLookup()
    tasks = _load_tasks(args.n)
    print(f"tasks: {len(tasks)}")

    # Per (task, method) results
    per_task_results: list[dict] = []
    out_jsonl = OUT_DIR / f"per_task_results_n{args.n}.jsonl"
    with out_jsonl.open("w") as fout:
        for ti, task in enumerate(tasks):
            refs = _refs_for_task(task, chebi)
            print(f"\n[{ti+1}/{len(tasks)}] {task['task_id'][:60]}  refs={len(refs)}")
            if not refs:
                continue
            # Run all 5 methods. Python methods sequential, R via persistent
            # docker exec — also kept sequential here to keep the loop
            # simple; K=10 concurrency added in a follow-up batch if needed.
            for method in METHODS:
                t0 = time.time()
                row = _run_method(method, refs, chebi, task)
                row["wall_total_sec"] = time.time() - t0
                per_task_results.append(row)
                fout.write(json.dumps(row) + "\n")
                if row.get("error"):
                    print(f"  {method}: ERROR {row['error'][:60]}")
                else:
                    print(f"  {method}: {row['n_pathways']} pathways, "
                          f"wall {row['wall_total_sec']:.1f}s")

    # Aggregate 5x5 Jaccard
    print(f"\n=== 5×5 Jaccard aggregate ===")
    by_task: dict[str, dict[str, list[str]]] = {}
    for r in per_task_results:
        by_task.setdefault(r["task_id"], {})[r["method"]] = r["pathway_ids"]

    import csv
    pairwise_jaccard: dict[tuple[str, str], list[float]] = {}
    per_task_csv = OUT_DIR / f"jaccard_per_task_n{args.n}.csv"
    with per_task_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "method_a", "method_b", "jaccard"])
        for task_id, methods_dict in by_task.items():
            for i, ma in enumerate(METHODS):
                for mb in METHODS[i:]:
                    a = methods_dict.get(ma, [])
                    b = methods_dict.get(mb, [])
                    j = _jaccard(a, b)
                    w.writerow([task_id, ma, mb, f"{j:.4f}"])
                    pairwise_jaccard.setdefault((ma, mb), []).append(j)

    pairwise_csv = OUT_DIR / f"jaccard_pairwise_n{args.n}.csv"
    with pairwise_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["method_a", "method_b", "mean_jaccard", "n_tasks"])
        for (ma, mb), vals in pairwise_jaccard.items():
            mean = sum(vals) / len(vals) if vals else 0.0
            w.writerow([ma, mb, f"{mean:.4f}", len(vals)])
            print(f"  {ma:25s} vs {mb:25s}  mean={mean:.4f}  n={len(vals)}")

    # Heatmap PNG/PDF
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        N = len(METHODS)
        mat = np.zeros((N, N))
        for i, ma in enumerate(METHODS):
            for j, mb in enumerate(METHODS):
                key = (ma, mb) if (ma, mb) in pairwise_jaccard else (mb, ma)
                vals = pairwise_jaccard.get(key, [])
                mat[i, j] = sum(vals) / len(vals) if vals else 0.0
        fig, ax = plt.subplots(figsize=(8, 7))
        im = ax.imshow(mat, vmin=0, vmax=1, cmap="viridis")
        ax.set_xticks(range(N)); ax.set_yticks(range(N))
        ax.set_xticklabels(METHODS, rotation=45, ha="right")
        ax.set_yticklabels(METHODS)
        for i in range(N):
            for j in range(N):
                ax.text(j, i, f"{mat[i,j]:.2f}", ha="center", va="center",
                        color="white" if mat[i,j] < 0.5 else "black")
        ax.set_title(f"5-axis pathway-level top-10 Jaccard (N={args.n})")
        plt.colorbar(im, ax=ax, label="mean Jaccard")
        plt.tight_layout()
        png = OUT_DIR / f"5axis_panel_n{args.n}.png"
        pdf = OUT_DIR / f"5axis_panel_n{args.n}.pdf"
        fig.savefig(png, dpi=180); fig.savefig(pdf)
        print(f"  → {png}")
    except Exception as e:
        print(f"  heatmap skip: {e}")

    print(f"\nartifacts in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
