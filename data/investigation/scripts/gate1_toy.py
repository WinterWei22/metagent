"""§8 W1 Gate 1 toy data — cross-method pathway analysis Jaccard + ID disagreement.

Pipeline:
  1. Select 10 tasks (2 per bucket × 5 buckets,避开 RAMP_P_000052855)
  2. RaMP ORA(HMDB IDs)        → top-10 pathway names per task
  3. sspa ORA(ChEBI IDs,synthetic 5-case + 5-ctrl matrix) → top-10
  4. mummichog(m/z from exact_mass + p-val table)         → top-10
  5. HMDB-direct InChIKey vs RDKit-from-SMILES InChIKey block14 → disagreement
  6. Pairwise Jaccard between PA methods(normalized pathway name)
  7. Output: heatmap PNG + 2 CSV + Gate 1 颜色判定

Run:
  /home/weiwentao/miniconda3/envs/mummichog_py310/bin/python data/investigation/scripts/gate1_toy.py
"""
from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

WORKTREE = Path(__file__).resolve().parents[2].parent  # → metagent_day1_v5_investigation
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

OUTPUT_DIR = WORKTREE / "data" / "investigation" / "fig3_toy"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RAMP_DB_PATH = "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite"
os.environ.setdefault("RAMP_DB_PATH", RAMP_DB_PATH)

BENCHMARK = WORKTREE / "data" / "benchmark" / "sub6" / "sub6b_mammalian_tasks_v3.jsonl"

# ============================================================================
# 0. ChEBI lookup helper(KEGG cpd / HMDB → ChEBI ID)
# ============================================================================


def build_chebi_lookups() -> tuple[dict[str, str], dict[str, str]]:
    """Return (kegg_to_chebi, hmdb_to_chebi) maps from ChEBI rel251 database_accession.tsv."""
    chebi_tsv = WORKTREE / "data" / "investigation" / "chebi_cache" / "database_accession.tsv.gz"
    if not chebi_tsv.exists():
        raise FileNotFoundError(f"ChEBI database_accession.tsv.gz not found at {chebi_tsv}")
    kegg2chebi: dict[str, str] = {}
    hmdb2chebi: dict[str, str] = {}
    # Source IDs (confirmed in Session 2):  45 = KEGG COMPOUND, 35 = HMDB
    with gzip.open(chebi_tsv, "rt") as f:
        header = f.readline().rstrip().split("\t")
        # cols: id, compound_id, accession_number, type, status_id, source_id
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 6:
                continue
            compound_id, accession, _ttype, _status, source_id = cols[1], cols[2], cols[3], cols[4], cols[5]
            chebi = f"CHEBI:{compound_id}"
            if source_id == "45":      # KEGG COMPOUND
                # Only keep first hit (avoid overwrite by less canonical)
                kegg2chebi.setdefault(accession, chebi)
            elif source_id == "35":    # HMDB
                hmdb2chebi.setdefault(accession, chebi)
    return kegg2chebi, hmdb2chebi


# ============================================================================
# 1. Task selection
# ============================================================================


def select_tasks(n: int = 10, seed: int = 42) -> list[dict]:
    """Select n diverse tasks: 2 per bucket × 5 buckets, avoid RAMP_P_000052855."""
    tasks = [json.loads(line) for line in BENCHMARK.read_text().splitlines()]
    clean = [t for t in tasks if "RAMP_P_000052855" not in t["task_id"]]

    # Group tasks by dominant pathway_bucket(majority among differential_metabolites)
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for t in clean:
        bckt = pd.Series([m.get("pathway_bucket", "other") for m in t["differential_metabolites"]])
        dom = bckt.value_counts().index[0] if len(bckt) else "other"
        by_bucket[dom].append(t)

    rng = np.random.default_rng(seed)
    selected: list[dict] = []
    target_buckets = ["lipid_metabolism", "central_metabolism",
                      "amino_acid_metabolism", "nucleotide_metabolism", "other"]
    for bckt in target_buckets:
        pool = by_bucket.get(bckt, [])
        if not pool:
            continue
        idxs = rng.choice(len(pool), size=min(2, len(pool)), replace=False)
        for i in idxs:
            selected.append(pool[i])
    if len(selected) < n:
        # Pad from any remaining
        chosen_ids = {t["task_id"] for t in selected}
        rest = [t for t in clean if t["task_id"] not in chosen_ids]
        rng.shuffle(rest)
        selected.extend(rest[: n - len(selected)])
    return selected[:n]


# ============================================================================
# 2. RaMP ORA
# ============================================================================


def run_ramp_ora(task: dict) -> list[dict]:
    """Return top-10 pathways via RaMP hypergeometric ORA (HMDB IDs)."""
    from tools.benchmark.sub6.ramp_enrichment import compute_enrichment
    mets = task["differential_metabolites"]
    hmdb_ids = [m["hmdb_id"] for m in mets if m.get("hmdb_id")]
    if not hmdb_ids:
        return []
    report = compute_enrichment(hmdb_ids, id_type="hmdb", top_n=10,
                                ramp_db_path=RAMP_DB_PATH)
    return [{"pathway_id": p.pathway_id, "pathway_name": p.pathway_name,
             "p_value": p.p_value, "fdr": p.fdr, "source": p.pathway_source}
            for p in report.top_pathways]


# ============================================================================
# 3. sspa ORA(synthetic 5-case + 5-ctrl matrix)
# ============================================================================


_SSPA_PATHWAY_DF_CACHE = None


def _sspa_pathways():
    global _SSPA_PATHWAY_DF_CACHE
    if _SSPA_PATHWAY_DF_CACHE is None:
        import sspa
        print("  [sspa] Loading Reactome Homo sapiens pathways ...", flush=True)
        _SSPA_PATHWAY_DF_CACHE = sspa.process_reactome(organism="Homo sapiens")
        print(f"  [sspa] Pathways: {_SSPA_PATHWAY_DF_CACHE.shape}", flush=True)
    return _SSPA_PATHWAY_DF_CACHE


def run_sspa_ora(task: dict, kegg2chebi: dict, hmdb2chebi: dict) -> list[dict]:
    """sspa ORA via synthetic 5-case + 5-ctrl ChEBI matrix.

    FIX 2026-05-15: sspa pathway_df cells are INT(not str)— ChEBI numeric ID.
    Convert all to str for consistent matching.
    """
    import sspa
    pathway_df = _sspa_pathways()

    # Pathway df cell values are int ChEBI IDs(e.g. 30616);column 'Pathway_name' is text.
    # Build universe of all compound IDs as strings.
    pathway_dict = {}
    for pid, row in pathway_df.iterrows():
        s = set()
        for c, v in row.items():
            if c == "Pathway_name":
                continue
            if pd.isna(v):
                continue
            s.add(str(v).strip())  # int → str
        pathway_dict[pid] = s
    all_chebi = sorted({c for compounds in pathway_dict.values() for c in compounds if c})

    # Resolve task metabolites → ChEBI numeric str
    diff_chebi: list[str] = []
    for m in task["differential_metabolites"]:
        chebi = None
        if m.get("kegg_id") and m["kegg_id"] in kegg2chebi:
            chebi = kegg2chebi[m["kegg_id"]]
        elif m.get("hmdb_id") and m["hmdb_id"] in hmdb2chebi:
            chebi = hmdb2chebi[m["hmdb_id"]]
        if chebi:
            diff_chebi.append(chebi.replace("CHEBI:", ""))

    if not diff_chebi:
        return []

    # Convert pathway_df cells to str for sspa_ora's internal matching
    pathway_df_str = pathway_df.copy()
    for col in pathway_df_str.columns:
        if col == "Pathway_name":
            continue
        pathway_df_str[col] = pathway_df_str[col].apply(
            lambda v: str(int(v)) if pd.notna(v) else v
        )

    n_case, n_ctrl = 5, 5
    rng = np.random.default_rng(42)
    mat = pd.DataFrame(
        rng.normal(loc=1.0, scale=0.1, size=(n_case + n_ctrl, len(all_chebi))),
        columns=all_chebi,
    )
    # Bump differential metabolites in case rows
    for cid in diff_chebi:
        if cid in mat.columns:
            mat.loc[: n_case - 1, cid] = rng.normal(loc=5.0, scale=0.5, size=n_case)
    metadata = pd.Series(["case"] * n_case + ["ctrl"] * n_ctrl, index=mat.index)
    try:
        ora = sspa.sspa_ora(mat, metadata, pathway_df_str,
                            DA_cutoff=0.05, DA_testtype="ttest")
        result = ora.over_representation_analysis()
    except Exception as e:
        print(f"  [sspa] task {task['task_id'][:50]}... ORA failed: {type(e).__name__}: {e}",
              flush=True)
        return []
    # Result is a DataFrame with columns including 'ID' / 'P-value' / 'Hits' / 'Pathway_name'
    result = result.sort_values("P-value").head(10)
    out = []
    for _, row in result.iterrows():
        out.append({"pathway_id": str(row.get("ID", "")),
                    "pathway_name": str(row.get("Pathway_name", row.get("ID", ""))),
                    "p_value": float(row.get("P-value", 1.0)),
                    "fdr": float(row.get("P-adjust", 1.0)) if "P-adjust" in row else None,
                    "source": "reactome"})
    return out


# ============================================================================
# 4. Mummichog
# ============================================================================


def run_mummichog(task: dict) -> list[dict]:
    """Synthesize m/z + p-val table, run mummichog CLI, parse top-10 pathways."""
    mets = task["differential_metabolites"]
    # Build full m/z table: differential = significant (small p), 50 random background
    # mummichog needs background, so we synthesize ~200 background m/z (random masses)
    rng = np.random.default_rng(seed=hash(task["task_id"]) % (2**32))

    rows = []
    # Significant: differential metabolites with M+H+ adduct (+ 1.00784)
    for m in mets:
        emass = m.get("exact_mass")
        if emass is None or emass < 50:
            continue
        mz_pos = emass + 1.00784  # M+H[1+]
        rt = float(rng.uniform(30, 600))
        rows.append((mz_pos, rt, 0.001, 4.5, f"diff_{m['name'][:20]}"))
    # Background: 250 random "non-significant" features at typical mass range
    for i in range(250):
        mz = float(rng.uniform(80, 800))
        rt = float(rng.uniform(30, 600))
        rows.append((mz, rt, float(rng.uniform(0.1, 0.95)), float(rng.normal(0, 1)),
                     f"bg_{i}"))

    with tempfile.TemporaryDirectory(prefix="mcg_toy_") as tmpdir:
        infile = Path(tmpdir) / "input.tsv"
        with infile.open("w") as f:
            f.write("m/z\tretention_time\tp-value\tt-score\tcustom_id\n")
            for mz, rt, p, t, cid in rows:
                f.write(f"{mz:.4f}\t{rt:.1f}\t{p:.6g}\t{t:.2f}\t{cid}\n")
        outdir = Path(tmpdir) / "mcg_out"
        outdir.mkdir()
        try:
            result = subprocess.run(
                ["/home/weiwentao/miniconda3/envs/mummichog_py310/bin/python",
                 "-m", "mummichog.main",
                 "-f", str(infile), "-o", "mcg_run", "-m", "positive",
                 "-p", "20", "-u", "10", "-z", "True",
                 "-k", str(outdir)],
                capture_output=True, text=True, timeout=180, cwd=tmpdir,
            )
        except subprocess.TimeoutExpired:
            print(f"  [mummichog] timeout on {task['task_id'][:50]}", flush=True)
            return []
        if result.returncode != 0:
            print(f"  [mummichog] exit {result.returncode}: {result.stderr[:200]}",
                  flush=True)
            return []
        # Find the pathway TSV in <timestamp>.mcg_run/tables/
        candidates = list(outdir.glob("*.mcg_run/tables/mcg_pathwayanalysis_mcg_run.tsv"))
        if not candidates:
            candidates = list(outdir.rglob("mcg_pathwayanalysis_*.tsv"))
        if not candidates:
            print(f"  [mummichog] no pathway tsv in {outdir}", flush=True)
            return []
        df = pd.read_csv(candidates[0], sep="\t")
        df = df.sort_values("p-value").head(10)
        out = []
        for _, row in df.iterrows():
            out.append({"pathway_id": str(row.get("pathway", "")),
                        "pathway_name": str(row.get("pathway", "")),
                        "p_value": float(row.get("p-value", 1.0)),
                        "fdr": None,
                        "source": "human_mfn"})
        return out


# ============================================================================
# 5. ID mapper disagreement
# ============================================================================


def id_disagreement(task: dict) -> list[dict]:
    """Compare HMDB-direct inchikey (precomputed) vs RDKit-from-SMILES."""
    from rdkit import Chem
    from rdkit.Chem import inchi
    rows = []
    for m in task["differential_metabolites"]:
        name = m.get("name", "")
        hmdb_inchikey = m.get("inchikey", "") or ""
        hmdb_block14 = hmdb_inchikey.split("-")[0] if hmdb_inchikey else ""

        # RDKit from SMILES
        smiles = m.get("smiles", "") or ""
        rdkit_inchikey, rdkit_block14 = "", ""
        if smiles:
            try:
                mol = Chem.MolFromSmiles(smiles)
                if mol is not None:
                    ikey = inchi.InchiToInchiKey(inchi.MolToInchi(mol))
                    rdkit_inchikey = ikey or ""
                    rdkit_block14 = rdkit_inchikey.split("-")[0] if rdkit_inchikey else ""
            except Exception:
                pass

        agree_full = (hmdb_inchikey == rdkit_inchikey and bool(hmdb_inchikey))
        agree_block14 = (hmdb_block14 == rdkit_block14 and bool(hmdb_block14))

        rows.append({
            "task_id": task["task_id"],
            "metabolite_name": name,
            "hmdb_inchikey": hmdb_inchikey,
            "rdkit_inchikey": rdkit_inchikey,
            "hmdb_block14": hmdb_block14,
            "rdkit_block14": rdkit_block14,
            "agree_full": agree_full,
            "agree_block14": agree_block14,
        })
    return rows


# ============================================================================
# 6. Pathway name normalization + Jaccard
# ============================================================================

_STOPWORDS = frozenset({"and", "of", "the", "in", "for", "to", "via", "with"})


def normalize_name(name: str) -> str:
    """Normalize pathway name for cross-method matching.

    Lowercase, strip punctuation, remove stopwords, sort tokens, join.
    'Glycolysis / Gluconeogenesis' → 'glycolysis gluconeogenesis'
    """
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    tokens = [t for t in s.split() if t and t not in _STOPWORDS]
    return " ".join(sorted(tokens))


def jaccard(set_a: set[str], set_b: set[str]) -> float:
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 1.0
    return len(set_a & set_b) / len(union)


# ============================================================================
# Main pipeline
# ============================================================================


def main():
    t0 = time.time()
    print(f"[gate1_toy] start @ {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[gate1_toy] output dir: {OUTPUT_DIR}")
    print()

    # Build ChEBI lookups
    print("[step 0] Building ChEBI lookups ...", flush=True)
    kegg2chebi, hmdb2chebi = build_chebi_lookups()
    print(f"  KEGG→ChEBI: {len(kegg2chebi)} entries")
    print(f"  HMDB→ChEBI: {len(hmdb2chebi)} entries")

    # Select tasks
    print("\n[step 1] Selecting 10 tasks ...", flush=True)
    tasks = select_tasks(n=10, seed=42)
    print(f"  Selected {len(tasks)} tasks:")
    for i, t in enumerate(tasks):
        n_mets = len(t["differential_metabolites"])
        buckets = [m.get("pathway_bucket", "?") for m in t["differential_metabolites"]]
        dom = pd.Series(buckets).value_counts().index[0]
        print(f"    [{i}] {t['task_id'][:60]} n_met={n_mets} bucket={dom}")

    # Run all 3 PA methods + ID disagreement
    pa_results: dict[str, dict[str, list[dict]]] = {}  # method → task_id → [pathways]
    id_rows = []

    for method in ["ramp", "sspa", "mummichog"]:
        pa_results[method] = {}

    for ti, task in enumerate(tasks):
        tid = task["task_id"]
        print(f"\n[task {ti+1}/{len(tasks)}] {tid[:60]}", flush=True)
        # RaMP
        t_start = time.time()
        try:
            pa_results["ramp"][tid] = run_ramp_ora(task)
            print(f"  ramp:      {len(pa_results['ramp'][tid])} pathways  "
                  f"({time.time() - t_start:.1f}s)")
        except Exception as e:
            print(f"  ramp:      ❌ {type(e).__name__}: {e}")
            pa_results["ramp"][tid] = []
        # sspa
        t_start = time.time()
        try:
            pa_results["sspa"][tid] = run_sspa_ora(task, kegg2chebi, hmdb2chebi)
            print(f"  sspa:      {len(pa_results['sspa'][tid])} pathways  "
                  f"({time.time() - t_start:.1f}s)")
        except Exception as e:
            print(f"  sspa:      ❌ {type(e).__name__}: {e}")
            pa_results["sspa"][tid] = []
        # mummichog
        t_start = time.time()
        try:
            pa_results["mummichog"][tid] = run_mummichog(task)
            print(f"  mummichog: {len(pa_results['mummichog'][tid])} pathways  "
                  f"({time.time() - t_start:.1f}s)")
        except Exception as e:
            print(f"  mummichog: ❌ {type(e).__name__}: {e}")
            pa_results["mummichog"][tid] = []
        # ID disagreement
        id_rows.extend(id_disagreement(task))

    # Compute Jaccard
    print("\n[step 6] Computing Jaccard ...", flush=True)
    methods = ["ramp", "sspa", "mummichog"]
    per_task = []  # rows: task × method_pair Jaccard
    aggregate = {}
    for m1 in methods:
        for m2 in methods:
            jacs = []
            for tid in (t["task_id"] for t in tasks):
                set1 = {normalize_name(p["pathway_name"]) for p in pa_results[m1].get(tid, [])}
                set2 = {normalize_name(p["pathway_name"]) for p in pa_results[m2].get(tid, [])}
                # Drop empty-string pathways
                set1.discard("")
                set2.discard("")
                if not set1 or not set2:
                    continue  # skip task if either method gave 0 results
                j = jaccard(set1, set2)
                jacs.append(j)
                per_task.append({"task_id": tid, "method_a": m1, "method_b": m2,
                                 "jaccard": j, "n_a": len(set1), "n_b": len(set2)})
            aggregate[(m1, m2)] = float(np.mean(jacs)) if jacs else float("nan")
            print(f"  {m1:10s} × {m2:10s}  mean Jaccard = {aggregate[(m1, m2)]:.3f}  "
                  f"(n_tasks={len(jacs)})")

    # Save CSVs
    print("\n[step 7] Saving CSVs ...", flush=True)
    df_jac = pd.DataFrame(per_task)
    df_jac.to_csv(OUTPUT_DIR / "jaccard_data.csv", index=False)
    print(f"  → {OUTPUT_DIR / 'jaccard_data.csv'} ({len(df_jac)} rows)")

    df_id = pd.DataFrame(id_rows)
    df_id.to_csv(OUTPUT_DIR / "id_disagreement.csv", index=False)
    print(f"  → {OUTPUT_DIR / 'id_disagreement.csv'} ({len(df_id)} rows)")

    # Cross-method aggregate Jaccard summary (excluding diagonal)
    cross_jaccs = [aggregate[(m1, m2)] for m1 in methods for m2 in methods if m1 < m2]
    cross_jaccs = [j for j in cross_jaccs if not np.isnan(j)]
    mean_cross = float(np.mean(cross_jaccs)) if cross_jaccs else float("nan")

    # ID mapper disagreement rate
    n_total = len(df_id)
    n_disagree_block14 = (~df_id["agree_block14"]).sum() if n_total else 0
    disagreement_rate = n_disagree_block14 / n_total if n_total else float("nan")

    # Plot heatmap
    print("\n[step 8] Plotting heatmap ...", flush=True)
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
            txt = f"{M[i,j]:.2f}" if not np.isnan(M[i,j]) else "—"
            color = "white" if (np.isnan(M[i,j]) or M[i,j] < 0.5) else "black"
            ax.text(j, i, txt, ha="center", va="center", color=color, fontsize=11)
    ax.set_title(f"Cross-method top-10 pathway Jaccard\n"
                 f"({len(tasks)} tasks, normalized pathway name match)\n"
                 f"mean off-diagonal = {mean_cross:.3f}")
    plt.colorbar(im, ax=ax, label="Jaccard")
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "jaccard_matrix.png", dpi=150)
    plt.close(fig)
    print(f"  → {OUTPUT_DIR / 'jaccard_matrix.png'}")

    # Gate 1 verdict
    if np.isnan(mean_cross):
        color = "ERROR"
    elif mean_cross < 0.4:
        color = "GREEN"
    elif mean_cross <= 0.6:
        color = "BORDERLINE"
    else:
        color = "RED"

    summary = {
        "n_tasks": len(tasks),
        "task_ids": [t["task_id"] for t in tasks],
        "methods": methods,
        "aggregate_jaccard": {f"{m1}__{m2}": aggregate[(m1, m2)]
                              for m1 in methods for m2 in methods},
        "mean_off_diagonal_jaccard": mean_cross,
        "id_disagreement_rate_block14": disagreement_rate,
        "n_metabolites_total": n_total,
        "n_metabolites_disagree_block14": int(n_disagree_block14),
        "gate1_verdict": color,
        "wall_time_sec": time.time() - t0,
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"  → {OUTPUT_DIR / 'summary.json'}")

    print(f"\n{'='*60}")
    print(f"GATE 1 VERDICT: {color}")
    print(f"  Mean cross-method Jaccard: {mean_cross:.3f}")
    print(f"  ID disagreement rate (block14): {disagreement_rate:.1%}")
    print(f"  Wall time: {time.time() - t0:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
