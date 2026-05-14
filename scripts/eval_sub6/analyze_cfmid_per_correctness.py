"""Phase 6.5 D2 — CFM-ID per-correctness analysis on Sub-6A real-id v2.

For every (spectrum, candidate) pair in Phase 6.2 full peak_evidence, mark
candidate as correct/wrong by comparing its RDKit InChIKey first-block to
the spectrum's gt_inchikey_first_block. Aggregate CFM-ID metrics:

  group A — correct candidate
  group B — wrong candidate
  → Are the CFM-ID predicted-spectrum cosines distinguishable between A and B?

Two metrics per candidate:
  predicted_cosine          — already in peak_evidence (CFM vs experimental)
  predicted_peaks_in_exp_pct — newly computed: % of CFM top-10 predicted peaks
                               that match an experimental peak within 5 ppm

Outputs:
  data/paper_figures/phase6_5_cfm_per_correctness.csv  (aggregate)
  data/paper_figures/phase6_5_cfm_distribution.csv     (per-candidate raw rows)

Pure read-only, no LLM, no SIRIUS/CFM rerun.
"""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

ROOT = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5")
PE_DIR = ROOT / "data/eval/sub6/v2_phase6_2/full/peak_evidence"
NARR = ROOT / "data/eval/sub6/v2_phase6_2/full/sub6a_narratives.jsonl"
OUT = ROOT / "data/paper_figures"


def smi_to_ik14(smi: str | None) -> str | None:
    if not smi:
        return None
    try:
        from rdkit import Chem
        from rdkit.Chem.inchi import MolToInchiKey
        m = Chem.MolFromSmiles(smi)
        if m is None:
            return None
        return MolToInchiKey(m)[:14]
    except Exception:
        return None


def load_spectrum_meta() -> dict[str, dict]:
    """spectrum_id → {gt_ik14, experimental_peaks (list of mz)}"""
    out = {}
    for line in NARR.open():
        rec = json.loads(line)
        for ident in rec.get("identifications", []):
            sid = ident.get("spectrum_id")
            gt = ident.get("gt_inchikey_first_block")
            if sid:
                out[sid] = {"gt_ik14": gt}
    return out


def fetch_experimental_peaks(pe: dict) -> list[float]:
    return [row[0] for row in pe.get("experimental_peaks", []) if isinstance(row, (list, tuple)) and row]


def fetch_cfmid_top_peaks(pe: dict) -> dict[str, list[float]]:
    """smiles → list of cfmid predicted m/z (top-1 candidate only — Phase 6.2
    only stored top1's CFM peaks per spectrum)."""
    top1 = pe.get("cfmid_top1") or {}
    smi = top1.get("smiles")
    peaks = top1.get("predicted_peaks") or []
    if not smi:
        return {}
    pred_mz = [row[0] for row in peaks if isinstance(row, (list, tuple)) and row]
    return {smi: pred_mz}


def predicted_in_exp_pct(pred_mz: list[float], exp_mz: list[float], ppm: float = 5.0) -> float | None:
    """% of pred peaks that match an experimental peak within ppm."""
    if not pred_mz or not exp_mz:
        return None
    hits = 0
    for p in pred_mz:
        if p <= 0:
            continue
        tol_da = p * ppm / 1e6
        for e in exp_mz:
            if abs(e - p) <= tol_da:
                hits += 1
                break
    return 100.0 * hits / len(pred_mz)


def main() -> int:
    spec_meta = load_spectrum_meta()
    rows_per_cand = []
    correct_cnt = wrong_cnt = 0
    for f in sorted(PE_DIR.glob("*.json")):
        pe = json.loads(f.read_text())
        sid = pe.get("spectrum_id")
        gt = (spec_meta.get(sid) or {}).get("gt_ik14")
        if not gt:
            continue
        exp_mz = fetch_experimental_peaks(pe)
        cfm_peaks_by_smi = fetch_cfmid_top_peaks(pe)
        for c in pe.get("candidates_evaluated", []):
            smi = c.get("smiles")
            ik = smi_to_ik14(smi)
            cfm_cosine = c.get("predicted_cosine")
            cfm_pred = cfm_peaks_by_smi.get(smi, [])
            in_exp_pct = predicted_in_exp_pct(cfm_pred, exp_mz) if cfm_pred else None
            is_correct = (ik == gt)
            if is_correct:
                correct_cnt += 1
            else:
                wrong_cnt += 1
            rows_per_cand.append({
                "spectrum_id": sid,
                "candidate_smiles": smi,
                "candidate_name": c.get("name"),
                "is_correct": int(is_correct),
                "rank_after_rerank": c.get("rank_after_rerank"),
                "modcos": c.get("modcos"),
                "predicted_cosine": cfm_cosine,
                "predicted_in_exp_pct": in_exp_pct,
                "sirius_match": c.get("sirius_match"),
                "mass_match": c.get("mass_match"),
            })

    raw_csv = OUT / "phase6_5_cfm_distribution.csv"
    with raw_csv.open("w", newline="") as fcsv:
        w = csv.DictWriter(fcsv, fieldnames=list(rows_per_cand[0].keys()))
        w.writeheader(); w.writerows(rows_per_cand)
    print(f"wrote {raw_csv} ({len(rows_per_cand)} candidate rows; {correct_cnt} correct, {wrong_cnt} wrong)")

    # Aggregate
    def stat(vals: list[float]) -> dict:
        clean = [v for v in vals if v is not None]
        if not clean:
            return {"n": 0, "mean": None, "median": None, "p25": None, "p75": None}
        clean = sorted(clean)
        return {
            "n": len(clean),
            "mean": round(statistics.mean(clean), 4),
            "median": round(clean[len(clean)//2], 4),
            "p25": round(clean[len(clean)//4], 4),
            "p75": round(clean[(3*len(clean))//4], 4),
            "min": round(clean[0], 4),
            "max": round(clean[-1], 4),
        }

    correct_rows = [r for r in rows_per_cand if r["is_correct"]]
    wrong_rows = [r for r in rows_per_cand if not r["is_correct"]]

    summary = []
    for label, rows in [("correct candidate", correct_rows),
                        ("wrong candidate", wrong_rows),
                        ("all candidates", rows_per_cand)]:
        cosine_stat = stat([r["predicted_cosine"] for r in rows])
        pct_stat = stat([r["predicted_in_exp_pct"] for r in rows])
        summary.append({
            "group": label,
            "n_candidates": len(rows),
            "cfm_cosine_n": cosine_stat["n"],
            "cfm_cosine_mean": cosine_stat["mean"],
            "cfm_cosine_median": cosine_stat["median"],
            "cfm_cosine_p25": cosine_stat["p25"],
            "cfm_cosine_p75": cosine_stat["p75"],
            "in_exp_pct_n": pct_stat["n"],
            "in_exp_pct_mean": pct_stat["mean"],
            "in_exp_pct_median": pct_stat["median"],
            "in_exp_pct_p25": pct_stat["p25"],
            "in_exp_pct_p75": pct_stat["p75"],
        })

    out_csv = OUT / "phase6_5_cfm_per_correctness.csv"
    with out_csv.open("w", newline="") as fcsv:
        w = csv.DictWriter(fcsv, fieldnames=list(summary[0].keys()))
        w.writeheader(); w.writerows(summary)
    print(f"wrote {out_csv}")
    print()
    print("=== CFM-ID per-correctness aggregate ===")
    for r in summary:
        print(f"\n  {r['group']:<22}: n={r['n_candidates']}")
        print(f"    cfm_cosine:        n={r['cfm_cosine_n']:>4}  mean={r['cfm_cosine_mean']}  median={r['cfm_cosine_median']}  IQR=[{r['cfm_cosine_p25']}, {r['cfm_cosine_p75']}]")
        print(f"    in_exp_pct:        n={r['in_exp_pct_n']:>4}  mean={r['in_exp_pct_mean']}  median={r['in_exp_pct_median']}  IQR=[{r['in_exp_pct_p25']}, {r['in_exp_pct_p75']}]")

    # Mann-Whitney effect size between correct and wrong cfm_cosine
    try:
        from scipy.stats import mannwhitneyu
        c_cosine = [r["predicted_cosine"] for r in correct_rows if r["predicted_cosine"] is not None]
        w_cosine = [r["predicted_cosine"] for r in wrong_rows if r["predicted_cosine"] is not None]
        if c_cosine and w_cosine:
            u, p = mannwhitneyu(c_cosine, w_cosine, alternative="greater")
            n1, n2 = len(c_cosine), len(w_cosine)
            # Wendt rank-biserial correlation = (2*U)/(n1*n2) - 1
            rbc = (2 * u) / (n1 * n2) - 1
            print(f"\nMann-Whitney U (correct > wrong) on cfm_cosine: U={u:.0f}, p={p:.4f}, rank-biserial r={rbc:.3f}")
            print(f"  (r ~ 0 → no discrimination; r=0.5 → moderate; r=1 → perfect)")
    except Exception as exc:
        print(f"(skipped Mann-Whitney: {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
