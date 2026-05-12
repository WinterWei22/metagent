"""Phase 6.6 — McNemar significance + cross-benchmark coherence on CASMI.

Reads:
  data/eval/casmi/2022_msclip_only/casmi_identifications.jsonl
  data/eval/casmi/2022_conditional/casmi_identifications.jsonl

Produces:
  data/paper_figures/phase6_6_casmi_results.csv      — main table
  data/paper_figures/phase6_6_casmi_per_spec.csv     — per-spec correctness
  data/paper_figures/phase6_6_significance.csv       — McNemar / Δ / CI
  data/paper_figures/phase6_6_cross_benchmark.csv    — Sub-6A v2 vs CASMI 2022 coherence

The conditional rerank threshold (gap≥0.05) is locked from Phase 6.5 grid
search on Sub-6A v2 — NOT tuned for CASMI.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _load_idents(path: Path) -> dict[str, dict]:
    """spectrum_id → record."""
    out: dict[str, dict] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    for line in path.open():
        rec = json.loads(line)
        out[rec["spectrum_id"]] = rec
    return out


def _is_correct(rec: dict) -> bool:
    return rec.get("correct_top1") is True


def mcnemar_p(a: list[bool], b: list[bool]) -> tuple[int, int, float]:
    """Returns (b_only, c_only, p) for paired binary outcomes a vs b."""
    from scipy.stats import binomtest
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

    bs = _load_idents(args.root / "2022_msclip_only" / "casmi_identifications.jsonl")
    cd = _load_idents(args.root / "2022_conditional" / "casmi_identifications.jsonl")
    sids = sorted(set(bs) & set(cd))
    n_total = len(sids)

    bs_correct = [_is_correct(bs[s]) for s in sids]
    cd_correct = [_is_correct(cd[s]) for s in sids]

    # GT-reachable subset: spec where pool actually contained the GT.
    # Unreachable specs always score wrong under both configs and only depress
    # the absolute id_acc; report both denominators.
    reachable = [
        s for s in sids
        if not bs[s].get("error") == "no_pubchem_pool" and bs[s].get("gt_inchikey_first_block")
    ]
    # Stronger reachability: a config can correctly predict iff the GT IK14
    # appears in the pool; we approximate this as "either config got it right
    # at any iteration" (spec is reachable if at least one of the two found it
    # — guarantees GT IS in pool). Specs reachable but missed by both still
    # count under id_acc/reachable. For the audit denominator we use the
    # earlier loader-side count (142/170 IK14-in-pool) reported separately.
    n_either_correct = sum(1 for s in sids if bs[s].get("correct_top1") or cd[s].get("correct_top1"))

    # ---- main table ----
    main_rows = [
        {
            "config": "msclip_only",
            "rerank": "none",
            "n_specs": n_total,
            "n_correct": sum(bs_correct),
            "id_acc_pct": round(100 * sum(bs_correct) / n_total, 2) if n_total else 0.0,
        },
        {
            "config": "conditional",
            "rerank": "sirius+cfmid (gate gap≥0.05)",
            "n_specs": n_total,
            "n_correct": sum(cd_correct),
            "id_acc_pct": round(100 * sum(cd_correct) / n_total, 2) if n_total else 0.0,
        },
    ]
    with (args.out / "phase6_6_casmi_results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(main_rows[0].keys()))
        w.writeheader(); w.writerows(main_rows)

    # ---- significance ----
    b_only, c_only, p = mcnemar_p(bs_correct, cd_correct)
    delta = sum(cd_correct) - sum(bs_correct)
    delta_pp = round(100 * delta / n_total, 2) if n_total else 0.0
    se = (b_only + c_only) ** 0.5
    ci_lo = round(100 * (delta - 1.96 * se) / n_total, 2) if n_total else 0.0
    ci_hi = round(100 * (delta + 1.96 * se) / n_total, 2) if n_total else 0.0
    sig_rows = [{
        "comparison": "conditional vs msclip_only",
        "benchmark": "casmi_2022",
        "n_paired": n_total,
        "delta_spec": delta,
        "delta_pp": delta_pp,
        "ci95_lo_pp": ci_lo,
        "ci95_hi_pp": ci_hi,
        "mcnemar_b": b_only,
        "mcnemar_c": c_only,
        "p_value": round(p, 4) if p >= 1e-4 else f"{p:.2e}",
    }]
    with (args.out / "phase6_6_significance.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sig_rows[0].keys()))
        w.writeheader(); w.writerows(sig_rows)

    # ---- per-spec audit ----
    per_rows = []
    for s in sids:
        per_rows.append({
            "spectrum_id": s,
            "formula": bs[s].get("casmi_formula"),
            "gt_ik14": bs[s].get("gt_inchikey_first_block"),
            "msclip_only_correct": int(bs_correct[sids.index(s)]),
            "msclip_only_pred": bs[s].get("predicted_inchikey_first_block"),
            "conditional_correct": int(cd_correct[sids.index(s)]),
            "conditional_pred": cd[s].get("predicted_inchikey_first_block"),
            "conditional_gate_skipped": (cd[s].get("gate") or {}).get("conditional_skipped"),
            "conditional_gate_msclip_top1": (cd[s].get("gate") or {}).get("gate_msclip_top1"),
            "conditional_gate_msclip_gap": (cd[s].get("gate") or {}).get("gate_msclip_gap"),
        })
    with (args.out / "phase6_6_casmi_per_spec.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_rows[0].keys()))
        w.writeheader(); w.writerows(per_rows)

    # ---- cross-benchmark coherence (Sub-6A v2 vs CASMI 2022) ----
    # Sub-6A v2 numbers from Phase 6.5 final report (locked headline).
    coh_rows = [
        {
            "benchmark": "sub6a_realid_v2",
            "n_specs": 448,
            "msclip_only_acc_pct": 56.70,
            "conditional_acc_pct": 66.96,
            "delta_pp": 10.27,
            "p_vs_msclip_only": "<1e-6",
            "skip_pct": 35.3,
            "leakage": "RIKEN→GNPS reingest (in-distribution lookup)",
            "candidate_space": "GNPS reference spectra",
        },
        {
            "benchmark": "casmi_2022",
            "n_specs": n_total,
            "msclip_only_acc_pct": main_rows[0]["id_acc_pct"],
            "conditional_acc_pct": main_rows[1]["id_acc_pct"],
            "delta_pp": delta_pp,
            "p_vs_msclip_only": sig_rows[0]["p_value"],
            "skip_pct": round(100 * sum(
                1 for s in sids if (cd[s].get("gate") or {}).get("conditional_skipped")
            ) / n_total, 2) if n_total else 0.0,
            "leakage": "none (PubChem candidate pool, no GNPS reference overlap)",
            "candidate_space": "PubChem (formula-restricted slice)",
        },
    ]
    with (args.out / "phase6_6_cross_benchmark.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(coh_rows[0].keys()))
        w.writeheader(); w.writerows(coh_rows)

    print("=" * 60)
    print(f"CASMI 2022   n_specs={n_total}")
    print(f"  msclip_only:  {main_rows[0]['n_correct']}/{n_total} = {main_rows[0]['id_acc_pct']}%")
    print(f"  conditional:  {main_rows[1]['n_correct']}/{n_total} = {main_rows[1]['id_acc_pct']}%")
    print(f"  delta:        {delta:+d} ({delta_pp:+.2f}pp)  CI95=[{ci_lo:+.2f}, {ci_hi:+.2f}]")
    print(f"  McNemar:      b={b_only} c={c_only}  p={sig_rows[0]['p_value']}")
    print(f"  either-correct:{n_either_correct}/{n_total} = {round(100*n_either_correct/n_total,2)}%")
    print()
    print("=== CROSS-BENCHMARK COHERENCE ===")
    for r in coh_rows:
        print(f"  {r['benchmark']:<22}  msclip={r['msclip_only_acc_pct']:.2f}%  cond={r['conditional_acc_pct']:.2f}%  Δ={r['delta_pp']:+.2f}pp  p={r['p_vs_msclip_only']}")
    print()
    print(f"wrote main: {args.out / 'phase6_6_casmi_results.csv'}")
    print(f"wrote sig:  {args.out / 'phase6_6_significance.csv'}")
    print(f"wrote per-spec: {args.out / 'phase6_6_casmi_per_spec.csv'}")
    print(f"wrote coherence: {args.out / 'phase6_6_cross_benchmark.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
