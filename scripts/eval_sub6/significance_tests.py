"""Phase 6.5 D3 — pairwise statistical significance across 9 configs.

For each pair (config_X vs config_Y), pairs spectra by spectrum_id (intersect),
runs:
  - McNemar's test on the 2x2 contingency of correct/incorrect (b vs c discordant)
  - Paired bootstrap CI on Δ id_acc (10K resamples, percentile method)

Configs (rerank-after id_acc, post-rerank top-1 from sub6a_narratives.jsonl):
  1. gnps_only (Phase 6.1 / Phase 6.2 Config A baseline)  — modcos top-1, no rerank
  2. msclip_fused (Phase 6.1 fused max-fusion)            — gnps + msclip max-fusion
  3. cfmid_only (Phase 6.2 Config C)                      — modcos + CFM-ID weighted
  4. sirius_only (Phase 6.2 Config B)                     — modcos + SIRIUS gate
  5. full (Phase 6.2 Config D)                            — modcos + SIRIUS + CFM weighted
  6. msclip_weighted (Phase 6.3 Config B)                 — msclip primary + weighted
  7. msclip_llm (Phase 6.3 Config C)                      — msclip primary + LLM
  8. (synthetic) pre_rerank_modcos                        — pre-rerank top-1 by modcos (peak_evidence)

Outputs:
  data/paper_figures/phase6_5_significance.csv

Bonferroni: 8 configs × 7 / 2 = 28 unordered pairs → α = 0.05 / 28 = 0.00179.

Pure read-only. No LLM, no SIRIUS/CFM rerun.
"""
from __future__ import annotations

import csv
import json
import random
import statistics
from pathlib import Path
from scipy.stats import binomtest

ROOT = Path("/home/weiwentao/workspace/llm_agent_metabolomics/metagent_day1_v5")
OUT = ROOT / "data/paper_figures"

# Map config label → narrative JSONL path
NARR_PATHS = {
    "gnps_only": ROOT / "data/eval/sub6/v2/sub6a_real/sub6a_narratives.jsonl",
    "msclip_fused_6.1": None,   # filled below if exists
    "cfmid_only": ROOT / "data/eval/sub6/v2_phase6_2/cfmid/sub6a_narratives.jsonl",
    "sirius_only": ROOT / "data/eval/sub6/v2_phase6_2/sirius/sub6a_narratives.jsonl",
    "full_6.2": ROOT / "data/eval/sub6/v2_phase6_2/full/sub6a_narratives.jsonl",
    "msclip_weighted_6.3": ROOT / "data/eval/sub6/v2_phase6_3/B_msclip_weighted/sub6a_narratives.jsonl",
    "msclip_llm_6.3": ROOT / "data/eval/sub6/v2_phase6_3/C_msclip_llm/sub6a_narratives.jsonl",
}

# Optional: Phase 6.1 msclip_fused if its file exists
P61_FUSED = ROOT / "data/eval/sub6/v2_phase6_1/sub6a_narratives.jsonl"
if not P61_FUSED.exists():
    # try alternative path
    for p in [ROOT / "data/eval/sub6/v2/sub6a_real_msclip_fused/sub6a_narratives.jsonl",
              ROOT / "data/eval/sub6/v2_phase6_1/fused/sub6a_narratives.jsonl"]:
        if p.exists():
            P61_FUSED = p; break

if P61_FUSED.exists():
    NARR_PATHS["msclip_fused_6.1"] = P61_FUSED
else:
    NARR_PATHS.pop("msclip_fused_6.1", None)

PE_DIR_FULL = ROOT / "data/eval/sub6/v2_phase6_2/full/peak_evidence"


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


def load_post_rerank(path: Path) -> dict[str, bool]:
    """spectrum_id → correct_top1 (bool, post-rerank)."""
    out = {}
    if not path or not path.exists():
        return out
    for line in path.open():
        rec = json.loads(line)
        for ident in rec.get("identifications", []):
            sid = ident.get("spectrum_id")
            ok = ident.get("correct_top1")
            if sid is not None and ok is not None:
                out[sid] = bool(ok)
    return out


def load_pre_rerank_from_pe() -> dict[str, bool]:
    """pre-rerank top-1 = candidates_evaluated max(modcos)."""
    out = {}
    # GT lookup from full narratives
    gt_lookup = {}
    full_narr = NARR_PATHS["full_6.2"]
    for line in full_narr.open():
        rec = json.loads(line)
        for ident in rec.get("identifications", []):
            sid = ident.get("spectrum_id"); gt = ident.get("gt_inchikey_first_block")
            if sid and gt: gt_lookup[sid] = gt
    for f in PE_DIR_FULL.glob("*.json"):
        pe = json.loads(f.read_text())
        sid = pe.get("spectrum_id"); cands = pe.get("candidates_evaluated") or []
        if not cands: continue
        gt = gt_lookup.get(sid)
        if not gt: continue
        top = max(cands, key=lambda c: c.get("modcos") or 0.0)
        ik = smi_to_ik14(top.get("smiles"))
        out[sid] = (ik == gt)
    return out


def mcnemar_pvalue(b: int, c: int) -> float:
    """Two-sided exact McNemar via binomial on discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return float(binomtest(k, n, p=0.5, alternative="two-sided").pvalue)


def paired_bootstrap_ci(x: list[bool], y: list[bool], *, n_boot: int = 10_000, alpha: float = 0.05, seed: int = 0):
    """95% percentile CI on Δ acc (y - x), paired."""
    rng = random.Random(seed)
    n = len(x)
    if n == 0:
        return (0.0, 0.0, 0.0)
    deltas = []
    indices = range(n)
    for _ in range(n_boot):
        sample = [rng.randrange(n) for _ in range(n)]
        sx = sum(x[i] for i in sample)
        sy = sum(y[i] for i in sample)
        deltas.append((sy - sx) / n)
    deltas.sort()
    lo = deltas[int(n_boot * alpha / 2)]
    hi = deltas[int(n_boot * (1 - alpha / 2))]
    obs = (sum(y) - sum(x)) / n
    return obs, lo, hi


def main() -> int:
    # Load all configs
    config_data: dict[str, dict[str, bool]] = {}
    for label, path in NARR_PATHS.items():
        if path is None:
            continue
        d = load_post_rerank(path)
        if d:
            config_data[label] = d
    config_data["pre_rerank_modcos"] = load_pre_rerank_from_pe()
    print("config -> n_spectra")
    for k, v in config_data.items():
        print(f"  {k}: {len(v)}, n_correct={sum(v.values())}")

    labels = list(config_data.keys())
    rows = []
    n_pairs = 0
    for i, A in enumerate(labels):
        for B in labels[i+1:]:
            ka = set(config_data[A].keys()); kb = set(config_data[B].keys())
            shared = sorted(ka & kb)
            if not shared:
                continue
            x = [config_data[A][s] for s in shared]
            y = [config_data[B][s] for s in shared]
            n_paired = len(shared)
            cor_a = sum(x); cor_b = sum(y)
            # McNemar: b = A correct & B wrong; c = A wrong & B correct
            b = sum(1 for xi, yi in zip(x, y) if xi and not yi)
            c = sum(1 for xi, yi in zip(x, y) if not xi and yi)
            p = mcnemar_pvalue(b, c)
            obs, lo, hi = paired_bootstrap_ci(x, y, n_boot=10_000)
            rows.append({
                "A": A, "B": B,
                "n_paired": n_paired,
                "A_correct": cor_a,
                "B_correct": cor_b,
                "delta_spec": cor_b - cor_a,
                "delta_pp": round(100 * (cor_b - cor_a) / n_paired, 2),
                "ci95_lo_pp": round(100 * lo, 2),
                "ci95_hi_pp": round(100 * hi, 2),
                "mcnemar_b": b, "mcnemar_c": c,
                "p_value": round(p, 4) if p >= 0.0001 else f"{p:.2e}",
            })
            n_pairs += 1

    # Bonferroni
    alpha = 0.05
    bonf_alpha = alpha / n_pairs if n_pairs else alpha
    for r in rows:
        try:
            pv = float(r["p_value"]) if not isinstance(r["p_value"], (int, float)) else r["p_value"]
        except ValueError:
            # scientific notation
            pv = float(r["p_value"])
        r["sig_p_lt_0.05"] = "yes" if pv < 0.05 else "no"
        r["sig_after_bonf"] = "yes" if pv < bonf_alpha else "no"

    out = OUT / "phase6_5_significance.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\nwrote {out} with {n_pairs} pairs")
    print(f"Bonferroni α = 0.05 / {n_pairs} = {bonf_alpha:.5f}")
    print()
    print("=== significant after Bonferroni ===")
    for r in rows:
        if r["sig_after_bonf"] == "yes":
            print(f"  {r['A']} vs {r['B']}: Δ={r['delta_pp']:>+5}pp [{r['ci95_lo_pp']:.2f}, {r['ci95_hi_pp']:.2f}] p={r['p_value']}  n={r['n_paired']}")
    print()
    print("=== NOT significant after Bonferroni (Δ may be noise) ===")
    for r in rows:
        if r["sig_after_bonf"] == "no":
            print(f"  {r['A']} vs {r['B']}: Δ={r['delta_pp']:>+5}pp [{r['ci95_lo_pp']:.2f}, {r['ci95_hi_pp']:.2f}] p={r['p_value']}  n={r['n_paired']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
