"""Phase 6.5 D1 — Modcos confidence + top-K gap bucketing on Sub-6A real-id v2.

Reads Phase 6.2 full peak_evidence (358 spectra, modcos primary, gnps+inhouse
fused ≈ modcos) plus the matching narrative file (for ground-truth InChIKey
first-block per spectrum_id). For each spectrum:

  pre-rerank top-1  = candidates_evaluated entry with max `modcos` (fused score)
  post-rerank top-1 = candidates_evaluated entry with rank_after_rerank == 1

Buckets:
  (a) modcos top-1 in {very_high ≥0.9, high 0.8-0.9, medium 0.6-0.8,
                        low 0.4-0.6, very_low <0.4}
  (b) top1-top2 modcos gap in {wide ≥0.15, medium 0.05-0.15, narrow <0.05}

Outputs:
  data/paper_figures/phase6_5_modcos_buckets.csv
  data/paper_figures/phase6_5_topk_gap_buckets.csv

Pure read-only, no LLM, no SIRIUS/CFM rerun.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5")
PE_DIR = ROOT / "data/eval/sub6/v2_phase6_2/full/peak_evidence"
NARR = ROOT / "data/eval/sub6/v2_phase6_2/full/sub6a_narratives.jsonl"
OUT = ROOT / "data/paper_figures"
OUT.mkdir(parents=True, exist_ok=True)


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


def load_gt_lookup() -> dict[str, str]:
    """spectrum_id → gt InChIKey first-block."""
    out: dict[str, str] = {}
    for line in NARR.open():
        rec = json.loads(line)
        for ident in rec.get("identifications", []):
            sid = ident.get("spectrum_id")
            gt = ident.get("gt_inchikey_first_block")
            if sid and gt:
                out[sid] = gt
    return out


def modcos_bucket(score: float) -> str:
    if score >= 0.9:
        return "very_high (≥0.9)"
    if score >= 0.8:
        return "high (0.8-0.9)"
    if score >= 0.6:
        return "medium (0.6-0.8)"
    if score >= 0.4:
        return "low (0.4-0.6)"
    return "very_low (<0.4)"


def gap_bucket(gap: float) -> str:
    if gap >= 0.15:
        return "wide (≥0.15)"
    if gap >= 0.05:
        return "medium (0.05-0.15)"
    return "narrow (<0.05)"


def main() -> int:
    gt_lookup = load_gt_lookup()
    print(f"loaded {len(gt_lookup)} spectrum_id → gt_inchikey first-block")

    rows = []  # per-spectrum tuples for both bucket axes
    for f in sorted(PE_DIR.glob("*.json")):
        pe = json.loads(f.read_text())
        sid = pe.get("spectrum_id")
        cands = pe.get("candidates_evaluated") or []
        if not cands:
            continue
        gt = gt_lookup.get(sid)
        if not gt:
            continue
        # pre-rerank top-1: highest modcos
        cands_sorted_modcos = sorted(cands, key=lambda c: c.get("modcos") or 0.0, reverse=True)
        pre = cands_sorted_modcos[0]
        pre_modcos = float(pre.get("modcos") or 0.0)
        # top-2 modcos for gap
        if len(cands_sorted_modcos) >= 2:
            top2 = float(cands_sorted_modcos[1].get("modcos") or 0.0)
            gap = pre_modcos - top2
        else:
            gap = 1.0  # treat single-candidate as wide gap
        # post-rerank top-1
        post = next((c for c in cands if c.get("rank_after_rerank") == 1), cands[0])
        # correctness
        pre_ik = smi_to_ik14(pre.get("smiles"))
        post_ik = smi_to_ik14(post.get("smiles"))
        rows.append({
            "spectrum_id": sid,
            "modcos_top1": pre_modcos,
            "top12_gap": gap,
            "n_cands": len(cands),
            "pre_correct": int(pre_ik == gt),
            "post_correct": int(post_ik == gt),
            "modcos_bucket": modcos_bucket(pre_modcos),
            "gap_bucket": gap_bucket(gap),
        })

    print(f"analyzed {len(rows)} spectra")

    # ---- modcos bucket ----
    modcos_order = ["very_high (≥0.9)", "high (0.8-0.9)", "medium (0.6-0.8)",
                    "low (0.4-0.6)", "very_low (<0.4)"]
    bucket_rows = []
    for b in modcos_order:
        sub = [r for r in rows if r["modcos_bucket"] == b]
        if not sub:
            continue
        n = len(sub)
        npre = sum(r["pre_correct"] for r in sub)
        npost = sum(r["post_correct"] for r in sub)
        bucket_rows.append({
            "bucket": b,
            "n_spectra": n,
            "frac_of_total": round(100 * n / len(rows), 2),
            "n_pre_correct": npre,
            "pre_acc_pct": round(100 * npre / n, 2),
            "n_post_correct": npost,
            "post_acc_pct": round(100 * npost / n, 2),
            "delta_spectra": npost - npre,
            "delta_pp": round(100 * (npost - npre) / n, 2),
        })
    out_a = OUT / "phase6_5_modcos_buckets.csv"
    with out_a.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(bucket_rows[0].keys()))
        w.writeheader(); w.writerows(bucket_rows)
    print(f"wrote {out_a}")
    print()
    print("=== modcos confidence bucket ===")
    for r in bucket_rows:
        print(f"  {r['bucket']:<22} n={r['n_spectra']:>3} ({r['frac_of_total']:>5}%) "
              f"pre={r['pre_acc_pct']:>5}%  post={r['post_acc_pct']:>5}%  "
              f"Δ={r['delta_pp']:>+5}pp ({r['delta_spectra']:+d})")

    # ---- top-K gap bucket ----
    gap_order = ["wide (≥0.15)", "medium (0.05-0.15)", "narrow (<0.05)"]
    gap_rows = []
    for b in gap_order:
        sub = [r for r in rows if r["gap_bucket"] == b]
        if not sub:
            continue
        n = len(sub)
        npre = sum(r["pre_correct"] for r in sub)
        npost = sum(r["post_correct"] for r in sub)
        gap_rows.append({
            "bucket": b,
            "n_spectra": n,
            "frac_of_total": round(100 * n / len(rows), 2),
            "n_pre_correct": npre,
            "pre_acc_pct": round(100 * npre / n, 2),
            "n_post_correct": npost,
            "post_acc_pct": round(100 * npost / n, 2),
            "delta_spectra": npost - npre,
            "delta_pp": round(100 * (npost - npre) / n, 2),
        })
    out_b = OUT / "phase6_5_topk_gap_buckets.csv"
    with out_b.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(gap_rows[0].keys()))
        w.writeheader(); w.writerows(gap_rows)
    print(f"\nwrote {out_b}")
    print()
    print("=== top1-top2 gap bucket ===")
    for r in gap_rows:
        print(f"  {r['bucket']:<22} n={r['n_spectra']:>3} ({r['frac_of_total']:>5}%) "
              f"pre={r['pre_acc_pct']:>5}%  post={r['post_acc_pct']:>5}%  "
              f"Δ={r['delta_pp']:>+5}pp ({r['delta_spectra']:+d})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
