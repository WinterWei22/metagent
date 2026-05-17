"""W7 D2 — Gate-2 with V1 / V2 / V3 metric variants, on 3 cohorts.

Reads W6 D3 5axis_results_*.jsonl, computes 3 variants × 3 cohorts,
emits a 9-row CSV verdict table + JSON per-task deltas. Also retains
W6 strict-intersection V0 as the baseline row for comparison.
"""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKTREE))

from concord.analyze.gate2_variants import (
    metric_v1_cohort, metric_v2_cohort, metric_v3_cohort, variant_verdict,
)
from concord.analyze.paradigm_consensus import metric_2_cohort  # W6 V0 baseline

W6_DIR = WORKTREE / "data/concord/gate2_w6"
W7_DIR = WORKTREE / "data/concord/gate2_w7"
TASKS_DIR = WORKTREE / "data/concord/tier_a_cooke"
W7_DIR.mkdir(parents=True, exist_ok=True)


def _load_rows(cohort: str) -> list[dict]:
    return [json.loads(l) for l in (W6_DIR / f"5axis_results_{cohort}.jsonl").read_text().splitlines()]


def _load_task_input_chebi(cohort: str) -> dict[str, set[str]]:
    """task_id → set of input differential metabolite CHEBI: IDs."""
    out: dict[str, set[str]] = {}
    for line in (TASKS_DIR / f"tasks_{cohort}.jsonl").read_text().splitlines():
        t = json.loads(line)
        chebis = {c["chebi_id"] for c in t["differential_metabolites"] if c.get("chebi_id")}
        out[t["task_id"]] = chebis
    return out


def main() -> int:
    rows_out = []
    detailed = {}
    for cohort in ("primary", "sens_a", "sens_b"):
        rows = _load_rows(cohort)
        inp = _load_task_input_chebi(cohort)

        v0 = metric_2_cohort(rows)
        v1 = metric_v1_cohort(rows)
        v2 = metric_v2_cohort(rows, task_input_chebi=inp)
        v3 = metric_v3_cohort(rows)

        for label, m in [("V0_W6_strict", v0), ("V1_fuzzy_inter", v1),
                          ("V2_compound_member", v2), ("V3_soft_union", v3)]:
            # V0 uses a slightly different key (metric_2_pass) — bridge to metric_pass
            if "metric_2_pass" in m and "metric_pass" not in m:
                m["metric_pass"] = m["metric_2_pass"]
            verdict = variant_verdict(m)
            row = {
                "variant": label, "cohort": cohort,
                "n_tasks": m["n_tasks"],
                "cond_a_prec": m["cond_a"]["mean_precision"],
                "cond_b_prec": m["cond_b"]["mean_precision"],
                "delta_pp": m["delta_precision_mean"] * 100,
                "sign_p": m["sign_test_p"],
                "metric_pass": m.get("metric_pass", False),
                "verdict": verdict,
                "pos_neg": f"{m['sign_test_pos']}/{m['sign_test_neg']}",
            }
            rows_out.append(row)
            detailed[f"{label}__{cohort}"] = {
                "label": label, "cohort": cohort,
                "summary": {k: (list(v) if isinstance(v, tuple) else v)
                              for k, v in m.items() if k != "per_task_deltas"},
            }

    csv_path = W7_DIR / "verdicts_3variant.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "variant", "cohort", "n_tasks", "cond_a_prec", "cond_b_prec",
            "delta_pp", "sign_p", "pos_neg", "verdict", "metric_pass",
        ])
        w.writeheader()
        for r in rows_out:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v)
                          for k, v in r.items()})
    (W7_DIR / "verdicts_3variant.json").write_text(json.dumps(detailed, indent=2, default=str))

    print(f"\n{'variant':<22}{'cohort':<10}{'N':>3}  {'A_prec':>7}  {'B_prec':>7}  "
          f"{'Δpp':>7}  {'sign_p':>7}  {'+/-':>6}  verdict")
    for r in rows_out:
        print(f"{r['variant']:<22}{r['cohort']:<10}{r['n_tasks']:>3}  "
              f"{r['cond_a_prec']:>7.3f}  {r['cond_b_prec']:>7.3f}  "
              f"{r['delta_pp']:>+7.2f}  {r['sign_p']:>7.3f}  {r['pos_neg']:>6}  {r['verdict']}")
    print(f"\nwrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
