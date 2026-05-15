"""§8 Gate 1 toy — N=30 expansion(Session 4 per user spec).

Differences vs gate1_toy.py:
  1. **Multi-seed task selection**(default seeds 42/41/40)→ dedupe → N≈30 tasks
  2. **R-NEW-16 partial fix**:wire real HMDB sqlite to get HMDB-published InChIKey;
     compare against RDKit-from-SMILES → `id_disagreement_real.csv`
  3. Output files suffixed `_n30` to keep original Session 3 N=10 results
  4. Aggregate verdict thresholds (per user 2026-05-15):
       < 0.2          → STRONG GREEN
       0.2 - 0.4      → STABLE GREEN
       > 0.4          → PING USER(unlikely given 0.049 baseline)
  5. Per-batch breakdown also reported(看 seed 间 variance)

Run:
  /home/weiwentao/miniconda3/envs/mummichog_py310/bin/python \\
      data/investigation/scripts/gate1_toy_n30.py
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

WORKTREE = Path(__file__).resolve().parents[2].parent
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

OUTPUT_DIR = WORKTREE / "data" / "investigation" / "fig3_toy"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RAMP_DB_PATH = "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite"
HMDB_DB_PATH = "/data/weiwentao/llm_agent_metabolomics/hmdb.sqlite"
os.environ.setdefault("RAMP_DB_PATH", RAMP_DB_PATH)
BENCHMARK = WORKTREE / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks_v3.jsonl"

SEEDS = (42, 41, 40)
TASKS_PER_BATCH = 10


# ============================================================================
# Reuse helpers from gate1_toy.py(同模块)
# ============================================================================
from data.investigation.scripts.gate1_toy import (  # noqa: E402
    build_chebi_lookups,
    run_ramp_ora,
    run_sspa_ora,
    run_mummichog,
    normalize_name,
    jaccard,
)


# ============================================================================
# Multi-seed task selection(dedup across batches)
# ============================================================================


def _select_tasks_one_batch(all_tasks: list[dict], n: int, seed: int) -> list[dict]:
    """One batch: 2 per bucket × 5 buckets,seed varies."""
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for t in all_tasks:
        bckt = pd.Series([m.get("pathway_bucket", "other")
                          for m in t["differential_metabolites"]])
        dom = bckt.value_counts().index[0] if len(bckt) else "other"
        by_bucket[dom].append(t)

    rng = np.random.default_rng(seed)
    selected: list[dict] = []
    for bckt in ["lipid_metabolism", "central_metabolism",
                 "amino_acid_metabolism", "nucleotide_metabolism", "other"]:
        pool = by_bucket.get(bckt, [])
        if not pool:
            continue
        idxs = rng.choice(len(pool), size=min(2, len(pool)), replace=False)
        for i in idxs:
            selected.append(pool[i])
    if len(selected) < n:
        chosen = {t["task_id"] for t in selected}
        rest = [t for t in all_tasks if t["task_id"] not in chosen]
        rng.shuffle(rest)
        selected.extend(rest[: n - len(selected)])
    return selected[:n]


def select_tasks_multi(seeds=SEEDS, n_per_batch=TASKS_PER_BATCH) -> tuple[list[dict], dict[int, list[str]]]:
    """Run _select_tasks_one_batch per seed, dedupe across seeds by task_id.

    Returns (unique_tasks, batch_membership_dict).
    """
    tasks_all = [json.loads(line) for line in BENCHMARK.read_text().splitlines()]
    clean = [t for t in tasks_all if "RAMP_P_000052855" not in t["task_id"]]

    seen: dict[str, dict] = {}
    batch_membership: dict[int, list[str]] = {}
    for seed in seeds:
        batch = _select_tasks_one_batch(clean, n_per_batch, seed)
        batch_membership[seed] = [t["task_id"] for t in batch]
        for t in batch:
            seen.setdefault(t["task_id"], t)
    return list(seen.values()), batch_membership


# ============================================================================
# Real HMDB sqlite-based ID disagreement(R-NEW-16 partial fix)
# ============================================================================


def open_hmdb_conn():
    conn = sqlite3.connect(f"file:{HMDB_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def id_disagreement_real(task: dict, hmdb_conn: sqlite3.Connection) -> list[dict]:
    """Compare HMDB-sqlite-published InChIKey vs RDKit-from-SMILES.

    This is the R-NEW-16 partial fix:HMDB sqlite gives us THE official
    HMDB-distributed InChIKey(curated),vs RDKit's computed InChIKey from
    the SMILES field. If they disagree, that means HMDB's curation and our
    structure-derived ID don't match → real cross-source reconciliation issue.
    """
    from rdkit import Chem
    from rdkit.Chem import inchi
    rows = []
    for m in task["differential_metabolites"]:
        name = m.get("name", "")
        hmdb_id = m.get("hmdb_id")
        smiles = m.get("smiles", "") or ""
        benchmark_inchikey = m.get("inchikey", "") or ""

        # Real HMDB sqlite lookup
        hmdb_real_inchikey = ""
        hmdb_real_smiles = ""
        if hmdb_id:
            cur = hmdb_conn.execute(
                "SELECT inchikey, smiles FROM metabolites WHERE hmdb_id = ?",
                (hmdb_id,),
            )
            r = cur.fetchone()
            if r:
                hmdb_real_inchikey = r["inchikey"] or ""
                hmdb_real_smiles = r["smiles"] or ""

        # RDKit InChIKey from benchmark SMILES
        rdkit_inchikey_from_bench = ""
        if smiles:
            try:
                mol = Chem.MolFromSmiles(smiles)
                if mol is not None:
                    ikey = inchi.InchiToInchiKey(inchi.MolToInchi(mol))
                    rdkit_inchikey_from_bench = ikey or ""
            except Exception:
                pass

        # RDKit InChIKey from HMDB-published SMILES (if differs from benchmark SMILES)
        rdkit_inchikey_from_hmdb_smi = ""
        if hmdb_real_smiles and hmdb_real_smiles != smiles:
            try:
                mol = Chem.MolFromSmiles(hmdb_real_smiles)
                if mol is not None:
                    ikey = inchi.InchiToInchiKey(inchi.MolToInchi(mol))
                    rdkit_inchikey_from_hmdb_smi = ikey or ""
            except Exception:
                pass

        def block14(ik: str) -> str:
            return ik.split("-")[0] if ik else ""

        rows.append({
            "task_id": task["task_id"],
            "metabolite_name": name,
            "hmdb_id": hmdb_id or "",
            "benchmark_inchikey": benchmark_inchikey,
            "benchmark_block14": block14(benchmark_inchikey),
            "hmdb_real_inchikey": hmdb_real_inchikey,
            "hmdb_real_block14": block14(hmdb_real_inchikey),
            "rdkit_from_bench_smi_block14": block14(rdkit_inchikey_from_bench),
            "rdkit_from_hmdb_smi_block14": block14(rdkit_inchikey_from_hmdb_smi),
            "agree_hmdb_real_vs_rdkit_bench": (
                block14(hmdb_real_inchikey) == block14(rdkit_inchikey_from_bench)
                and bool(block14(hmdb_real_inchikey))
            ),
            "agree_hmdb_real_vs_benchmark": (
                block14(hmdb_real_inchikey) == block14(benchmark_inchikey)
                and bool(block14(hmdb_real_inchikey))
            ),
            "hmdb_lookup_found": bool(hmdb_real_inchikey),
        })
    return rows


# ============================================================================
# Main
# ============================================================================


def main():
    t0 = time.time()
    print(f"[gate1_toy_n30] start @ {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[gate1_toy_n30] output dir: {OUTPUT_DIR}")
    print()

    # Build ChEBI lookups
    print("[step 0] Building ChEBI lookups ...", flush=True)
    kegg2chebi, hmdb2chebi = build_chebi_lookups()
    print(f"  KEGG→ChEBI: {len(kegg2chebi)},  HMDB→ChEBI: {len(hmdb2chebi)}")

    # Multi-seed selection
    print(f"\n[step 1] Selecting tasks, seeds={SEEDS} ...", flush=True)
    tasks, batch_membership = select_tasks_multi(SEEDS, TASKS_PER_BATCH)
    print(f"  Unique tasks after dedup: {len(tasks)}")
    for seed, tids in batch_membership.items():
        print(f"    seed={seed}: {len(tids)} tasks")
    print(f"  Total cross-batch unique: {len(tasks)} (target ~30)")

    # Open HMDB conn
    print(f"\n[step 2] Opening real HMDB sqlite ({HMDB_DB_PATH}) ...", flush=True)
    hmdb_conn = open_hmdb_conn()

    # Run all 3 PA + ID disagreement (real)
    pa_results = {"ramp": {}, "sspa": {}, "mummichog": {}}
    id_real_rows = []
    n_failures = {"ramp": 0, "sspa": 0, "mummichog": 0}

    for ti, task in enumerate(tasks):
        tid = task["task_id"]
        print(f"\n[task {ti+1}/{len(tasks)}] {tid[:60]}", flush=True)
        for method, runner in [("ramp", lambda t: run_ramp_ora(t)),
                                ("sspa", lambda t: run_sspa_ora(t, kegg2chebi, hmdb2chebi)),
                                ("mummichog", lambda t: run_mummichog(t))]:
            ts = time.time()
            try:
                pa_results[method][tid] = runner(task)
                n_p = len(pa_results[method][tid])
                if n_p == 0:
                    n_failures[method] += 1
                print(f"  {method:9s}: {n_p:2d} pathways  ({time.time()-ts:.1f}s)")
            except Exception as e:
                print(f"  {method:9s}: ❌ {type(e).__name__}: {e}")
                pa_results[method][tid] = []
                n_failures[method] += 1
        id_real_rows.extend(id_disagreement_real(task, hmdb_conn))

    hmdb_conn.close()

    # Stop-condition check: any PA method failed all tasks?
    halt = False
    for method, nfail in n_failures.items():
        if nfail == len(tasks):
            print(f"\n❌ STOP CONDITION: {method} failed all {len(tasks)} tasks", flush=True)
            halt = True
    if halt:
        print("HALT — Session 4 stop condition triggered, report shows.", flush=True)
        return

    # Aggregate Jaccard
    print("\n[step 3] Computing aggregate Jaccard ...", flush=True)
    methods = ["ramp", "sspa", "mummichog"]
    per_task = []
    aggregate = {}
    aggregate_by_batch = defaultdict(dict)  # batch_seed → method-pair → list of Jaccards

    task_id_to_seeds: dict[str, list[int]] = defaultdict(list)
    for seed, tids in batch_membership.items():
        for tid in tids:
            task_id_to_seeds[tid].append(seed)

    for m1 in methods:
        for m2 in methods:
            jacs = []
            for tid in (t["task_id"] for t in tasks):
                set1 = {normalize_name(p["pathway_name"]) for p in pa_results[m1].get(tid, [])}
                set2 = {normalize_name(p["pathway_name"]) for p in pa_results[m2].get(tid, [])}
                set1.discard(""); set2.discard("")
                if not set1 or not set2:
                    continue
                j = jaccard(set1, set2)
                jacs.append(j)
                per_task.append({"task_id": tid, "method_a": m1, "method_b": m2,
                                 "jaccard": j, "n_a": len(set1), "n_b": len(set2),
                                 "from_seeds": ",".join(str(s) for s in task_id_to_seeds[tid])})
                # Per-batch breakdown
                for s in task_id_to_seeds[tid]:
                    aggregate_by_batch[s].setdefault((m1, m2), []).append(j)
            aggregate[(m1, m2)] = float(np.mean(jacs)) if jacs else float("nan")
            print(f"  {m1:10s} × {m2:10s}  mean={aggregate[(m1, m2)]:.4f}  n={len(jacs)}")

    # Per-batch summary
    print("\n[step 4] Per-batch mean off-diagonal Jaccard ...", flush=True)
    for seed in SEEDS:
        batch_jaccs = []
        for (m1, m2), js in aggregate_by_batch[seed].items():
            if m1 < m2 and js:
                batch_jaccs.append(float(np.mean(js)))
        mean_batch = float(np.mean(batch_jaccs)) if batch_jaccs else float("nan")
        print(f"  seed={seed} mean off-diagonal Jaccard: {mean_batch:.4f}")

    # ID disagreement summary
    df_id_real = pd.DataFrame(id_real_rows)
    n_total = len(df_id_real)
    n_lookup_found = int(df_id_real["hmdb_lookup_found"].sum()) if n_total else 0
    n_disagree_block14_vs_rdkit = int((~df_id_real["agree_hmdb_real_vs_rdkit_bench"]).sum()) if n_total else 0
    n_disagree_block14_vs_bench = int((~df_id_real["agree_hmdb_real_vs_benchmark"]).sum()) if n_total else 0

    # Aggregate cross-method Jaccard
    cross = [aggregate[(m1, m2)] for m1 in methods for m2 in methods if m1 < m2]
    cross = [j for j in cross if not np.isnan(j)]
    mean_cross = float(np.mean(cross)) if cross else float("nan")

    # Verdict tier
    if np.isnan(mean_cross):
        verdict = "ERROR"
    elif mean_cross < 0.2:
        verdict = "STRONG GREEN"
    elif mean_cross < 0.4:
        verdict = "STABLE GREEN"
    elif mean_cross <= 0.6:
        verdict = "BORDERLINE"
    else:
        verdict = "RED"

    # Save outputs
    print("\n[step 5] Saving N=30 outputs ...", flush=True)
    df_jac = pd.DataFrame(per_task)
    df_jac.to_csv(OUTPUT_DIR / "jaccard_data_n30.csv", index=False)
    print(f"  → {OUTPUT_DIR / 'jaccard_data_n30.csv'} ({len(df_jac)} rows)")

    df_id_real.to_csv(OUTPUT_DIR / "id_disagreement_real.csv", index=False)
    print(f"  → {OUTPUT_DIR / 'id_disagreement_real.csv'} ({n_total} rows)")

    # Plot N=30 heatmap
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n_methods = len(methods)
    M = np.full((n_methods, n_methods), np.nan)
    for i, m1 in enumerate(methods):
        for j, m2 in enumerate(methods):
            M[i, j] = aggregate.get((m1, m2), float("nan"))
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(M, cmap="viridis", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(n_methods)); ax.set_xticklabels(methods, rotation=15)
    ax.set_yticks(range(n_methods)); ax.set_yticklabels(methods)
    for i in range(n_methods):
        for j in range(n_methods):
            txt = f"{M[i,j]:.3f}" if not np.isnan(M[i,j]) else "—"
            color = "white" if (np.isnan(M[i,j]) or M[i,j] < 0.5) else "black"
            ax.text(j, i, txt, ha="center", va="center", color=color, fontsize=11)
    ax.set_title(f"Cross-method top-10 pathway Jaccard (N={len(tasks)})\n"
                 f"seeds={SEEDS}  mean off-diag={mean_cross:.3f}  verdict={verdict}")
    plt.colorbar(im, ax=ax, label="Jaccard")
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "jaccard_matrix_n30.png", dpi=150)
    plt.close(fig)
    print(f"  → {OUTPUT_DIR / 'jaccard_matrix_n30.png'}")

    # Summary JSON
    summary = {
        "n_tasks_unique": len(tasks),
        "n_tasks_target": len(SEEDS) * TASKS_PER_BATCH,
        "seeds": list(SEEDS),
        "task_ids": [t["task_id"] for t in tasks],
        "batch_membership": batch_membership,
        "methods": methods,
        "aggregate_jaccard": {f"{m1}__{m2}": aggregate[(m1, m2)]
                              for m1 in methods for m2 in methods},
        "mean_off_diagonal_jaccard": mean_cross,
        "n_failures_per_method": n_failures,
        "id_disagreement_real": {
            "n_metabolites_total": int(n_total),
            "n_hmdb_lookup_found": int(n_lookup_found),
            "n_hmdb_lookup_miss": int(n_total - n_lookup_found),
            "n_disagree_block14_hmdb_real_vs_rdkit_bench": int(n_disagree_block14_vs_rdkit),
            "n_disagree_block14_hmdb_real_vs_benchmark_field": int(n_disagree_block14_vs_bench),
        },
        "gate1_verdict": verdict,
        "wall_time_sec": time.time() - t0,
    }
    (OUTPUT_DIR / "summary_n30.json").write_text(json.dumps(summary, indent=2))
    print(f"  → {OUTPUT_DIR / 'summary_n30.json'}")

    print(f"\n{'='*70}")
    print(f"GATE 1 VERDICT (N=30): {verdict}")
    print(f"  Mean cross-method Jaccard: {mean_cross:.4f}")
    print(f"  Wall time: {time.time() - t0:.1f}s")
    print()
    print(f"  ID disagreement (R-NEW-16 partial fix on real HMDB sqlite):")
    print(f"    n_metabolites: {n_total}")
    print(f"    HMDB sqlite lookup hit rate: {n_lookup_found}/{n_total} ({100*n_lookup_found/max(1,n_total):.1f}%)")
    print(f"    HMDB-real vs RDKit-from-bench-SMILES block14 disagree: "
          f"{n_disagree_block14_vs_rdkit}/{n_total} "
          f"({100*n_disagree_block14_vs_rdkit/max(1,n_total):.1f}%)")
    print(f"    HMDB-real vs benchmark.inchikey field block14 disagree: "
          f"{n_disagree_block14_vs_bench}/{n_total} "
          f"({100*n_disagree_block14_vs_bench/max(1,n_total):.1f}%)")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
