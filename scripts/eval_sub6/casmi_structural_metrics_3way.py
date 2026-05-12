"""Phase 6.7 — 3-way Tanimoto + MCS atom-fraction across CASMI configs.

Adds llm_reranker config alongside msclip_only + weighted from Phase 6.6.
Reuses RDKit Morgan-2 fingerprint + rdFMCS atom-fraction (same as Phase 6.6
structural_metrics.py). Pairwise paired Wilcoxon signed-rank.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import AllChem, rdFMCS
from scipy.stats import wilcoxon

RDLogger.DisableLog("rdApp.*")
logger = logging.getLogger(__name__)


def _fp(mol):
    return AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048)


def _tan(p, g):
    if not p or not g:
        return None
    pm = Chem.MolFromSmiles(p); gm = Chem.MolFromSmiles(g)
    if pm is None or gm is None:
        return None
    return float(DataStructs.TanimotoSimilarity(_fp(pm), _fp(gm)))


def _mcs(p, g, timeout_s=30):
    if not p or not g:
        return None
    pm = Chem.MolFromSmiles(p); gm = Chem.MolFromSmiles(g)
    if pm is None or gm is None:
        return None
    denom = max(pm.GetNumAtoms(), gm.GetNumAtoms(), 1)
    try:
        r = rdFMCS.FindMCS([pm, gm], timeout=timeout_s)
    except Exception:
        return None
    if r.canceled or r.numAtoms == 0:
        return None
    return float(r.numAtoms / denom)


def _load(path: Path) -> dict[str, dict]:
    return {json.loads(l)["spectrum_id"]: json.loads(l) for l in path.open()}


CONFIGS = [
    ("msclip_only",  "2022_msclip_only"),
    ("weighted",     "2022_conditional"),
    ("llm_reranker", "2022_llm_reranker"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("data/eval/casmi"))
    ap.add_argument("--out", type=Path, default=Path("data/paper_figures"))
    ap.add_argument("--mcs-timeout-s", type=int, default=30)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    data = {name: _load(args.root / sub / "casmi_identifications.jsonl") for name, sub in CONFIGS}
    sids = sorted(set.intersection(*[set(d) for d in data.values()]))
    logger.info("paired across 3 configs: %d spectra", len(sids))

    rows = []
    for i, s in enumerate(sids):
        gt = data["msclip_only"][s].get("gt_smiles")
        row = {"spectrum_id": s, "formula": data["msclip_only"][s].get("casmi_formula"),
               "gt_smiles": gt}
        for name, _ in CONFIGS:
            p = data[name][s].get("predicted_smiles")
            row[f"{name}_tan"] = _tan(p, gt)
            row[f"{name}_mcs"] = _mcs(p, gt, timeout_s=args.mcs_timeout_s)
        rows.append(row)
        if (i + 1) % 25 == 0:
            logger.info("processed %d/%d", i + 1, len(sids))

    out_per = args.out / "phase6_7_structural_metrics_3way.csv"
    with out_per.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    logger.info("wrote per-spec %s", out_per)

    def _stats(name, vals):
        import statistics as st
        vals = [v for v in vals if v is not None]
        if not vals:
            return {"metric": name, "n": 0}
        sorted_vals = sorted(vals)
        return {
            "metric": name, "n": len(vals),
            "mean": round(sum(vals)/len(vals), 4),
            "median": round(st.median(vals), 4),
            "p25": round(sorted_vals[int(0.25*len(vals))], 4),
            "p75": round(sorted_vals[int(0.75*len(vals))], 4),
            "p90": round(sorted_vals[int(0.90*len(vals))], 4),
            "max": round(max(vals), 4),
        }

    summary = []
    for name, _ in CONFIGS:
        summary.append(_stats(f"tanimoto_{name}", [r[f"{name}_tan"] for r in rows]))
        summary.append(_stats(f"mcs_frac_{name}", [r[f"{name}_mcs"] for r in rows]))

    out_sum = args.out / "phase6_7_structural_summary.csv"
    with out_sum.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader(); w.writerows(summary)

    # Pairwise paired Wilcoxon for both metrics — focus on LLM comparisons.
    wilcoxon_rows = []
    pairs = [("llm_reranker", "msclip_only"), ("llm_reranker", "weighted"),
             ("weighted", "msclip_only")]
    for metric in ("tan", "mcs"):
        for A, B in pairs:
            pairs_v = [(r[f"{A}_{metric}"], r[f"{B}_{metric}"]) for r in rows
                       if r[f"{A}_{metric}"] is not None and r[f"{B}_{metric}"] is not None]
            if not pairs_v:
                continue
            diffs = [a - b for a, b in pairs_v]  # A − B (positive means A's metric higher)
            n_pos = sum(1 for d in diffs if d > 0)
            n_neg = sum(1 for d in diffs if d < 0)
            n_zero = sum(1 for d in diffs if d == 0)
            if n_pos + n_neg == 0:
                p = 1.0
            else:
                p = float(wilcoxon(diffs, zero_method="wilcox", alternative="two-sided").pvalue)
            wilcoxon_rows.append({
                "metric": "tanimoto" if metric == "tan" else "mcs_frac",
                "comparison": f"{A} vs {B}",
                "n_paired": len(pairs_v),
                "n_A_better": n_pos,
                "n_B_better": n_neg,
                "n_tied": n_zero,
                "mean_AminusB": round(sum(diffs)/len(diffs), 5),
                "p_wilcoxon": round(p, 4) if p >= 1e-4 else f"{p:.2e}",
            })
    out_wil = args.out / "phase6_7_structural_wilcoxon.csv"
    with out_wil.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(wilcoxon_rows[0].keys()))
        w.writeheader(); w.writerows(wilcoxon_rows)

    print("=" * 70)
    print("Per-config distributions:")
    for r in summary:
        if r.get("n"):
            print(f"  {r['metric']:<28} n={r['n']:>3}  mean={r['mean']:.4f}  median={r['median']:.4f}  p90={r['p90']:.4f}")
    print("\nPairwise paired Wilcoxon (A − B):")
    for r in wilcoxon_rows:
        print(f"  {r['metric']:<10} {r['comparison']:<32} n={r['n_paired']}  "
              f"A>B={r['n_A_better']}  A<B={r['n_B_better']}  ties={r['n_tied']}  "
              f"mean Δ={r['mean_AminusB']:+.4f}  p={r['p_wilcoxon']}")
    print(f"\nwrote: {out_per}, {out_sum}, {out_wil}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
