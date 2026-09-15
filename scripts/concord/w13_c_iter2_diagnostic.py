"""W13.C — iter-2 degradation root-cause diagnostic on W12 D5 N=63 superset.

W12 D5 iter-2 degradation rate jumped from W10 D4 17.7 % to 22.2 %
(+4.48 pp). W10 D4.5 H3 hypothesis (richer feedback → LLM overshoot)
was CONFIRMED on the W10 N=11 slice. This W13.C diagnostic re-runs
the per-iter quality decomposition on the W12 D5 N=63 superset to
distinguish two candidate root causes:

  H3 (extends): unsupported gains dominate iter-1 → iter-2 quality
                rise. Richer feedback prompt still drives LLM to
                produce unsupported-class claims in iter-2 rewrite.

  H4 (new):     contradicted gains dominate iter-1 → iter-2 quality
                rise. W12 D4 dispatcher case (FACTUAL/GROUNDED →
                factual_sub6) means more claims now receive concrete
                verdict; iter-2 rewrite has more verdict signal to
                react against and accidentally introduces explicit
                CONTRADICTED claims.

  H3 + H4 mix:  both axes contribute, no clear single driver.

Pure analysis. No production code touched. No LLM call.

Run:
    PYTHONPATH=. python3 scripts/concord/w13_c_iter2_diagnostic.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

_INPUT = Path("data/concord/w12_path_x_post_c7/path_x_full63_results.jsonl")
_OUTPUT_DIR = Path("data/concord/w13_c_iter2_diagnostic")


def _per_iter_quality(per_iter: list[dict]) -> list[dict]:
    """Return one summary row per iter with c/u/v/s + quality (c+u)."""
    rows = []
    for it in per_iter:
        c = it.get("n_contradicted", 0)
        u = it.get("n_unsupported", 0)
        v = it.get("n_unverifiable_v0", 0)
        s = it.get("n_supported", 0)
        rows.append({
            "iter_idx": it.get("iter_idx"),
            "c": c, "u": u, "v": v, "s": s,
            "quality_cu": c + u,
        })
    return rows


def _analyse_task(row: dict) -> dict:
    """Compute iter-1 → iter-2 deltas for one task."""
    iters = _per_iter_quality(row.get("per_iter") or [])
    if len(iters) < 3:
        return {
            "task_id": row.get("task_id"),
            "skipped": f"only {len(iters)} iters",
        }
    it0, it1, it2 = iters[0], iters[1], iters[2]
    return {
        "task_id": row.get("task_id"),
        "iter_qualities": [it0["quality_cu"], it1["quality_cu"], it2["quality_cu"]],
        "iter_counts": iters,
        "delta_q_12": it2["quality_cu"] - it1["quality_cu"],
        "delta_c_12": it2["c"] - it1["c"],
        "delta_u_12": it2["u"] - it1["u"],
        "delta_s_12": it2["s"] - it1["s"],
        "delta_v_12": it2["v"] - it1["v"],
    }


def _verdict(rows: list[dict]) -> dict:
    """Aggregate H3 vs H4 attribution across all iter2_degraded tasks."""
    n = len(rows)
    if n == 0:
        return {"verdict": "NO_DATA", "n_degraded": 0}

    # For each task, what drove δ_q_12 — δ_u_12 (H3) or δ_c_12 (H4)?
    h3_dominant = 0     # δ_u_12 > δ_c_12 and δ_u_12 > 0
    h4_dominant = 0     # δ_c_12 > δ_u_12 and δ_c_12 > 0
    h3_h4_tie = 0       # both positive, similar magnitude
    other = 0           # neither positive (rare edge case)

    sum_du = 0
    sum_dc = 0
    sum_ds = 0
    losses_supported = 0
    for r in rows:
        if r.get("skipped"):
            continue
        du = r["delta_u_12"]
        dc = r["delta_c_12"]
        ds = r["delta_s_12"]
        sum_du += du
        sum_dc += dc
        sum_ds += ds
        if ds < 0:
            losses_supported += 1
        if du > 0 and dc <= 0:
            h3_dominant += 1
        elif dc > 0 and du <= 0:
            h4_dominant += 1
        elif du > 0 and dc > 0:
            # both positive — see which is bigger
            if du > 2 * dc:
                h3_dominant += 1
            elif dc > 2 * du:
                h4_dominant += 1
            else:
                h3_h4_tie += 1
        else:
            other += 1

    # Verdict logic
    if h3_dominant >= 0.6 * n:
        verdict = "H3_CONFIRMED"
        rationale = (f"unsupported gains dominate in {h3_dominant}/{n} tasks "
                     f"(>= 60 %). H3 (richer feedback → LLM unsupported "
                     f"overshoot) extends from W10 D4.5 to W12 D5 N=63.")
    elif h4_dominant >= 0.6 * n:
        verdict = "H4_CONFIRMED"
        rationale = (f"contradicted gains dominate in {h4_dominant}/{n} tasks "
                     f"(>= 60 %). H4 (W12 dispatcher case enables more "
                     f"contradicted verdicts, iter-2 over-corrects) is the "
                     f"new root cause.")
    else:
        verdict = "MIXED"
        rationale = (f"neither hypothesis dominates: h3={h3_dominant}, "
                     f"h4={h4_dominant}, tie={h3_h4_tie}, other={other} of {n}. "
                     f"Both axes contribute; W14 attribution requires deeper "
                     f"trace inspection (per-claim verdict diff).")

    return {
        "verdict": verdict,
        "rationale": rationale,
        "n_degraded": n,
        "h3_unsupported_dominant": h3_dominant,
        "h4_contradicted_dominant": h4_dominant,
        "tie": h3_h4_tie,
        "other": other,
        "aggregate_delta_iter1_to_iter2": {
            "sum_delta_unsupported": sum_du,
            "sum_delta_contradicted": sum_dc,
            "sum_delta_supported": sum_ds,
            "tasks_losing_supported": losses_supported,
        },
    }


def _build_markdown(rows: list[dict], v: dict, all_w12_degraded: int) -> str:
    L = []
    a = L.append
    a("# W13.C — iter-2 degradation root-cause on W12 D5 N=63 superset")
    a("")
    a("**Source data:** `data/concord/w12_path_x_post_c7/path_x_full63_results.jsonl`")
    a(f"**Tasks analysed:** {len(rows)} `rollback_reason == \"iter2_degraded\"`")
    a("**Cross-check vs W12 D5 close-out aggregate:** "
      f"{'match ✓' if len(rows) == all_w12_degraded else f'MISMATCH (close-out reported {all_w12_degraded})'}")
    a("")
    a("---")
    a("")
    a("## 1 · Verdict")
    a("")
    a(f"**{v['verdict']}** — {v['rationale']}")
    a("")
    a(f"- H3 (unsupported dominant) tasks:    **{v['h3_unsupported_dominant']}/{v['n_degraded']}**")
    a(f"- H4 (contradicted dominant) tasks:   **{v['h4_contradicted_dominant']}/{v['n_degraded']}**")
    a(f"- Tied / mixed:                       {v['tie']}/{v['n_degraded']}")
    a(f"- Other (neither positive):           {v['other']}/{v['n_degraded']}")
    a("")
    agg = v["aggregate_delta_iter1_to_iter2"]
    a("Aggregate iter-1 → iter-2 deltas (sum across all degraded tasks):")
    a("")
    a(f"- Σ Δ unsupported: **{agg['sum_delta_unsupported']:+d}** claims")
    a(f"- Σ Δ contradicted: **{agg['sum_delta_contradicted']:+d}** claims")
    a(f"- Σ Δ supported: **{agg['sum_delta_supported']:+d}** claims")
    a(f"- Tasks losing supported in iter-2: {agg['tasks_losing_supported']}/{v['n_degraded']}")
    a("")
    a("---")
    a("")
    a("## 2 · Per-task table")
    a("")
    a("| task_id (tail) | q[0,1,2] | Δq_12 | Δs_12 | Δu_12 | Δc_12 | Δv_12 |")
    a("|---|---|---:|---:|---:|---:|---:|")
    for r in rows:
        if r.get("skipped"):
            a(f"| {r['task_id'][-30:]} | skipped: {r['skipped']} |||||| |")
            continue
        tail = r["task_id"][-30:]
        a(f"| `{tail}` | {r['iter_qualities']} | "
          f"{r['delta_q_12']:+d} | {r['delta_s_12']:+d} | "
          f"{r['delta_u_12']:+d} | {r['delta_c_12']:+d} | {r['delta_v_12']:+d} |")
    a("")
    a("---")
    a("")
    a("## 3 · W14 candidate paths (data-driven)")
    a("")
    if v["verdict"] == "H3_CONFIRMED":
        a("- **W14-α (recommended)**: cap `max_feedback_iters=1`. iter-2 "
          "rewrite consistently degrades quality on iter-1's responsive "
          "narrative; removing iter-2 eliminates the regression source.")
        a("- **W14-β (alternative)**: redesign quality_score to count "
          "supported gains positively (currently c+u only). May offset "
          "iter-2 unsupported overshoot.")
    elif v["verdict"] == "H4_CONFIRMED":
        a("- **W14-α (recommended)**: dispatcher-case soft-skip — in iter-2, "
          "skip routing FACTUAL/GROUNDED through factual_sub6 (revert to "
          "fall-through UV for iter-2 only). Preserves iter-1 gains.")
        a("- **W14-β (alternative)**: factual_sub6 stricter verdict threshold "
          "(e.g. only SUPPORTED if curated-pool match also confirms; otherwise "
          "UV instead of CONTRADICTED).")
    else:
        a("- **W14-α**: deep per-claim verdict diff between iter-1 and iter-2 "
          "(sample 5-10 representative degraded tasks).")
        a("- **W14-β**: defer iter-2 fix to W15; W14 picks C8/C9 noise sprint "
          "instead.")
    a("")
    return "\n".join(L) + "\n"


def main() -> int:
    if not _INPUT.exists():
        print(f"ERROR: input not found at {_INPUT}")
        return 1

    rows_all = []
    with _INPUT.open() as f:
        for line in f:
            rows_all.append(json.loads(line))

    degraded = []
    n_all_degraded = 0
    for r in rows_all:
        if r.get("rollback_reason") == "iter2_degraded":
            degraded.append(_analyse_task(r))
            n_all_degraded += 1

    print(f"Loaded {len(rows_all)} W12 D5 tasks, "
          f"{n_all_degraded} with rollback_reason==iter2_degraded")

    verdict = _verdict(degraded)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = _OUTPUT_DIR / "per_task.json"
    out_json.write_text(json.dumps({
        "n_iter2_degraded": n_all_degraded,
        "per_task": degraded,
        "verdict": verdict,
    }, indent=2, ensure_ascii=False, default=str))

    md = _build_markdown(degraded, verdict, n_all_degraded)
    (_OUTPUT_DIR / "summary.md").write_text(md)

    print()
    print(md)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
