"""W6 D4 — compute Gate-2 Metric 1 + Metric 2 + cohort verdict.

Inputs:
  data/concord/gate2_w6/5axis_results_{primary,sens_a,sens_b}.jsonl
  data/concord/tier_a_cooke/tasks_{primary,sens_a,sens_b}.jsonl
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKTREE))

from concord.analyze.paradigm_consensus import (
    metric_1_cohort, metric_2_cohort, cohort_verdict, ALL_METHODS,
)
from concord.analyze.pathway_match import pathway_name_overlap

OUT_DIR = WORKTREE / "data/concord/gate2_w6"


def _load_cohort(cohort: str) -> list[dict]:
    p = OUT_DIR / f"5axis_results_{cohort}.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()]


def _compute_5x5_jaccard(rows: list[dict]) -> dict:
    """5x5 pathway-NAME Jaccard mean across cohort (W5-style)."""
    from itertools import combinations
    pairs = list(combinations(ALL_METHODS, 2))
    sums = {p: [] for p in pairs}
    # Within-paradigm (diagonal-like, no self) and across-paradigm
    paradigm_of = {"sspa_ora": "ora", "ramp": "ora", "PSEA": "ora",
                    "mummichog": "mz", "FELLA": "net"}
    for row in rows:
        method_names = {m: set(p["pathway_name"] for p in row.get(m, {}).get("pathways", []))
                          for m in ALL_METHODS}
        for a, b in pairs:
            sa, sb = method_names.get(a, set()), method_names.get(b, set())
            if not sa and not sb:
                continue
            if not (sa | sb):
                continue
            sums[(a, b)].append(len(sa & sb) / len(sa | sb))
    pair_mean = {f"{a}_vs_{b}": (sum(v) / len(v) if v else 0.0)
                  for (a, b), v in sums.items()}
    # paradigm bucket means
    bucket = {"ora_ora": [], "ora_mz": [], "ora_net": [], "mz_net": []}
    for (a, b), vals in sums.items():
        pa, pb = paradigm_of[a], paradigm_of[b]
        if pa == "ora" and pb == "ora":
            bucket["ora_ora"].extend(vals)
        elif {pa, pb} == {"ora", "mz"}:
            bucket["ora_mz"].extend(vals)
        elif {pa, pb} == {"ora", "net"}:
            bucket["ora_net"].extend(vals)
        elif {pa, pb} == {"mz", "net"}:
            bucket["mz_net"].extend(vals)
    bucket_mean = {k: (sum(v) / len(v) if v else 0.0) for k, v in bucket.items()}
    return {"pair_mean": pair_mean, "paradigm_bucket_mean": bucket_mean}


def main() -> int:
    summary: dict = {}
    for cohort in ("primary", "sens_a", "sens_b"):
        rows = _load_cohort(cohort)
        m1 = metric_1_cohort(rows)
        m2 = metric_2_cohort(rows)
        verdict = cohort_verdict(m1, m2)
        jaccard = _compute_5x5_jaccard(rows)
        summary[cohort] = {
            "n_tasks": len(rows),
            "metric_1": m1,
            "metric_2": m2,
            "verdict": verdict,
            "jaccard_5x5": jaccard,
        }

    out = OUT_DIR / "gate2_verdict.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n=== W6 D4 Gate-2 ===\n")

    for cohort, s in summary.items():
        print(f"--- {cohort.upper()}  N={s['n_tasks']} ---")
        m1 = s["metric_1"]; m2 = s["metric_2"]
        print(f"  Metric 1 (paradigm-aware supported %)")
        print(f"    Cond A (Level 1 ORA-only) : {m1['cond_a_supported_pct']:.1%}")
        print(f"    Cond B (Level 4+5 xpara)  : {m1['cond_b_supported_pct']:.1%}")
        print(f"    Δ pp                       : {m1['delta_pp']:+.1f}pp")
        print(f"    Metric 1                   : {'PASS' if m1['metric_1_pass'] else 'FAIL'}")
        print(f"  Metric 2 (precision/recall vs Cooke GT, name-fuzzy)")
        ca, cb = m2["cond_a"], m2["cond_b"]
        print(f"    Cond A precision@10        : {ca['mean_precision']:.1%}  CI95={ca['precision_ci95']}")
        print(f"    Cond B precision@10        : {cb['mean_precision']:.1%}  CI95={cb['precision_ci95']}")
        print(f"    Δ precision                : {m2['delta_precision_mean']*100:+.1f}pp")
        print(f"    Δ recall                   : {m2['delta_recall_mean']*100:+.1f}pp")
        print(f"    sign test p (per-task Δ)   : p={m2['sign_test_p']:.3f}  (+/-: {m2['sign_test_pos']}/{m2['sign_test_neg']})")
        print(f"    Metric 2                   : {'PASS' if m2['metric_2_pass'] else 'FAIL'}")
        print(f"  Verdict                      : {s['verdict']}")
        b = s["jaccard_5x5"]["paradigm_bucket_mean"]
        print(f"  5×5 Jaccard buckets:  ora×ora={b['ora_ora']:.3f}  "
              f"ora×mz={b['ora_mz']:.3f}  ora×net={b['ora_net']:.3f}  mz×net={b['mz_net']:.3f}")
        print()

    verdicts = [s["verdict"] for s in summary.values()]
    if all(v == "GREEN" for v in verdicts):
        overall = "GREEN (3/3)"
    elif all(v == "RED" for v in verdicts):
        overall = "RED (3/3)"
    elif "RED" in verdicts:
        overall = "YELLOW (mixed, contains RED)"
    else:
        overall = "YELLOW (mixed GREEN/YELLOW)"
    print(f"=== OVERALL: {overall} ===")
    print(f"\nwritten → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
