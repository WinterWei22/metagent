"""Phase 6.5 D5a-grid — sweep conditional gate thresholds.

For each (msclip_top1_threshold, msclip_gap_threshold) in a grid, compute:
  - Config E id_acc on the 448 cached spectra
  - skip / trigger rate
  - McNemar p-value vs msclip-only baseline
  - McNemar p-value vs Phase 6.3 B (always-rerank)

Output:
  data/paper_figures/phase6_5_grid_search.csv

Run with the same dual-score cache as simulate_config_e.py.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from scipy.stats import binomtest

ROOT = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5")
CACHE = ROOT / "data/cache/library_search_dual_score.jsonl"
PHASE63_B = ROOT / "data/eval/sub6/v2_phase6_3/B_msclip_weighted/sub6a_narratives.jsonl"
OUT = ROOT / "data/paper_figures"


def smi_to_ik14(smi):
    if not smi: return None
    try:
        from rdkit import Chem
        from rdkit.Chem.inchi import MolToInchiKey
        m = Chem.MolFromSmiles(smi)
        if m is None: return None
        return MolToInchiKey(m)[:14]
    except Exception:
        return None


def mcnemar_p(a, b):
    n_b = sum(1 for x, y in zip(a, b) if not x and y)
    n_c = sum(1 for x, y in zip(a, b) if x and not y)
    n = n_b + n_c
    if n == 0:
        return 1.0
    return float(binomtest(min(n_b, n_c), n, p=0.5, alternative="two-sided").pvalue)


def load_phase63b():
    out = {}
    for line in PHASE63_B.open():
        rec = json.loads(line)
        for ident in rec.get("identifications", []):
            sid = ident.get("spectrum_id")
            smi = ident.get("predicted_smiles")
            if sid is not None: out[sid] = smi
    return out


def main():
    p63b = load_phase63b()
    # pre-compute per-spectrum signals
    rows = []
    for line in CACHE.open():
        rec = json.loads(line)
        if rec.get("error"): continue
        sid = rec["spectrum_id"]
        gt = rec.get("gt_inchikey_first_block")
        cands = rec.get("candidates") or []
        if not cands or not gt: continue
        ms_cands = [c for c in cands if c.get("msclip_rescaled") is not None]
        if ms_cands:
            ms_sorted = sorted(ms_cands, key=lambda c: c["msclip_rescaled"], reverse=True)
            ms_top1 = ms_sorted[0]
            ms_top1_score = ms_top1["msclip_rescaled"]
            ms_gap = ms_top1_score - (ms_sorted[1]["msclip_rescaled"] if len(ms_sorted) > 1 else 0.0)
            ms_top1_correct = (smi_to_ik14(ms_top1["smiles"]) == gt)
        else:
            ms_top1_score = None
            ms_gap = None
            ms_top1_correct = False
        p63b_smi = p63b.get(sid)
        p63b_correct = (smi_to_ik14(p63b_smi) == gt) if p63b_smi else False
        rows.append({
            "msclip_top1_score": ms_top1_score, "msclip_gap": ms_gap,
            "msclip_correct": ms_top1_correct, "phase63b_correct": p63b_correct,
        })
    n_total = len(rows)
    msclip_baseline_correct = sum(1 for r in rows if r["msclip_correct"])
    phase63b_correct = sum(1 for r in rows if r["phase63b_correct"])
    print(f"n_total={n_total}, msclip baseline correct={msclip_baseline_correct} ({100*msclip_baseline_correct/n_total:.2f}%)")
    print(f"Phase 6.3 B (always rerank) correct={phase63b_correct} ({100*phase63b_correct/n_total:.2f}%)")
    print()

    top1_grid = [0.0, 0.70, 0.75, 0.80, 0.83, 0.85, 0.87]
    gap_grid = [0.0, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20]

    out_rows = []
    msclip_outcomes = [r["msclip_correct"] for r in rows]
    p63b_outcomes = [r["phase63b_correct"] for r in rows]

    for t1 in top1_grid:
        for g in gap_grid:
            n_skip = 0
            ce_outcomes = []
            for r in rows:
                if (r["msclip_top1_score"] is not None and r["msclip_top1_score"] >= t1
                    and r["msclip_gap"] is not None and r["msclip_gap"] >= g):
                    n_skip += 1
                    ce_outcomes.append(r["msclip_correct"])
                else:
                    ce_outcomes.append(r["phase63b_correct"])
            ce_correct = sum(ce_outcomes)
            ce_acc = 100 * ce_correct / n_total
            delta_vs_msclip = ce_correct - msclip_baseline_correct
            delta_vs_p63b = ce_correct - phase63b_correct
            p_vs_msclip = mcnemar_p(msclip_outcomes, ce_outcomes)
            p_vs_p63b = mcnemar_p(p63b_outcomes, ce_outcomes)
            out_rows.append({
                "msclip_top1_thresh": t1,
                "msclip_gap_thresh": g,
                "skip_n": n_skip,
                "skip_pct": round(100 * n_skip / n_total, 2),
                "trigger_n": n_total - n_skip,
                "config_e_correct": ce_correct,
                "config_e_acc_pct": round(ce_acc, 2),
                "delta_vs_msclip_only_spec": delta_vs_msclip,
                "delta_vs_msclip_only_pp": round(100 * delta_vs_msclip / n_total, 2),
                "p_vs_msclip_only": round(p_vs_msclip, 4) if p_vs_msclip >= 0.0001 else f"{p_vs_msclip:.2e}",
                "delta_vs_phase63b_spec": delta_vs_p63b,
                "delta_vs_phase63b_pp": round(100 * delta_vs_p63b / n_total, 2),
                "p_vs_phase63b": round(p_vs_p63b, 4) if p_vs_p63b >= 0.0001 else f"{p_vs_p63b:.2e}",
            })

    out_csv = OUT / "phase6_5_grid_search.csv"
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader(); w.writerows(out_rows)
    print(f"wrote {out_csv} ({len(out_rows)} cells)")
    print()

    # Sort by config_e_acc descending and show top-10
    print("=== TOP 10 thresholds by Config E id_acc ===")
    print(f"{'top1':>6} {'gap':>6} {'skip%':>7} {'CE_acc':>7} {'Δms':>5} {'p_ms':>8} {'Δp63b':>6} {'p_p63b':>8}")
    for r in sorted(out_rows, key=lambda x: -x["config_e_acc_pct"])[:10]:
        print(f"{r['msclip_top1_thresh']:>6} {r['msclip_gap_thresh']:>6} {r['skip_pct']:>6.1f}% "
              f"{r['config_e_acc_pct']:>6.2f}% {r['delta_vs_msclip_only_pp']:>+5.1f} {str(r['p_vs_msclip_only']):>8} "
              f"{r['delta_vs_phase63b_pp']:>+5.1f} {str(r['p_vs_phase63b']):>8}")
    print()
    # also show: highest Δ vs Phase 6.3 B (i.e. conditional beats always-rerank most)
    print("=== TOP 5 thresholds by Δ vs Phase 6.3 B (conditional > always-rerank most) ===")
    for r in sorted(out_rows, key=lambda x: -x["delta_vs_phase63b_spec"])[:5]:
        print(f"{r['msclip_top1_thresh']:>6} {r['msclip_gap_thresh']:>6} {r['skip_pct']:>6.1f}% "
              f"{r['config_e_acc_pct']:>6.2f}% Δms={r['delta_vs_msclip_only_pp']:+.1f} "
              f"Δp63b={r['delta_vs_phase63b_pp']:+.1f} p_p63b={r['p_vs_phase63b']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
