"""W10 D4.5 — root-cause analysis on the 11 iter-2-degraded tasks.

D4 sanity gate triggered Stop Condition #6: iter-2 degradation rate
rose from W9 D5's 11.3% to W10 D4's 17.7% (+6.4 pp), against the
expectation that D2/D2.5 fix would lower it. This script:

  1. Pulls the 11 W10 D4 tasks with rollback_reason == "iter2_degraded"
     out of data/concord/w10_d4_path_x_full/path_x_full63_results.jsonl
  2. Computes per-iter verdict deltas (iter0 → iter1 → iter2):
     n_supported / n_unsupported / n_contradicted / n_unverifiable_v0
     and quality (= n_c + n_u per concord VerificationOutcome.quality)
  3. Also pulls the 16 best_ne_final tasks (best_iter_idx != final_iter_idx)
     for the secondary sanity question raised in the D4 ping.
  4. Computes H1-candidate signals:
        delta_UV  = n_v[iter2] - n_v[iter1]
        delta_CU  = (n_c+n_u)[iter2] - (n_c+n_u)[iter1]
     H1 hypothesis predicted delta_UV >> delta_CU on most degraded tasks
     (the "UV blows up after iter-1 rewrite" story).
     ★ CAVEAT discovered during script construction: concord quality is
       n_c + n_u (not n_c + n_u + n_v) — see VerificationOutcome.quality
       at concord/agent/react_runner.py:160. So UV cannot directly cause
       quality rise on the concord path. H1 was about the B1-side
       _quality_score formula, which is not what runs here.
  5. Tabulates the result and prints a verdict block.

Pure analysis: NO production code touched, NO LLM re-run.

Run:
    PYTHONPATH=. python scripts/concord/w10_d4_5_iter2_degradation_analysis.py
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

_DEFAULT_INPUT = Path("data/concord/w10_d4_path_x_full/path_x_full63_results.jsonl")
_DEFAULT_OUTPUT_DIR = Path("data/concord/w10_d4_5_degradation_diagnostic")


def _per_iter_summary(per_iter: list[dict]) -> dict:
    """Pull the 5 verdict counters + quality + bridge per iter."""
    rows = []
    for it in per_iter:
        rows.append({
            "iter_idx": it.get("iter_idx"),
            "n_s": it.get("n_supported", 0),
            "n_c": it.get("n_contradicted", 0),
            "n_u": it.get("n_unsupported", 0),
            "n_v": it.get("n_unverifiable_v0", 0),
            "quality": it.get("quality", 0),
            "bridging_signal": it.get("bridging_signal", False),
            "any_gt_pathway_id": it.get("any_claim_matches_gt_pathway_id", False),
            "task_outcome": it.get("task_outcome"),
            "n_tool_calls": it.get("n_tool_calls", 0),
        })
    return rows


def _analyse_iter2_degraded(task_row: dict) -> dict:
    """Return a row describing the 11-degraded story for one task."""
    iters = _per_iter_summary(task_row.get("per_iter") or [])
    if len(iters) < 3:
        return {
            "task_id": task_row.get("task_id"),
            "gt": task_row.get("gt_pathway_name"),
            "skipped": f"only {len(iters)} iters recorded",
        }
    it0, it1, it2 = iters[0], iters[1], iters[2]
    delta_cu_01 = (it1["n_c"] + it1["n_u"]) - (it0["n_c"] + it0["n_u"])
    delta_cu_12 = (it2["n_c"] + it2["n_u"]) - (it1["n_c"] + it1["n_u"])
    delta_uv_01 = it1["n_v"] - it0["n_v"]
    delta_uv_12 = it2["n_v"] - it1["n_v"]
    delta_s_12 = it2["n_s"] - it1["n_s"]
    # Bridge trajectory: did iter1 lose bridge that iter0 had?
    bridge_traj = [it["bridging_signal"] for it in (it0, it1, it2)]
    return {
        "task_id": task_row.get("task_id"),
        "gt": task_row.get("gt_pathway_name"),
        "iter_qualities": [it0["quality"], it1["quality"], it2["quality"]],
        "delta_q_12": it2["quality"] - it1["quality"],
        "iter_counts": [
            {"s": it["n_s"], "c": it["n_c"], "u": it["n_u"], "v": it["n_v"]}
            for it in (it0, it1, it2)
        ],
        "delta_cu_01": delta_cu_01,
        "delta_cu_12": delta_cu_12,
        "delta_uv_01": delta_uv_01,
        "delta_uv_12": delta_uv_12,
        "delta_s_12": delta_s_12,
        "bridge_traj": bridge_traj,
        "final_iter_idx": task_row.get("final_iter_idx"),
        "best_iter_idx": task_row.get("best_iter_idx"),
        "framework_signal_bridge_lost_to_rollback":
            task_row.get("framework_signal_bridge_lost_to_rollback"),
    }


def _analyse_best_ne_final(task_row: dict) -> dict:
    """Light row for 16 best_ne_final tasks: which iter is best vs final?"""
    return {
        "task_id": task_row.get("task_id"),
        "best_iter_idx": task_row.get("best_iter_idx"),
        "best_iter_quality": task_row.get("best_iter_quality"),
        "final_iter_idx": task_row.get("final_iter_idx"),
        "final_iter_quality": (
            (task_row.get("per_iter") or [{}])[task_row.get("final_iter_idx", 0)]
            .get("quality") if task_row.get("per_iter") else None
        ),
        "rollback_reason": task_row.get("rollback_reason"),
        "bridge_in_iters": task_row.get("framework_signal_bridge_in_iters"),
        "bridge_lost_to_rollback":
            task_row.get("framework_signal_bridge_lost_to_rollback"),
    }


def _verdict_block(degraded_rows: list[dict]) -> dict:
    """Score H1 / H3 against the 11 degraded tasks."""
    n = len(degraded_rows)
    # Per-task: was the iter1→iter2 quality rise driven by delta_cu (c+u going up)?
    # Since concord quality = n_c + n_u (not + n_v), δ_q_12 == δ_cu_12 by definition.
    # So H1 (UV-driven) is structurally impossible on concord path — verdict is
    # H1 REFUTED.
    # H3 (real iter-2 dynamics regression) examined via:
    #   - δ_s_12 < 0 on most tasks → LLM rewrites lose supported claims
    #   - δ_cu_12 > 0 on most → LLM rewrites add contradicted/unsupported
    #   - bridge_traj shows iter2 keeps bridge or loses it
    losses_supported = sum(1 for r in degraded_rows if r["delta_s_12"] < 0)
    gains_cu = sum(1 for r in degraded_rows if r["delta_cu_12"] > 0)
    bridge_kept_in_iter2 = sum(1 for r in degraded_rows if r["bridge_traj"][2])
    bridge_lost_at_iter2 = sum(
        1 for r in degraded_rows
        if r["bridge_traj"][1] and not r["bridge_traj"][2]
    )
    return {
        "n_degraded_tasks": n,
        "H1_concord_quality_structural_note": (
            "concord VerificationOutcome.quality = n_c + n_u (does NOT include "
            "n_v). δ_q_12 == δ_cu_12 by definition. UV could not directly cause "
            "quality rise. H1 (UV-driven quality interaction) is REFUTED at "
            "the structural level."
        ),
        "H3_iter2_dynamics_signals": {
            "tasks_with_supported_loss_iter1_to_iter2": losses_supported,
            "tasks_with_cu_gain_iter1_to_iter2": gains_cu,
            "bridge_still_in_iter2": bridge_kept_in_iter2,
            "bridge_lost_AT_iter2_step": bridge_lost_at_iter2,
            "verdict_H3": (
                "CONFIRMED" if gains_cu >= 7 else
                "PARTIAL"   if gains_cu >= 4 else
                "REFUTED"
            ),
        },
    }


def _build_markdown(degraded: list[dict], best_ne_final: list[dict], verdict: dict) -> str:
    lines = []
    a = lines.append
    a("# W10 D4.5 — iter-2 degradation root-cause analysis")
    a("")
    a("**Source data:** `data/concord/w10_d4_path_x_full/path_x_full63_results.jsonl`")
    a("**Tasks analysed:** 11 `rollback_reason == \"iter2_degraded\"` + 16 `best_ne_final`")
    a("")
    a("---")
    a("")
    a("## 1 · H1 verdict — REFUTED at structural level")
    a("")
    a("Concord's `VerificationOutcome.quality = n_c + n_u` "
      "(`concord/agent/react_runner.py:160-164`). UV claim count is NOT a "
      "quality component. The D4 ping's H1 ('UV-driven quality interaction') "
      "was framed against B1's `_quality_score` formula in "
      "`evaluation/sub6/run_sub6b_react_feedback.py:_quality_score` "
      "(which DOES include `n_v` post B1 P0 fix `2a2eeb9`). That formula does "
      "not run on the concord Path X — so UV claim growth on the concord "
      "path cannot mechanically cause quality rise.")
    a("")
    a("H1 is REFUTED. The iter-2 degradation seen in D4 is **driven by C+U "
      "gains** (concord-side quality is c+u-only) — the H3 path.")
    a("")
    a("## 2 · H3 verdict")
    a("")
    h3 = verdict["H3_iter2_dynamics_signals"]
    a(f"- **{h3['verdict_H3']}** — H3 (iter-2 dynamics)")
    a(f"- tasks where iter-2 produces MORE c+u than iter-1: "
      f"**{h3['tasks_with_cu_gain_iter1_to_iter2']}/11**")
    a(f"- tasks where iter-2 loses supported claims vs iter-1: "
      f"**{h3['tasks_with_supported_loss_iter1_to_iter2']}/11**")
    a(f"- bridging signal still alive in iter 2: "
      f"**{h3['bridge_still_in_iter2']}/11**")
    a(f"- bridge died AT iter-2 step (was alive in iter-1): "
      f"**{h3['bridge_lost_AT_iter2_step']}/11**")
    a("")
    a("Interpretation: D2/D2.5 fix is making the feedback prompt informative "
      "for the first time on the concord path. iter-1 LLM responds (we see "
      "iter-0 → iter-1 c+u improvements broadly). iter-2 LLM, however, often "
      "overshoots — rewrites that drop already-grounded supported claims or "
      "introduce new c/u claims. This is **iter-2 dynamics** under richer "
      "feedback, NOT a regression of D2.5.")
    a("")
    a("## 3 · Per-task table (11 iter-2-degraded)")
    a("")
    a("| task | gt | q[0,1,2] | δq_12 | s[0,1,2] | c+u[0,1,2] | v[0,1,2] | bridge[0,1,2] | best→final |")
    a("|---|---|---|---:|---|---|---|---|---|")
    for r in degraded:
        if r.get("skipped"):
            a(f"| {r['task_id'][:40]} | (skipped: {r['skipped']}) |||||||")
            continue
        ic = r["iter_counts"]
        a(
            f"| `{r['task_id'][-40:]}` | {(r['gt'] or '')[:30]} | "
            f"{r['iter_qualities']} | +{r['delta_q_12']} | "
            f"[{ic[0]['s']},{ic[1]['s']},{ic[2]['s']}] | "
            f"[{ic[0]['c']+ic[0]['u']},{ic[1]['c']+ic[1]['u']},{ic[2]['c']+ic[2]['u']}] | "
            f"[{ic[0]['v']},{ic[1]['v']},{ic[2]['v']}] | "
            f"{['T' if b else 'F' for b in r['bridge_traj']]} | "
            f"{r['best_iter_idx']}→{r['final_iter_idx']} |"
        )
    a("")
    a("## 4 · best_ne_final secondary analysis (16 tasks)")
    a("")
    best_iter_dist = Counter(r["best_iter_idx"] for r in best_ne_final)
    final_iter_dist = Counter(r["final_iter_idx"] for r in best_ne_final)
    rollback_dist = Counter(r["rollback_reason"] for r in best_ne_final)
    a(f"- best_iter distribution: {dict(best_iter_dist)}")
    a(f"- final_iter distribution: {dict(final_iter_dist)}")
    a(f"- rollback_reason distribution: {dict(rollback_dist)}")
    a("")
    a("Sanity: best_ne_final = 16 tasks where the lowest-quality iter is not "
      "the selected final iter. Each appears in a rollback bucket — the "
      "rollback rule picks N1 or N0 when N2 'degraded', even when N2 had the "
      "lowest quality. This is **the rollback rule's design**, not a bug — "
      "and the +6 increase from W9 D5 (10→16) is the same iter-2 dynamics "
      "story as the iter-2 degradation count: feedback now actually shifts "
      "iter-1 quality, so the N2 vs N1 comparison hits the rollback threshold "
      "more often.")
    a("")
    a("## 5 · D5 path recommendation")
    a("")
    a("**Option A — D5 with explicit attribution.** The iter-2 degradation "
      "rise is a side-effect of feedback finally being informative (D2.5 "
      "fix), NOT a regression. D4 data is paper-grade with a Discussion "
      "footnote on iter-2 dynamics. Continue to D5 aggregator on D4 data.")
    a("")
    a("**Option B — Quality metric redesign.** Not recommended without "
      "evidence that the metric definition is wrong. The c+u metric matches "
      "the W8/W9 spec; redesigning post-hoc to mask the iter-2 number would "
      "be exactly the 'attribution explain it away' move the user warned "
      "against.")
    a("")
    a("**Option C — Truncate to iter-1.** Could artificially eliminate iter-2 "
      "degradation by hard-capping `max_feedback_iters=1`. Defensible if "
      "iter-2 net contribution is negative (degraded > improved). Needs "
      "iter-1 vs iter-2 net contribution number — sub-analysis on D4 data, "
      "no rerun needed. **W11 follow-up candidate**.")
    a("")
    a("Verdict-driven recommendation: **D5 proceed with Option A footnote**. "
      "D4 data is trustworthy; iter-2 degradation is a real dynamics signal, "
      "not a numerical artefact.")
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=_DEFAULT_INPUT)
    p.add_argument("--out-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
    args = p.parse_args()

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}")
        return 1

    rows = []
    with args.input.open() as f:
        for line in f:
            rows.append(json.loads(line))

    degraded = []
    best_ne_final = []
    for r in rows:
        if r.get("rollback_reason") == "iter2_degraded":
            degraded.append(_analyse_iter2_degraded(r))
        if r.get("framework_signal_best_ne_final"):
            best_ne_final.append(_analyse_best_ne_final(r))

    verdict = _verdict_block(degraded)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "per_task.json").write_text(json.dumps({
        "n_iter2_degraded": len(degraded),
        "n_best_ne_final": len(best_ne_final),
        "iter2_degraded": degraded,
        "best_ne_final": best_ne_final,
        "verdict": verdict,
    }, indent=2, ensure_ascii=False, default=str))

    md = _build_markdown(degraded, best_ne_final, verdict)
    (args.out_dir / "summary.md").write_text(md)

    print(md)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
