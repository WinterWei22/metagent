"""Phase 6.7-C — combined n=378 MRR + top-K + Wilcoxon across
CASMI 2022 (n=170) + CASMI 2016 cat2 (n=208).

Per-benchmark derivation reuses casmi_topk_mrr.py's logic in-process; this
script just imports the helpers, applies them to both benchmarks, and
emits a unified CSV + Wilcoxon test on the concatenated reciprocal-rank
vector.
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

import sys
sys.path.insert(0, "/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5")

from scipy.stats import wilcoxon

from evaluation.sub6.casmi_loader import (
    load_casmi_2016_cat2_specs,
    load_casmi_2022_specs,
)
from scripts.eval_sub6.casmi_topk_mrr import (
    derive_weighted_rank, derive_llm_rank, _gt_rank,
    mrr, topk_acc,
)

logger = logging.getLogger(__name__)


def _ranks_for_benchmark(
    *,
    llm_jsonl: Path,
    weighted_anchor_jsonl: Path,
    spec_by_id: dict,
    cfm_cache_dir: Path = Path("data/cache/cfmid"),
    head_k: int = 5,
) -> tuple[list[int | None], list[int | None], list[int | None], list[str]]:
    """Return (msclip_ranks, weighted_ranks, llm_ranks, sid_order)."""
    weighted_anchor: dict[str, str | None] = {}
    if weighted_anchor_jsonl.exists():
        for line in weighted_anchor_jsonl.open():
            w = json.loads(line)
            weighted_anchor[w["spectrum_id"]] = w.get("predicted_inchikey_first_block")
    msclip_ranks, weighted_ranks, llm_ranks, sids = [], [], [], []
    for line in llm_jsonl.open():
        r = json.loads(line)
        sid = r["spectrum_id"]
        gt_ik = r.get("gt_inchikey_first_block")
        ranked = r.get("ranked_candidates") or []
        if not ranked:
            continue
        sp = spec_by_id.get(sid)
        if sp is None:
            continue
        llm_indices = ((r.get("llm_rerank") or {}).get("ranked_indices")) or []
        if sp.peaks:
            base = max(p[1] for p in sp.peaks)
            exp_peaks = [[float(p[0]), float(p[1]) / base if base > 0 else 0.0]
                         for p in sp.peaks]
        else:
            exp_peaks = []
        ms_r = _gt_rank(ranked, gt_ik)
        w_derived = derive_weighted_rank(
            ranked, spectrum_peaks=exp_peaks, precursor_mz=sp.precursor_mz,
            adduct=sp.adduct, ionization_mode=sp.ion_mode,
            cfm_cache_dir=cfm_cache_dir, head_k=head_k,
        )
        wpred = weighted_anchor.get(sid)
        if wpred:
            pinned = None; others = []
            for c in w_derived:
                if c.get("ik14") == wpred and pinned is None:
                    pinned = c
                else:
                    others.append(c)
            w_ranked = ([pinned] + others) if pinned else w_derived
            w_ranked = [{**c, "rank_after_primary": i+1} for i, c in enumerate(w_ranked)]
        else:
            w_ranked = w_derived
        w_r = _gt_rank(w_ranked, gt_ik)
        llm_derived = derive_llm_rank(w_ranked, llm_indices, head_k=head_k)
        record_pred_ik = r.get("predicted_inchikey_first_block")
        if record_pred_ik:
            pinned = None; others = []
            for c in llm_derived:
                if c.get("ik14") == record_pred_ik and pinned is None:
                    pinned = c
                else:
                    others.append(c)
            l_ranked = ([pinned] + others) if pinned else llm_derived
            l_ranked = [{**c, "rank_after_primary": i+1} for i, c in enumerate(l_ranked)]
        else:
            l_ranked = llm_derived
        l_r = _gt_rank(l_ranked, gt_ik)
        msclip_ranks.append(ms_r); weighted_ranks.append(w_r); llm_ranks.append(l_r)
        sids.append(sid)
    return msclip_ranks, weighted_ranks, llm_ranks, sids


def _summary_row(name: str, benchmark: str, ranks: list[int | None]) -> dict:
    n = len(ranks)
    reach_ranks = [r for r in ranks if r is not None]
    row = {"config": name, "benchmark": benchmark, "n": n,
           "n_reachable": len(reach_ranks)}
    for k in (1, 3, 5, 10, 20):
        row[f"top{k}_acc_pct"] = round(100 * topk_acc(ranks, k), 2)
    row["mrr"] = round(mrr(ranks), 4)
    row["mrr_reachable"] = round(
        sum(1.0/r for r in reach_ranks) / len(reach_ranks), 4
    ) if reach_ranks else 0.0
    return row


def _paired_wilcoxon(a_ranks: list[int | None], b_ranks: list[int | None],
                     label: str) -> dict:
    rr_a = [(1.0/r) if r else 0.0 for r in a_ranks]
    rr_b = [(1.0/r) if r else 0.0 for r in b_ranks]
    diffs = [bb - aa for aa, bb in zip(rr_a, rr_b)]
    n_pos = sum(1 for d in diffs if d > 0)
    n_neg = sum(1 for d in diffs if d < 0)
    n_zero = sum(1 for d in diffs if d == 0)
    if n_pos + n_neg == 0:
        p = 1.0
    else:
        p = float(wilcoxon(diffs, zero_method="wilcox", alternative="two-sided").pvalue)
    return {
        "comparison": label,
        "n_paired": len(diffs),
        "n_B_better_rr": n_pos,
        "n_A_better_rr": n_neg,
        "n_tied": n_zero,
        "mean_delta_rr_BminusA": round(sum(diffs)/len(diffs), 5),
        "mean_mrr_A": round(sum(rr_a)/len(rr_a), 4),
        "mean_mrr_B": round(sum(rr_b)/len(rr_b), 4),
        "wilcoxon_p": round(p, 4) if p >= 1e-4 else f"{p:.2e}",
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    root = Path("data/eval/casmi")
    out = Path("data/paper_figures")
    out.mkdir(parents=True, exist_ok=True)

    casmi2022_root = Path("/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2022/preprocessed/casmi2022")
    casmi2016_root = Path("/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2016/category2")

    logger.info("loading CASMI 2022 specs ...")
    spec_2022 = {s.spectrum_id: s for s in load_casmi_2022_specs(casmi2022_root)}
    logger.info("loading CASMI 2016 cat2 specs ...")
    spec_2016 = {s.spectrum_id: s for s in load_casmi_2016_cat2_specs(casmi2016_root)}

    logger.info("deriving CASMI 2022 ranks (n=%d)", len(spec_2022))
    ms2022, w2022, l2022, sids2022 = _ranks_for_benchmark(
        llm_jsonl=root / "2022_llm_reranker_v2" / "casmi_identifications.jsonl",
        weighted_anchor_jsonl=root / "2022_conditional" / "casmi_identifications.jsonl",
        spec_by_id=spec_2022,
    )
    logger.info("deriving CASMI 2016 cat2 ranks (n=%d)", len(spec_2016))
    ms2016, w2016, l2016, sids2016 = _ranks_for_benchmark(
        llm_jsonl=root / "2016_cat2_llm_reranker" / "casmi_identifications.jsonl",
        weighted_anchor_jsonl=root / "2016_cat2_conditional" / "casmi_identifications.jsonl",
        spec_by_id=spec_2016,
    )

    # Combined n=378.
    ms_all = ms2022 + ms2016
    w_all = w2022 + w2016
    l_all = l2022 + l2016
    sids_all = sids2022 + sids2016

    # Per-benchmark + combined summary rows
    summary_rows = []
    for name, ranks2022, ranks2016, ranks_all in [
        ("msclip_only", ms2022, ms2016, ms_all),
        ("weighted", w2022, w2016, w_all),
        ("llm_reranker", l2022, l2016, l_all),
    ]:
        summary_rows.append(_summary_row(name, "casmi_2022", ranks2022))
        summary_rows.append(_summary_row(name, "casmi_2016_cat2", ranks2016))
        summary_rows.append(_summary_row(name, "combined_n378", ranks_all))

    out_csv = out / "phase6_7c_combined_n378.csv"
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        w.writeheader(); w.writerows(summary_rows)
    logger.info("wrote %s", out_csv)

    # Pairwise Wilcoxon — per-benchmark + combined, Bonferroni-3.
    alpha = 0.05 / 3
    sig_rows = []
    for label_suffix, ms, ww, ll in [
        ("casmi_2022", ms2022, w2022, l2022),
        ("casmi_2016_cat2", ms2016, w2016, l2016),
        ("combined_n378", ms_all, w_all, l_all),
    ]:
        for a_name, b_name, a_ranks, b_ranks in [
            ("msclip_only", "weighted", ms, ww),
            ("msclip_only", "llm_reranker", ms, ll),
            ("weighted", "llm_reranker", ww, ll),
        ]:
            r = _paired_wilcoxon(a_ranks, b_ranks, f"{a_name} vs {b_name} ({label_suffix})")
            try:
                p_num = float(r["wilcoxon_p"]) if isinstance(r["wilcoxon_p"], (int, float)) else float(r["wilcoxon_p"])
            except Exception:
                p_num = 1.0
            r["bonferroni_alpha"] = round(alpha, 4)
            r["significant_at_bonf_3"] = p_num < alpha
            sig_rows.append(r)
    sig_csv = out / "phase6_7c_combined_significance.csv"
    with sig_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sig_rows[0].keys()))
        w.writeheader(); w.writerows(sig_rows)
    logger.info("wrote %s", sig_csv)

    # Pretty print
    print("=" * 90)
    print("Phase 6.7-C — top-K + MRR (CASMI 2022, CASMI 2016 cat2, COMBINED n=378)")
    print()
    print(f"{'config':<14} {'benchmark':<18} {'n':>4} {'top1':>7} {'top3':>7} {'top5':>7} {'top20':>7} {'MRR':>8} {'MRR(reach)':>11}")
    for r in summary_rows:
        print(f"  {r['config']:<14} {r['benchmark']:<18} {r['n']:>4} "
              f"{r['top1_acc_pct']:>6.2f}% {r['top3_acc_pct']:>6.2f}% "
              f"{r['top5_acc_pct']:>6.2f}% {r['top20_acc_pct']:>6.2f}% "
              f"{r['mrr']:>8.4f} {r['mrr_reachable']:>11.4f}")
    print()
    print(f"Pairwise Wilcoxon on reciprocal rank (Bonferroni α=0.0167)")
    for r in sig_rows:
        flag = " *" if r["significant_at_bonf_3"] else ""
        print(f"  {r['comparison']:<60}  n={r['n_paired']:>3}  B>A={r['n_B_better_rr']:>3} A>B={r['n_A_better_rr']:>3} tied={r['n_tied']:>3}  "
              f"meanΔ={r['mean_delta_rr_BminusA']:+.4f}  p={r['wilcoxon_p']}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
