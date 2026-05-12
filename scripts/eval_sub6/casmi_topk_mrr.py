"""Phase 6.7-A — derive top-K accuracy + MRR for msclip / weighted / llm.

Reads:
  data/eval/casmi/2022_llm_reranker_v2/casmi_identifications.jsonl
    (must include ranked_candidates + llm_rerank.ranked_indices per record)

Derives three ranked candidate lists per spec:
  - msclip_only_rank: ranked_candidates as-is (top-K by msclip score)
  - weighted_rank   : msclip top-K reordered by Phase 6.2 evidence_score
                      formula = 0.4·modcos + 0.3·CFM_cosine + 0.2·mass_match
                      For CASMI: modcos=0, mass_match=1 (constant), so the
                      weighted reorder reduces to CFM-cosine over top-5.
                      Falls back to msclip rank for K>5.
                      *** CFM_cosine is read from disk cache (~100% hit rate) ***
  - llm_rank        : msclip top-K reordered by llm_rerank.ranked_indices;
                      for K>5 (= rerank_top_k default), unchanged from msclip.

Computes per-config:
  - top1 / top3 / top5 / top10 / top20 accuracy
  - MRR = mean(1/rank if GT in top-20 else 0)
  - On the reachable subset (GT IK14 present in any rank ≤ 20)

Pairwise paired Wilcoxon signed-rank on reciprocal rank.

Writes:
  data/paper_figures/phase6_7a_topk_mrr.csv             — main per-config table
  data/paper_figures/phase6_7a_topk_mrr_significance.csv — pairwise tests
  data/paper_figures/phase6_7a_per_spec_ranks.csv       — per-spec audit
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from pathlib import Path

from scipy.stats import wilcoxon

logger = logging.getLogger(__name__)

# Phase 6.2 evidence_score weights (Phase 6.6 §3.3.1).
W_MODCOS = 0.4
W_CFM = 0.3
W_MASS = 0.2
W_PATHWAY = 0.1


def _cfm_cache_key(smiles: str, adduct: str, ionization_mode: str,
                   collision_energies: tuple[float, ...]) -> str:
    """Reproduce the cache-key hash from evaluation/sub6/rerank.py:_cfmid_cache_key.

    Format: ``{canonical_smiles}|{adduct}|{ion_mode}|{e1,e2,e3}`` SHA-1.
    """
    try:
        from tools.molecule_gen.canonicalize import canonicalize_smiles
        canon = canonicalize_smiles(smiles) or smiles
    except Exception:
        # Fallback to RDKit canonicalisation directly.
        try:
            from rdkit import Chem
            mol = Chem.MolFromSmiles(smiles)
            canon = Chem.MolToSmiles(mol) if mol else smiles
        except Exception:
            canon = smiles
    payload = f"{canon}|{adduct}|{ionization_mode}|{','.join(f'{e:.1f}' for e in collision_energies)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _modified_cosine(experimental_peaks: list[list[float]], precursor_mz: float,
                     predicted_peaks: list[list[float]], predicted_precursor_mz: float) -> float:
    """Use the same modified_cosine_score that production weighted reranker uses."""
    from tools.library_search.scoring import modified_cosine_score
    if not experimental_peaks or not predicted_peaks:
        return 0.0
    q_mz = [p[0] for p in experimental_peaks]
    q_int = [p[1] for p in experimental_peaks]
    r_mz = [p[0] for p in predicted_peaks]
    r_int = [p[1] for p in predicted_peaks]
    return float(modified_cosine_score(
        query_mz=q_mz, query_intensity=q_int, query_precursor_mz=precursor_mz,
        ref_mz=r_mz, ref_intensity=r_int, ref_precursor_mz=predicted_precursor_mz,
    ))


def _read_cfm_cache(cache_dir: Path, key: str) -> dict | None:
    fp = cache_dir / f"{key}.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text())
    except Exception:
        return None


def _gt_rank(ranked: list[dict], gt_ik14: str | None) -> int | None:
    """1-based rank of GT IK14 in the ranked candidate list, or None."""
    if not gt_ik14:
        return None
    for r, c in enumerate(ranked, start=1):
        if c.get("ik14") == gt_ik14:
            return r
    return None


def derive_weighted_rank(ranked_msclip: list[dict],
                        spectrum_peaks: list[list[float]] | None,
                        precursor_mz: float,
                        adduct: str | None,
                        ionization_mode: str,
                        cfm_cache_dir: Path,
                        head_k: int = 5) -> list[dict]:
    """Return ranked_msclip with the top-K head reordered by evidence_score.
    Tail (rank > head_k) is preserved from msclip order.

    On CASMI: modcos=0, mass_match=1 (constant), pathway_presence=0, so
    evidence_score = 0.3 * CFM_cosine. We pull CFM predicted peaks from
    disk cache and compute spectrum cosine vs the experimental peaks.
    """
    head = ranked_msclip[:head_k]
    tail = ranked_msclip[head_k:]
    if not spectrum_peaks or not adduct:
        # No way to compute CFM cosine — preserve msclip order.
        return ranked_msclip
    scored = []
    for c in head:
        smi = c.get("smiles") or ""
        if not smi:
            scored.append((0.0, c))
            continue
        key = _cfm_cache_key(smi, adduct, ionization_mode, (10.0, 20.0, 40.0))
        cached = _read_cfm_cache(cfm_cache_dir, key)
        if cached is None:
            scored.append((0.0, c))
            continue
        # Cached file is the PredictSpectrumResponse model_dump directly.
        pred = cached.get("predicted") or {}
        peaks: list[list[float]] = []
        if "mz" in pred and "intensity" in pred:
            peaks = [[float(m), float(i)] for m, i in zip(pred["mz"], pred["intensity"])]
        pred_precursor = float(pred.get("precursor_mz") or precursor_mz)
        cfm_cos = _modified_cosine(spectrum_peaks, precursor_mz, peaks, pred_precursor)
        # Production reads cand.score, which on CASMI = msclip (inhouse
        # retriever's normalised score). Phase 6.6 §3.3.1's framing of
        # "modcos=0" was loose — production evidence_score's `candidate_score`
        # arg receives the msclip-derived score for these candidates.
        primary = float(c.get("score") or c.get("msclip") or 0.0)
        evidence = W_MODCOS * primary + W_CFM * cfm_cos + W_MASS * 1.0  # pathway=0
        scored.append((evidence, c))
    scored.sort(key=lambda x: -x[0])
    reordered_head = [c for _, c in scored]
    # rebuild rank_after_primary so the merged list is sequential
    out = []
    for r, c in enumerate(reordered_head + tail, start=1):
        d = dict(c); d["rank_after_primary"] = r
        out.append(d)
    return out


def derive_llm_rank(ranked_msclip: list[dict],
                    llm_ranked_indices: list[int],
                    head_k: int = 5) -> list[dict]:
    """Apply LLM's ranked_indices to the top-K head of msclip ordering.

    The LLM saw `surviving[:head_k]` and emitted `ranked_indices` as a
    permutation over those `head_k` positions. Tail (rank > head_k) is
    preserved from msclip.
    """
    head = ranked_msclip[:head_k]
    tail = ranked_msclip[head_k:]
    if not llm_ranked_indices:
        return ranked_msclip
    seen = set()
    reordered_head = []
    for idx in llm_ranked_indices:
        if 0 <= idx < len(head) and idx not in seen:
            reordered_head.append(head[idx])
            seen.add(idx)
    for i, c in enumerate(head):
        if i not in seen:
            reordered_head.append(c)
    out = []
    for r, c in enumerate(reordered_head + tail, start=1):
        d = dict(c); d["rank_after_primary"] = r
        out.append(d)
    return out


def topk_acc(ranks: list[int | None], k: int) -> float:
    """Fraction of specs where GT rank ≤ k. None counts as miss (rank=∞)."""
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def mrr(ranks: list[int | None]) -> float:
    """Mean Reciprocal Rank. None → 0."""
    if not ranks:
        return 0.0
    return sum(1.0 / r for r in ranks if r is not None) / len(ranks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-jsonl", type=Path,
                    default=Path("data/eval/casmi/2022_llm_reranker_v2/casmi_identifications.jsonl"))
    ap.add_argument("--weighted-anchor-jsonl", type=Path,
                    default=Path("data/eval/casmi/2022_conditional/casmi_identifications.jsonl"),
                    help="Phase 6.6 D3 weighted predictions, used to anchor weighted top-1.")
    ap.add_argument("--cfm-cache-dir", type=Path, default=Path("data/cache/cfmid"))
    ap.add_argument("--out", type=Path, default=Path("data/paper_figures"))
    ap.add_argument("--head-k", type=int, default=5,
                    help="Reranker scope; head_k candidates get reordered, tail stays.")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Each record needs: ranked_candidates, llm_rerank.ranked_indices, gt_inchikey_first_block,
    # casmi_formula, plus a way to look up experimental spectrum + adduct.
    # CASMI loader is deterministic; we re-load the specs lazily to get peaks+adduct.
    from evaluation.sub6.casmi_loader import load_casmi_2022_specs
    casmi_root = Path("/data/weiwentao/llm_agent_metabolomics/CASMI/casmi_2022/preprocessed/casmi2022")
    spec_by_id = {s.spectrum_id: s for s in load_casmi_2022_specs(casmi_root)}
    logger.info("loaded %d CASMI specs for adduct/peak lookup", len(spec_by_id))

    # Load Phase 6.6 D3 weighted predictions for top-1 anchoring.
    weighted_anchor: dict[str, str | None] = {}
    if args.weighted_anchor_jsonl.exists():
        for line in args.weighted_anchor_jsonl.open():
            w = json.loads(line)
            weighted_anchor[w["spectrum_id"]] = w.get("predicted_inchikey_first_block")
        logger.info("loaded %d weighted-anchor records", len(weighted_anchor))

    per_spec_rows = []
    msclip_ranks: list[int | None] = []
    weighted_ranks: list[int | None] = []
    llm_ranks: list[int | None] = []
    sid_order: list[str] = []

    for line in args.input_jsonl.open():
        r = json.loads(line)
        sid = r["spectrum_id"]
        gt_ik = r.get("gt_inchikey_first_block")
        ranked = r.get("ranked_candidates") or []
        if not ranked:
            logger.warning("%s has no ranked_candidates — skipping", sid)
            continue
        llm_indices = ((r.get("llm_rerank") or {}).get("ranked_indices")) or []

        sp = spec_by_id.get(sid)
        if sp is None:
            logger.warning("%s not in casmi loader — skipping", sid)
            continue

        msclip_rank = _gt_rank(ranked, gt_ik)
        # Normalise experimental peaks the same way production does
        # (task_spectrum_to_schema normalises to base peak = 1.0).
        if sp.peaks:
            base = max(p[1] for p in sp.peaks)
            exp_peaks = [[float(p[0]), float(p[1]) / base if base > 0 else 0.0] for p in sp.peaks]
        else:
            exp_peaks = []
        weighted_ranked_derived = derive_weighted_rank(
            ranked, spectrum_peaks=exp_peaks, precursor_mz=sp.precursor_mz,
            adduct=sp.adduct, ionization_mode=sp.ion_mode,
            cfm_cache_dir=args.cfm_cache_dir, head_k=args.head_k,
        )
        # Anchor weighted top-1 to Phase 6.6 D3 actual prediction.
        wpred = weighted_anchor.get(sid)
        if wpred:
            pinned = None; others = []
            for c in weighted_ranked_derived:
                if c.get("ik14") == wpred and pinned is None:
                    pinned = c
                else:
                    others.append(c)
            weighted_ranked = ([pinned] + others) if pinned else weighted_ranked_derived
            weighted_ranked = [{**c, "rank_after_primary": i+1} for i, c in enumerate(weighted_ranked)]
        else:
            weighted_ranked = weighted_ranked_derived
        weighted_rank = _gt_rank(weighted_ranked, gt_ik)
        # Phase 6.7-A pipeline: LLM saw the CFM-evidence-reordered top-K
        # (because --rerank-with cfmid runs BEFORE the LLM in identification.py).
        # Production weighted-reorder uses matchms ModifiedCosine which our
        # derivation approximates closely but not byte-for-byte (~6/170 specs
        # diverge). To get authoritative LLM top-1 we anchor to the record's
        # predicted_inchikey_first_block, then fill ranks 2..K from the
        # weighted-derived order with the LLM top-1 IK moved to position 1.
        llm_ranked_derived = derive_llm_rank(weighted_ranked, llm_indices, head_k=args.head_k)
        record_pred_ik = r.get("predicted_inchikey_first_block")
        if record_pred_ik:
            # Move record_pred_ik to rank 1 of the derived list; preserve the rest.
            pinned_first = None
            others = []
            for c in llm_ranked_derived:
                if c.get("ik14") == record_pred_ik and pinned_first is None:
                    pinned_first = c
                else:
                    others.append(c)
            if pinned_first is not None:
                llm_ranked = [pinned_first] + others
                # rebuild rank
                llm_ranked = [{**c, "rank_after_primary": i+1} for i, c in enumerate(llm_ranked)]
            else:
                llm_ranked = llm_ranked_derived
        else:
            llm_ranked = llm_ranked_derived
        llm_rank = _gt_rank(llm_ranked, gt_ik)

        msclip_ranks.append(msclip_rank)
        weighted_ranks.append(weighted_rank)
        llm_ranks.append(llm_rank)
        sid_order.append(sid)

        per_spec_rows.append({
            "spectrum_id": sid,
            "formula": r.get("casmi_formula"),
            "gt_ik14": gt_ik,
            "msclip_rank": msclip_rank,
            "weighted_rank": weighted_rank,
            "llm_rank": llm_rank,
            "msclip_rr": (1.0 / msclip_rank) if msclip_rank else 0.0,
            "weighted_rr": (1.0 / weighted_rank) if weighted_rank else 0.0,
            "llm_rr": (1.0 / llm_rank) if llm_rank else 0.0,
        })

    # Per-spec audit CSV.
    with (args.out / "phase6_7a_per_spec_ranks.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_spec_rows[0].keys()))
        w.writeheader(); w.writerows(per_spec_rows)
    logger.info("wrote per-spec ranks CSV")

    # Main aggregate table.
    n_total = len(msclip_ranks)
    n_reachable = sum(1 for r in msclip_ranks if r is not None)
    logger.info("n_total=%d, reachable (GT in top-20 of msclip)=%d", n_total, n_reachable)

    main_rows = []
    for name, ranks in [("msclip_only", msclip_ranks),
                        ("weighted",    weighted_ranks),
                        ("llm_reranker", llm_ranks)]:
        row = {"config": name, "n": n_total}
        for k in (1, 3, 5, 10, 20):
            row[f"top{k}_acc_pct"] = round(100 * topk_acc(ranks, k), 2)
        row["mrr"] = round(mrr(ranks), 4)
        # Reachable-subset MRR (denominator = specs where GT is in any rank).
        reachable_ranks = [r for r in ranks if r is not None]
        row["mrr_reachable"] = round(sum(1.0/r for r in reachable_ranks) / len(reachable_ranks), 4) if reachable_ranks else 0.0
        row["n_reachable"] = len(reachable_ranks)
        main_rows.append(row)
    with (args.out / "phase6_7a_topk_mrr.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(main_rows[0].keys()))
        w.writeheader(); w.writerows(main_rows)
    logger.info("wrote main topk_mrr CSV")

    # Pairwise paired Wilcoxon on reciprocal rank.
    sig_rows = []
    rr_vec = {
        "msclip_only": [(1.0/r) if r else 0.0 for r in msclip_ranks],
        "weighted":    [(1.0/r) if r else 0.0 for r in weighted_ranks],
        "llm_reranker":[(1.0/r) if r else 0.0 for r in llm_ranks],
    }
    pairs = [("msclip_only","weighted"), ("msclip_only","llm_reranker"),
             ("weighted","llm_reranker")]
    alpha = 0.05 / len(pairs)
    for A, B in pairs:
        a = rr_vec[A]; b = rr_vec[B]
        diffs = [bb - aa for aa, bb in zip(a, b)]
        n_pos = sum(1 for d in diffs if d > 0)
        n_neg = sum(1 for d in diffs if d < 0)
        n_zero = sum(1 for d in diffs if d == 0)
        if n_pos + n_neg == 0:
            p = 1.0
        else:
            p = float(wilcoxon(diffs, zero_method="wilcox", alternative="two-sided").pvalue)
        sig_rows.append({
            "comparison": f"{A} vs {B}",
            "n_paired": len(a),
            "n_B_better_rr": n_pos,
            "n_A_better_rr": n_neg,
            "n_tied": n_zero,
            "mean_delta_rr_BminusA": round(sum(diffs)/len(diffs), 5),
            "mean_mrr_A": round(sum(a)/len(a), 4),
            "mean_mrr_B": round(sum(b)/len(b), 4),
            "wilcoxon_p": round(p, 4) if p >= 1e-4 else f"{p:.2e}",
            "significant_at_bonf_alpha": p < alpha,
        })
    with (args.out / "phase6_7a_topk_mrr_significance.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sig_rows[0].keys()))
        w.writeheader(); w.writerows(sig_rows)
    logger.info("wrote significance CSV")

    # Pretty print
    print("=" * 80)
    print(f"Phase 6.7-A — CASMI 2022 top-K + MRR (n={n_total}, reachable={n_reachable})")
    print()
    print(f"{'config':<14} {'top1':>6} {'top3':>6} {'top5':>6} {'top10':>6} {'top20':>6} {'MRR':>7} {'MRR(reach)':>10}")
    for r in main_rows:
        print(f"  {r['config']:<14} {r['top1_acc_pct']:>5.2f}% {r['top3_acc_pct']:>5.2f}% "
              f"{r['top5_acc_pct']:>5.2f}% {r['top10_acc_pct']:>5.2f}% {r['top20_acc_pct']:>5.2f}% "
              f"{r['mrr']:>7.4f} {r['mrr_reachable']:>10.4f}")
    print()
    print(f"Pairwise paired Wilcoxon on reciprocal rank (Bonferroni α={alpha:.4f})")
    for r in sig_rows:
        flag = " *" if r["significant_at_bonf_alpha"] else ""
        print(f"  {r['comparison']:<32}  B>A={r['n_B_better_rr']:>3} B<A={r['n_A_better_rr']:>3} tied={r['n_tied']:>3}  "
              f"meanΔ={r['mean_delta_rr_BminusA']:+.4f}  p={r['wilcoxon_p']}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
