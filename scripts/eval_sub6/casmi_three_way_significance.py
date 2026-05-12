"""Phase 6.7 — 3-way McNemar + cross-benchmark coherence (CASMI 2022).

Reads three per-spec JSONL files:
  data/eval/casmi/2022_msclip_only/casmi_identifications.jsonl   (D2, Phase 6.6)
  data/eval/casmi/2022_conditional/casmi_identifications.jsonl   (D3 weighted, Phase 6.6)
  data/eval/casmi/2022_llm_reranker/casmi_identifications.jsonl  (D3 llm, Phase 6.7)

Writes:
  data/paper_figures/phase6_7_casmi_three_way.csv     — 3-row main table
  data/paper_figures/phase6_7_significance.csv        — 3 pairwise McNemar + Bonferroni
  data/paper_figures/phase6_7_cross_benchmark.csv     — Sub-6A v2 × CASMI 2022 coherence
  data/paper_figures/phase6_7_casmi_per_spec.csv      — per-spec across-config audit
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scipy.stats import binomtest

CONFIGS = [
    ("msclip_only",  "2022_msclip_only",  "none"),
    ("weighted",     "2022_conditional",  "sirius,cfmid (gate gap≥0.05 always-trigger)"),
    ("llm_reranker", "2022_llm_reranker", "cfmid + LLM (opus47)"),
]


def _load(path: Path) -> dict[str, dict]:
    return {json.loads(l)["spectrum_id"]: json.loads(l) for l in path.open()}


def _is_correct(rec: dict) -> bool:
    return rec.get("correct_top1") is True


def mcnemar_p(a: list[bool], b: list[bool]) -> tuple[int, int, float]:
    b_only = sum(1 for x, y in zip(a, b) if not x and y)
    c_only = sum(1 for x, y in zip(a, b) if x and not y)
    n = b_only + c_only
    if n == 0:
        return b_only, c_only, 1.0
    return b_only, c_only, float(
        binomtest(min(b_only, c_only), n, p=0.5, alternative="two-sided").pvalue
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("data/eval/casmi"))
    ap.add_argument("--out", type=Path, default=Path("data/paper_figures"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    data = {}
    for name, subdir, _ in CONFIGS:
        path = args.root / subdir / "casmi_identifications.jsonl"
        if not path.exists():
            raise SystemExit(f"missing {path}")
        data[name] = _load(path)

    sids = sorted(set.intersection(*[set(d) for d in data.values()]))
    n = len(sids)
    print(f"paired across {len(CONFIGS)} configs: {n} spectra")

    outcomes = {name: [_is_correct(data[name][s]) for s in sids] for name, _, _ in CONFIGS}

    # Main table
    main_rows = []
    for name, _, rerank_desc in CONFIGS:
        nc = sum(outcomes[name])
        main_rows.append({
            "config": name,
            "rerank_with": rerank_desc,
            "n_specs": n,
            "n_correct": nc,
            "id_acc_pct": round(100 * nc / n, 2),
        })
    with (args.out / "phase6_7_casmi_three_way.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(main_rows[0].keys()))
        w.writeheader(); w.writerows(main_rows)

    # Significance — pairwise McNemar, Bonferroni-corrected
    pairs = [(a, b) for a, _, _ in CONFIGS for b, _, _ in CONFIGS if a < b]
    alpha = 0.05 / len(pairs)
    print(f"\nBonferroni α = 0.05 / {len(pairs)} = {alpha:.4f}")
    sig_rows = []
    for A, B in pairs:
        b_only, c_only, p = mcnemar_p(outcomes[A], outcomes[B])
        delta = sum(outcomes[B]) - sum(outcomes[A])
        delta_pp = round(100 * delta / n, 2) if n else 0.0
        se = (b_only + c_only) ** 0.5
        ci_lo = round(100 * (delta - 1.96 * se) / n, 2) if n else 0.0
        ci_hi = round(100 * (delta + 1.96 * se) / n, 2) if n else 0.0
        sig_rows.append({
            "config_A": A,
            "config_B": B,
            "n_paired": n,
            "delta_BminusA_spec": delta,
            "delta_BminusA_pp": delta_pp,
            "ci95_lo_pp": ci_lo,
            "ci95_hi_pp": ci_hi,
            "mcnemar_b_AwrongBright": b_only,
            "mcnemar_c_ArightBwrong": c_only,
            "p_value": round(p, 4) if p >= 1e-4 else f"{p:.2e}",
            "significant_at_bonf_alpha": p < alpha,
        })
    with (args.out / "phase6_7_significance.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sig_rows[0].keys()))
        w.writeheader(); w.writerows(sig_rows)

    # Per-spec audit (3 configs side-by-side)
    per_rows = []
    for s in sids:
        row = {"spectrum_id": s,
               "formula": data["msclip_only"][s].get("casmi_formula"),
               "gt_ik14": data["msclip_only"][s].get("gt_inchikey_first_block")}
        for name, _, _ in CONFIGS:
            r = data[name][s]
            row[f"{name}_correct"] = int(bool(r.get("correct_top1")))
            row[f"{name}_pred_ik14"] = r.get("predicted_inchikey_first_block")
            row[f"{name}_pred_smiles"] = r.get("predicted_smiles")
        # LLM extras
        llm = (data["llm_reranker"][s].get("llm_rerank") or {})
        row["llm_confidence"] = llm.get("confidence")
        row["llm_fallback"] = llm.get("fallback_used")
        row["llm_n_peak_claims"] = len(llm.get("peak_claims") or [])
        per_rows.append(row)
    with (args.out / "phase6_7_casmi_per_spec.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_rows[0].keys()))
        w.writeheader(); w.writerows(per_rows)

    # Cross-benchmark coherence — paper-level finding
    coh_rows = [
        {"benchmark": "sub6a_realid_v2", "reranker": "weighted (conditional gap≥0.05)",
         "n_specs": 448, "id_acc_pct": 66.96, "delta_vs_msclip_pp": 10.27,
         "p_vs_msclip": "<1e-6", "leakage": "RIKEN→GNPS reingest"},
        {"benchmark": "sub6a_realid_v2", "reranker": "llm-as-reranker (Phase 6.3 C)",
         "n_specs": 448, "id_acc_pct": 64.49, "delta_vs_msclip_pp": 7.79,
         "p_vs_msclip": "<1e-4", "leakage": "RIKEN→GNPS reingest"},
        {"benchmark": "casmi_2022", "reranker": "weighted (= conditional, 100% trigger)",
         "n_specs": n, "id_acc_pct": main_rows[1]["id_acc_pct"],
         "delta_vs_msclip_pp": round(main_rows[1]["id_acc_pct"] - main_rows[0]["id_acc_pct"], 2),
         "p_vs_msclip": next((r["p_value"] for r in sig_rows
                             if r["config_A"] == "msclip_only" and r["config_B"] == "weighted"), "?"),
         "leakage": "none (PubChem formula-restricted)"},
        {"benchmark": "casmi_2022", "reranker": "llm-as-reranker (Phase 6.7, opus47)",
         "n_specs": n, "id_acc_pct": main_rows[2]["id_acc_pct"],
         "delta_vs_msclip_pp": round(main_rows[2]["id_acc_pct"] - main_rows[0]["id_acc_pct"], 2),
         "p_vs_msclip": next((r["p_value"] for r in sig_rows
                             if r["config_A"] == "llm_reranker" and r["config_B"] == "msclip_only") or
                             (r["p_value"] for r in sig_rows
                             if r["config_A"] == "msclip_only" and r["config_B"] == "llm_reranker"), "?"),
         "leakage": "none (PubChem formula-restricted)"},
    ]
    with (args.out / "phase6_7_cross_benchmark.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(coh_rows[0].keys()))
        w.writeheader(); w.writerows(coh_rows)

    print("=" * 70)
    print("MAIN — id_acc per config")
    for r in main_rows:
        print(f"  {r['config']:<14} {r['n_correct']:>3}/{r['n_specs']:<3}  = {r['id_acc_pct']:>6.2f}%")

    print("\n=== Pairwise McNemar (Bonferroni α = {:.4f}) ===".format(alpha))
    for r in sig_rows:
        flag = " *" if r["significant_at_bonf_alpha"] else ""
        print(f"  {r['config_A']} vs {r['config_B']:<14}  Δ={r['delta_BminusA_pp']:+.2f}pp  "
              f"b={r['mcnemar_b_AwrongBright']:>3}  c={r['mcnemar_c_ArightBwrong']:>3}  "
              f"p={r['p_value']}{flag}")

    print(f"\n=== Files ===")
    for fn in ("phase6_7_casmi_three_way.csv", "phase6_7_significance.csv",
               "phase6_7_casmi_per_spec.csv", "phase6_7_cross_benchmark.csv"):
        print(f"  data/paper_figures/{fn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
