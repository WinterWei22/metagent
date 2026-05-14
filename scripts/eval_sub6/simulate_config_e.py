"""Phase 6.5 D5a — simulate Config E (msclip primary + conditional reranker)
without rerunning library_search/SIRIUS/CFM.

For each spectrum in the dual-score cache:
  pre-rerank top-1 (by msclip)  = candidate with max msclip_rescaled
  conditional gate decision     = msclip_top1 ≥ 0.85 AND gap ≥ 0.15
    SKIP  → use msclip top-1
    TRIGGER → use Phase 6.3 B's post-rerank top-1 (predicted_smiles in narratives)

Compares Config E vs three baselines:
  - msclip primary (no rerank, OOD-realistic baseline): use msclip top-1 always
  - modcos primary (in-distribution upper bound, leakage-inflated)
  - Phase 6.3 B = msclip primary + weighted (rerank everywhere)

Outputs:
  data/paper_figures/phase6_5_config_e_simulation.csv

McNemar tests: Config E vs each baseline.
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

MSCLIP_TOP1_THRESH = 0.85
MSCLIP_GAP_THRESH = 0.15


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


def load_phase63b_predicted() -> dict[str, str | None]:
    """spectrum_id → predicted_smiles (Phase 6.3 B post-rerank top-1)."""
    out = {}
    for line in PHASE63_B.open():
        rec = json.loads(line)
        for ident in rec.get("identifications", []):
            sid = ident.get("spectrum_id")
            smi = ident.get("predicted_smiles")
            if sid is not None:
                out[sid] = smi
    return out


def mcnemar_p(a: list[bool], b: list[bool]) -> tuple[int, int, float]:
    """b_only (a wrong, b correct), c_only (a correct, b wrong), p-value."""
    n_b = sum(1 for x, y in zip(a, b) if not x and y)
    n_c = sum(1 for x, y in zip(a, b) if x and not y)
    n = n_b + n_c
    if n == 0:
        return n_b, n_c, 1.0
    return n_b, n_c, float(binomtest(min(n_b, n_c), n, p=0.5, alternative="two-sided").pvalue)


def main() -> int:
    phase63b_pred = load_phase63b_predicted()
    print(f"loaded {len(phase63b_pred)} Phase 6.3 B predictions")

    rows = []
    n_skip = n_trigger = n_no_msclip = 0
    config_e_correct = msclip_only_correct = modcos_only_correct = phase63b_correct = 0
    n_total = 0
    config_e_outcomes: list[bool] = []
    msclip_only_outcomes: list[bool] = []
    modcos_only_outcomes: list[bool] = []
    phase63b_outcomes: list[bool] = []
    for line in CACHE.open():
        rec = json.loads(line)
        if rec.get("error"): continue
        sid = rec["spectrum_id"]
        gt = rec.get("gt_inchikey_first_block")
        cands = rec.get("candidates") or []
        if not cands or not gt: continue

        # MS-CLIP primary order
        ms_cands = [c for c in cands if c.get("msclip_rescaled") is not None]
        ms_top1_score = None
        ms_gap = None
        if ms_cands:
            ms_cands_sorted = sorted(ms_cands, key=lambda c: c["msclip_rescaled"], reverse=True)
            ms_top1 = ms_cands_sorted[0]
            ms_top1_score = ms_top1["msclip_rescaled"]
            ms_top2_score = ms_cands_sorted[1]["msclip_rescaled"] if len(ms_cands_sorted) > 1 else 0.0
            ms_gap = ms_top1_score - ms_top2_score
        else:
            ms_top1 = None
            n_no_msclip += 1

        # Modcos primary order
        mc_cands = [c for c in cands if c.get("modcos") is not None]
        mc_top1 = max(mc_cands, key=lambda c: c["modcos"]) if mc_cands else None

        msclip_top1_correct = (smi_to_ik14(ms_top1["smiles"]) == gt) if ms_top1 else False
        modcos_top1_correct = (smi_to_ik14(mc_top1["smiles"]) == gt) if mc_top1 else False

        # Phase 6.3 B's post-rerank top-1
        p63b_smi = phase63b_pred.get(sid)
        p63b_correct = (smi_to_ik14(p63b_smi) == gt) if p63b_smi else False

        # Config E: conditional gate
        gate_skip = (ms_top1_score is not None and ms_top1_score >= MSCLIP_TOP1_THRESH
                     and ms_gap is not None and ms_gap >= MSCLIP_GAP_THRESH)
        if gate_skip:
            n_skip += 1
            config_e_correct_this = msclip_top1_correct
            decision = "SKIP_msclip_high_conf"
        else:
            n_trigger += 1
            # fallback to Phase 6.3 B's post-rerank top-1 (= weighted reranker)
            config_e_correct_this = p63b_correct
            decision = "TRIGGER_weighted"

        n_total += 1
        if config_e_correct_this: config_e_correct += 1
        if msclip_top1_correct: msclip_only_correct += 1
        if modcos_top1_correct: modcos_only_correct += 1
        if p63b_correct: phase63b_correct += 1
        config_e_outcomes.append(config_e_correct_this)
        msclip_only_outcomes.append(msclip_top1_correct)
        modcos_only_outcomes.append(modcos_top1_correct)
        phase63b_outcomes.append(p63b_correct)

        rows.append({
            "spectrum_id": sid,
            "msclip_top1_score": ms_top1_score,
            "msclip_gap": ms_gap,
            "decision": decision,
            "msclip_top1_correct": int(msclip_top1_correct),
            "modcos_top1_correct": int(modcos_top1_correct),
            "phase63b_correct": int(p63b_correct),
            "config_e_correct": int(config_e_correct_this),
        })

    print(f"\nspectra evaluated: {n_total}")
    print(f"  conditional decisions: SKIP={n_skip}, TRIGGER={n_trigger}, no_msclip(default trigger)={n_no_msclip}")
    print(f"  trigger rate: {100*n_trigger/n_total:.1f}%")

    print(f"\n=== id_acc on {n_total} spectra ===")
    print(f"  modcos primary (in-distribution upper bound):  {modcos_only_correct}/{n_total} = {100*modcos_only_correct/n_total:.2f}%")
    print(f"  msclip primary (OOD-realistic baseline):       {msclip_only_correct}/{n_total} = {100*msclip_only_correct/n_total:.2f}%")
    print(f"  Phase 6.3 B (msclip + weighted everywhere):    {phase63b_correct}/{n_total} = {100*phase63b_correct/n_total:.2f}%")
    print(f"  Config E (msclip + CONDITIONAL):              {config_e_correct}/{n_total} = {100*config_e_correct/n_total:.2f}%")

    print(f"\n=== Δ vs each baseline (paired McNemar) ===")
    comparisons = [
        ("Config_E vs msclip_only", config_e_outcomes, msclip_only_outcomes),
        ("Config_E vs phase63b (B)", config_e_outcomes, phase63b_outcomes),
        ("Config_E vs modcos_only", config_e_outcomes, modcos_only_outcomes),
    ]
    sig_rows = []
    for label, e_out, b_out in comparisons:
        b_only, c_only, p = mcnemar_p(b_out, e_out)
        delta = sum(e_out) - sum(b_out)
        delta_pp = round(100*delta/n_total, 2)
        ci_low_pp = round(100*(delta - 1.96 * (b_only + c_only)**0.5) / n_total, 2)
        ci_high_pp = round(100*(delta + 1.96 * (b_only + c_only)**0.5) / n_total, 2)
        print(f"  {label:<32} Δ={delta:+d}({delta_pp:+.2f}pp)  b={b_only} c={c_only}  p={p:.4f}")
        sig_rows.append({
            "comparison": label,
            "n_paired": n_total,
            "delta_spec": delta,
            "delta_pp": delta_pp,
            "ci95_lo_pp": ci_low_pp,
            "ci95_hi_pp": ci_high_pp,
            "mcnemar_b": b_only,
            "mcnemar_c": c_only,
            "p_value": round(p, 4) if p >= 0.0001 else f"{p:.2e}",
        })

    # Per-decision-bucket analysis
    print(f"\n=== Within trigger subset (Config E used Phase 6.3 B's rerank result) ===")
    trig_rows = [r for r in rows if r["decision"] == "TRIGGER_weighted"]
    if trig_rows:
        ms_correct = sum(r["msclip_top1_correct"] for r in trig_rows)
        ce_correct = sum(r["config_e_correct"] for r in trig_rows)
        n_t = len(trig_rows)
        print(f"  trigger subset: n={n_t}")
        print(f"    msclip-only:     {ms_correct}/{n_t} = {100*ms_correct/n_t:.2f}%")
        print(f"    Config E (=B):   {ce_correct}/{n_t} = {100*ce_correct/n_t:.2f}%")
        print(f"    Δ:               {ce_correct - ms_correct:+d}  ({100*(ce_correct-ms_correct)/n_t:+.2f}pp)")

    print(f"\n=== Within skip subset (Config E used msclip top-1, no rerank) ===")
    skip_rows = [r for r in rows if r["decision"] == "SKIP_msclip_high_conf"]
    if skip_rows:
        ms_correct = sum(r["msclip_top1_correct"] for r in skip_rows)
        ce_correct = sum(r["config_e_correct"] for r in skip_rows)
        b_correct = sum(r["phase63b_correct"] for r in skip_rows)
        n_s = len(skip_rows)
        print(f"  skip subset: n={n_s}")
        print(f"    msclip-only (= Config E):  {ms_correct}/{n_s} = {100*ms_correct/n_s:.2f}%")
        print(f"    Phase 6.3 B (would-rerank): {b_correct}/{n_s} = {100*b_correct/n_s:.2f}%")
        print(f"    saved by skip:              {ms_correct - b_correct:+d}  ({100*(ms_correct-b_correct)/n_s:+.2f}pp)")

    out_csv = OUT / "phase6_5_config_e_simulation.csv"
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\nwrote per-spectrum sim to {out_csv}")

    sig_csv = OUT / "phase6_5_config_e_significance.csv"
    with sig_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sig_rows[0].keys()))
        w.writeheader(); w.writerows(sig_rows)
    print(f"wrote significance to {sig_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
