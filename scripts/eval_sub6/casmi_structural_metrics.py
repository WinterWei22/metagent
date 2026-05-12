"""Phase 6.6 — soft structural metrics on CASMI predictions.

Reads the same D2 (msclip-only) and D3 (conditional) per-spec JSONL files
that ``casmi_significance.py`` consumes, computes for each (predicted_smiles,
gt_smiles) pair:

  - Tanimoto similarity over Morgan radius-2, 2048-bit fingerprints
  - MCS atom-fraction = (# atoms in maximum common substructure) /
      max(# atoms in predicted, # atoms in GT)
      [RDKit ``rdFMCS`` with a 30 s per-pair timeout. Reported as a
      structural analog of the MIST-paper MCES metric, which uses bond
      counts — atom-fraction is a close cousin and uses only RDKit.]

Then aggregates:
  - mean / median / p25 / p75 / p90 Tanimoto and MCS-frac per config
  - paired Δ (D3 − D2) per spec
  - Wilcoxon signed-rank p-value (D3 vs D2 on the paired distribution)

Outputs:
  data/paper_figures/phase6_6_structural_metrics.csv         (per-spec)
  data/paper_figures/phase6_6_structural_summary.csv         (aggregate)

Run:
  python scripts/eval_sub6/casmi_structural_metrics.py
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


def _morgan_fp(mol):
    return AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048)


def _tanimoto(pred_smi: str | None, gt_smi: str | None) -> float | None:
    if not pred_smi or not gt_smi:
        return None
    pm = Chem.MolFromSmiles(pred_smi)
    gm = Chem.MolFromSmiles(gt_smi)
    if pm is None or gm is None:
        return None
    return float(DataStructs.TanimotoSimilarity(_morgan_fp(pm), _morgan_fp(gm)))


def _mcs_atom_fraction(pred_smi: str | None, gt_smi: str | None,
                      *, timeout_s: int = 30) -> float | None:
    """Atom-fraction of the maximum common substructure: |MCS atoms| /
    max(|pred atoms|, |GT atoms|). 1.0 iff predicted == GT (up to relabeling).
    Returns None on parse / timeout / empty-MCS failure."""
    if not pred_smi or not gt_smi:
        return None
    pm = Chem.MolFromSmiles(pred_smi)
    gm = Chem.MolFromSmiles(gt_smi)
    if pm is None or gm is None:
        return None
    n_pred = pm.GetNumAtoms()
    n_gt = gm.GetNumAtoms()
    denom = max(n_pred, n_gt, 1)
    try:
        res = rdFMCS.FindMCS([pm, gm], timeout=timeout_s,
                             completeRingsOnly=False,
                             ringMatchesRingOnly=False,
                             matchValences=False)
    except Exception:
        return None
    if res.canceled or res.numAtoms == 0:
        return None
    return float(res.numAtoms / denom)


def _load_idents(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for line in path.open():
        rec = json.loads(line)
        out[rec["spectrum_id"]] = rec
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("data/eval/casmi"))
    ap.add_argument("--out", type=Path, default=Path("data/paper_figures"))
    ap.add_argument("--mcs-timeout-s", type=int, default=30)
    ap.add_argument("--skip-mcs", action="store_true",
                    help="Only compute Tanimoto (faster).")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    bs = _load_idents(args.root / "2022_msclip_only" / "casmi_identifications.jsonl")
    cd = _load_idents(args.root / "2022_conditional" / "casmi_identifications.jsonl")
    sids = sorted(set(bs) & set(cd))
    logger.info("paired spectra: %d", len(sids))

    rows = []
    for i, sid in enumerate(sids):
        b = bs[sid]; c = cd[sid]
        gt = b.get("gt_smiles") or c.get("gt_smiles")
        bp = b.get("predicted_smiles")
        cp = c.get("predicted_smiles")
        tan_b = _tanimoto(bp, gt)
        tan_c = _tanimoto(cp, gt)
        mcs_b = mcs_c = None
        if not args.skip_mcs:
            mcs_b = _mcs_atom_fraction(bp, gt, timeout_s=args.mcs_timeout_s)
            mcs_c = _mcs_atom_fraction(cp, gt, timeout_s=args.mcs_timeout_s)
        rows.append({
            "spectrum_id": sid,
            "formula": b.get("casmi_formula"),
            "gt_smiles": gt,
            "msclip_only_pred": bp,
            "conditional_pred": cp,
            "msclip_only_tanimoto": tan_b,
            "conditional_tanimoto": tan_c,
            "delta_tanimoto": (tan_c - tan_b) if (tan_b is not None and tan_c is not None) else None,
            "msclip_only_mcs_frac": mcs_b,
            "conditional_mcs_frac": mcs_c,
            "delta_mcs_frac": (mcs_c - mcs_b) if (mcs_b is not None and mcs_c is not None) else None,
            "msclip_only_exact": int(b.get("correct_top1") is True),
            "conditional_exact": int(c.get("correct_top1") is True),
        })
        if (i + 1) % 25 == 0:
            logger.info("processed %d/%d", i + 1, len(sids))

    out_per = args.out / "phase6_6_structural_metrics.csv"
    with out_per.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    logger.info("wrote per-spec %s", out_per)

    def _stats(name: str, vals: list[float]) -> dict:
        import statistics as st
        vals = [v for v in vals if v is not None]
        if not vals:
            return {"metric": name, "n": 0}
        s = sorted(vals)
        return {
            "metric": name,
            "n": len(vals),
            "mean": round(sum(vals) / len(vals), 4),
            "median": round(st.median(vals), 4),
            "p25": round(s[int(0.25 * len(s))], 4),
            "p75": round(s[int(0.75 * len(s))], 4),
            "p90": round(s[int(0.90 * len(s))], 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
        }

    tan_b = [r["msclip_only_tanimoto"] for r in rows]
    tan_c = [r["conditional_tanimoto"] for r in rows]
    mcs_b = [r["msclip_only_mcs_frac"] for r in rows]
    mcs_c = [r["conditional_mcs_frac"] for r in rows]

    summary_rows = [
        _stats("tanimoto_msclip_only", tan_b),
        _stats("tanimoto_conditional", tan_c),
        _stats("mcs_frac_msclip_only", mcs_b),
        _stats("mcs_frac_conditional", mcs_c),
    ]

    # Paired Wilcoxon signed-rank: D3 vs D2.
    def _paired_wilcoxon(a, b, label):
        pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
        if not pairs:
            return None
        diffs = [y - x for x, y in pairs]
        n_pos = sum(1 for d in diffs if d > 0)
        n_neg = sum(1 for d in diffs if d < 0)
        n_zero = sum(1 for d in diffs if d == 0)
        if n_pos + n_neg == 0:
            return {"comparison": label, "n_paired": len(pairs),
                    "n_d3_better": n_pos, "n_d2_better": n_neg, "n_tied": n_zero,
                    "mean_delta": 0.0, "wilcoxon_p": 1.0}
        res = wilcoxon(diffs, zero_method="wilcox", alternative="two-sided")
        p = float(res.pvalue)
        return {
            "comparison": label,
            "n_paired": len(pairs),
            "n_d3_better": n_pos,
            "n_d2_better": n_neg,
            "n_tied": n_zero,
            "mean_delta": round(sum(diffs) / len(diffs), 5),
            "wilcoxon_p": round(p, 4) if p >= 1e-4 else f"{p:.2e}",
        }

    wilcoxon_rows = [
        _paired_wilcoxon(tan_b, tan_c, "tanimoto: conditional vs msclip_only"),
    ]
    if not args.skip_mcs:
        wilcoxon_rows.append(_paired_wilcoxon(mcs_b, mcs_c, "mcs_frac: conditional vs msclip_only"))

    summary_csv = args.out / "phase6_6_structural_summary.csv"
    with summary_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        w.writeheader(); w.writerows(summary_rows)

    wilcoxon_csv = args.out / "phase6_6_structural_wilcoxon.csv"
    with wilcoxon_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(wilcoxon_rows[0].keys()))
        w.writeheader(); w.writerows(wilcoxon_rows)

    print("=" * 70)
    print("Per-config distributions:")
    for r in summary_rows:
        if r.get("n"):
            print(f"  {r['metric']:<28} n={r['n']:>3}  mean={r['mean']:.4f}  median={r['median']:.4f}  p90={r['p90']:.4f}")
        else:
            print(f"  {r['metric']:<28} n=0 (no valid pairs)")
    print()
    print("Paired Wilcoxon signed-rank (D3 vs D2):")
    for r in wilcoxon_rows:
        if r is None:
            continue
        print(f"  {r['comparison']:<48} n={r['n_paired']}  D3>D2={r['n_d3_better']}  D3<D2={r['n_d2_better']}  ties={r['n_tied']}  mean_Δ={r['mean_delta']}  p={r['wilcoxon_p']}")
    print()
    print(f"wrote per-spec:   {out_per}")
    print(f"wrote summary:    {summary_csv}")
    print(f"wrote wilcoxon:   {wilcoxon_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
