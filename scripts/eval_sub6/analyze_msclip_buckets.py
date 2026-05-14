"""Phase 6.5 D1 supplement — MS-CLIP confidence + top-K gap bucketing.

Same structure as analyze_modcos_buckets.py but using MS-CLIP rescaled scores
recovered from the dual-score cache (build_msclip_modcos_cache.py).

For each spectrum, compute:
  pre-rerank-by-msclip top-1  = candidate with max msclip_rescaled
  pre-rerank-by-modcos top-1  = candidate with max modcos          (D1 baseline)
  post-rerank top-1           = Phase 6.3 B narrative (msclip primary + weighted)

Outputs:
  data/paper_figures/phase6_5_msclip_buckets.csv
  data/paper_figures/phase6_5_msclip_topk_gap.csv
  data/paper_figures/phase6_5_modcos_vs_msclip_pre_rerank.csv (which signal picks better top-1)
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5")
CACHE = ROOT / "data/cache/library_search_dual_score.jsonl"
PHASE63_B_NARR = ROOT / "data/eval/sub6/v2_phase6_3/B_msclip_weighted/sub6a_narratives.jsonl"
OUT = ROOT / "data/paper_figures"


def smi_to_ik14(smi: str | None) -> str | None:
    if not smi:
        return None
    try:
        from rdkit import Chem
        from rdkit.Chem.inchi import MolToInchiKey
        m = Chem.MolFromSmiles(smi)
        if m is None: return None
        return MolToInchiKey(m)[:14]
    except Exception:
        return None


def msclip_bucket(score: float) -> str:
    if score >= 0.9: return "very_high (≥0.9)"
    if score >= 0.8: return "high (0.8-0.9)"
    if score >= 0.6: return "medium (0.6-0.8)"
    if score >= 0.4: return "low (0.4-0.6)"
    return "very_low (<0.4)"


def gap_bucket(gap: float) -> str:
    if gap >= 0.15: return "wide (≥0.15)"
    if gap >= 0.05: return "medium (0.05-0.15)"
    return "narrow (<0.05)"


def load_phase63B_post_rerank() -> dict[str, bool]:
    """spectrum_id → correct_top1 from Phase 6.3 B msclip+weighted narrative."""
    out = {}
    if not PHASE63_B_NARR.exists():
        return out
    for line in PHASE63_B_NARR.open():
        rec = json.loads(line)
        for ident in rec.get("identifications", []):
            sid = ident.get("spectrum_id"); ok = ident.get("correct_top1")
            if sid is not None and ok is not None:
                out[sid] = bool(ok)
    return out


def main() -> int:
    post_rerank = load_phase63B_post_rerank()
    print(f"loaded {len(post_rerank)} Phase 6.3 B post-rerank labels")

    rows = []
    n_total = n_with_msclip = n_with_modcos = 0
    msclip_top_picked_correct = msclip_top_picked_wrong = 0
    modcos_top_picked_correct = modcos_top_picked_wrong = 0
    crosstab = {"both_correct": 0, "modcos_only": 0, "msclip_only": 0, "both_wrong": 0}

    for line in CACHE.open():
        rec = json.loads(line)
        if rec.get("error"):
            continue
        sid = rec["spectrum_id"]
        gt = rec.get("gt_inchikey_first_block")
        cands = rec.get("candidates") or []
        if not cands or not gt:
            continue
        n_total += 1

        # filter only candidates with msclip score available
        msclip_cands = [c for c in cands if c.get("msclip_rescaled") is not None]
        modcos_cands = [c for c in cands if c.get("modcos") is not None]

        msclip_top1_score = None
        msclip_gap = None
        msclip_top1_correct = None
        if msclip_cands:
            msclip_cands_sorted = sorted(msclip_cands, key=lambda c: c.get("msclip_rescaled") or 0.0, reverse=True)
            t1 = msclip_cands_sorted[0]
            msclip_top1_score = float(t1.get("msclip_rescaled"))
            t2_score = float(msclip_cands_sorted[1].get("msclip_rescaled")) if len(msclip_cands_sorted) >= 2 else 0.0
            msclip_gap = msclip_top1_score - t2_score
            ik = smi_to_ik14(t1.get("smiles"))
            msclip_top1_correct = (ik == gt)
            n_with_msclip += 1
            if msclip_top1_correct: msclip_top_picked_correct += 1
            else: msclip_top_picked_wrong += 1

        modcos_top1_correct = None
        if modcos_cands:
            modcos_cands_sorted = sorted(modcos_cands, key=lambda c: c.get("modcos") or 0.0, reverse=True)
            t1m = modcos_cands_sorted[0]
            ikm = smi_to_ik14(t1m.get("smiles"))
            modcos_top1_correct = (ikm == gt)
            n_with_modcos += 1
            if modcos_top1_correct: modcos_top_picked_correct += 1
            else: modcos_top_picked_wrong += 1

        # cross-tab modcos vs msclip top-1 correctness
        if modcos_top1_correct is not None and msclip_top1_correct is not None:
            if modcos_top1_correct and msclip_top1_correct: crosstab["both_correct"] += 1
            elif modcos_top1_correct and not msclip_top1_correct: crosstab["modcos_only"] += 1
            elif msclip_top1_correct and not modcos_top1_correct: crosstab["msclip_only"] += 1
            else: crosstab["both_wrong"] += 1

        post_correct = post_rerank.get(sid)
        rows.append({
            "spectrum_id": sid,
            "msclip_top1_score": msclip_top1_score,
            "msclip_gap": msclip_gap,
            "msclip_pre_correct": int(msclip_top1_correct) if msclip_top1_correct is not None else None,
            "modcos_pre_correct": int(modcos_top1_correct) if modcos_top1_correct is not None else None,
            "post_rerank_B_correct": int(post_correct) if post_correct is not None else None,
        })

    print(f"\nspectra processed: {n_total}")
    print(f"  with msclip score: {n_with_msclip}")
    print(f"  with modcos score: {n_with_modcos}")
    print(f"\nTop-1 correctness (over {n_total} spectra):")
    print(f"  by msclip: {msclip_top_picked_correct} correct ({100*msclip_top_picked_correct/n_total:.2f}%)")
    print(f"  by modcos: {modcos_top_picked_correct} correct ({100*modcos_top_picked_correct/n_total:.2f}%)")
    print(f"\nmodcos vs msclip top-1 cross-tab:")
    for k, v in crosstab.items():
        print(f"  {k}: {v} ({100*v/n_total:.2f}%)")

    # ---- msclip confidence bucket ----
    msclip_order = ["very_high (≥0.9)", "high (0.8-0.9)", "medium (0.6-0.8)",
                    "low (0.4-0.6)", "very_low (<0.4)"]
    bucket_rows = []
    for b in msclip_order:
        sub = [r for r in rows if r["msclip_top1_score"] is not None
               and msclip_bucket(r["msclip_top1_score"]) == b]
        if not sub: continue
        n = len(sub)
        npre = sum(r["msclip_pre_correct"] or 0 for r in sub)
        # post-rerank from Phase 6.3 B (msclip primary + weighted)
        npost_sub = [r for r in sub if r["post_rerank_B_correct"] is not None]
        npost_n = len(npost_sub)
        npost = sum(r["post_rerank_B_correct"] or 0 for r in npost_sub)
        bucket_rows.append({
            "bucket": b,
            "n_spectra": n,
            "frac_of_total": round(100 * n / n_total, 2),
            "pre_rerank_msclip_correct": npre,
            "pre_rerank_msclip_pct": round(100 * npre / n, 2),
            "post_rerank_B_n": npost_n,
            "post_rerank_B_correct": npost,
            "post_rerank_B_pct": round(100 * npost / npost_n, 2) if npost_n else 0.0,
            "delta_pp": round(100 * (npost - npre) / n if n else 0, 2),
        })
    out_a = OUT / "phase6_5_msclip_buckets.csv"
    with out_a.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(bucket_rows[0].keys()))
        w.writeheader(); w.writerows(bucket_rows)
    print(f"\nwrote {out_a}")
    print("\n=== msclip confidence bucket ===")
    for r in bucket_rows:
        print(f"  {r['bucket']:<22} n={r['n_spectra']:>3} ({r['frac_of_total']:>5}%) "
              f"pre-msclip={r['pre_rerank_msclip_pct']:>5}%  post-B={r['post_rerank_B_pct']:>5}%  Δ={r['delta_pp']:>+5}pp")

    # ---- msclip top1-top2 gap bucket ----
    gap_order = ["wide (≥0.15)", "medium (0.05-0.15)", "narrow (<0.05)"]
    gap_rows = []
    for b in gap_order:
        sub = [r for r in rows if r["msclip_gap"] is not None
               and gap_bucket(r["msclip_gap"]) == b]
        if not sub: continue
        n = len(sub)
        npre = sum(r["msclip_pre_correct"] or 0 for r in sub)
        npost_sub = [r for r in sub if r["post_rerank_B_correct"] is not None]
        npost_n = len(npost_sub)
        npost = sum(r["post_rerank_B_correct"] or 0 for r in npost_sub)
        gap_rows.append({
            "bucket": b,
            "n_spectra": n,
            "frac_of_total": round(100 * n / n_total, 2),
            "pre_rerank_pct": round(100 * npre / n, 2),
            "post_rerank_pct": round(100 * npost / npost_n, 2) if npost_n else 0.0,
            "delta_pp": round(100 * (npost - npre) / n, 2),
        })
    out_b = OUT / "phase6_5_msclip_topk_gap.csv"
    with out_b.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(gap_rows[0].keys()))
        w.writeheader(); w.writerows(gap_rows)
    print(f"\nwrote {out_b}")
    print("\n=== msclip top1-top2 gap bucket ===")
    for r in gap_rows:
        print(f"  {r['bucket']:<22} n={r['n_spectra']:>3} ({r['frac_of_total']:>5}%) "
              f"pre={r['pre_rerank_pct']:>5}%  post={r['post_rerank_pct']:>5}%  Δ={r['delta_pp']:>+5}pp")

    # ---- modcos vs msclip cross-tab CSV ----
    cross_csv = OUT / "phase6_5_modcos_vs_msclip_pre_rerank.csv"
    with cross_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["bucket", "n_spectra", "pct"])
        w.writeheader()
        for k, v in crosstab.items():
            w.writerow({"bucket": k, "n_spectra": v, "pct": round(100*v/n_total, 2)})
        w.writerow({"bucket": "TOTAL", "n_spectra": n_total, "pct": 100.0})
    print(f"wrote {cross_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
