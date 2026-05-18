"""W8 D5 Path X — LLM-agent ConcordMet on sub6b-v3 (closed-loop, batch).

Per task:
  1. Build ConcordReactRunner with chat_with_tools=common.llm_client.chat_with_tools
     and verifier_fn=verifier.agent.verify_sub6
  2. Call run_task_with_feedback(task) → ConcordFeedbackResult (3 iters max)
  3. Compute per-task framework signals (rollback / best-iter ≠ final-iter
     / tool-call count > 25 / wall / etc.)
  4. Flush per-task record to jsonl so partial runs are usable

D5 SCOPING NOTE: each task wall is ~18 min (D4 smoke baseline = 3 iters
× ~6 min each). Full 63-task sequential run is ~19h, exceeding the D5
budget. D5 runs a **stratified 5-task sample** instead; full 63-task
deferred to W9 (after the D2 handler-output-shape bug is patched —
see framework health report). Pass --limit / --task-ids to override.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from common.llm_client import chat_with_tools as _llm_chat
from verifier.agent import verify_sub6 as _b1_verify_sub6

from concord.agent.react_runner import ConcordReactRunner


_DEFAULT_BENCHMARK = Path("data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")

# D5 stratified 5-task sample (per "framework health, not paper data"):
#   - 2× lipid WP167 seeds (paper-critical bridging trajectory)
#   - 1× steroid Androgen/Estrogen (D4 smoke 1 baseline)
#   - 1× tryptophan metabolism (different pathway type)
#   - 1× galactose metabolism (yet another type)
D5_STRATIFIED_TASK_IDS: tuple[str, ...] = (
    "compound_only_enrich_mammalian_lm_pathway_WP167_seed3",
    "compound_only_enrich_mammalian_lm_pathway_WP167_seed7",
    "compound_only_enrich_mammalian_RAMP_P_000000421_seed1",
    "compound_only_enrich_mammalian_RAMP_P_000000141_seed0",
    "compound_only_enrich_mammalian_RAMP_P_000000398_seed0",
)


# ---------------------------------------------------------------------------
# Per-task signal extraction
# ---------------------------------------------------------------------------


def _gt_pathway_namespaces_signal(react_result, gt_pathway: dict) -> dict[str, Any]:
    """Detect whether the iter's claims / narrative mention ground truth
    in any of three ways."""
    text = (react_result.final_narrative_text or "")
    gt_name = (gt_pathway.get("pathway_name") or "")
    gt_id = gt_pathway.get("pathway_id") or ""
    gt_ext = gt_pathway.get("external_id") or ""

    literal_name = bool(gt_name) and gt_name.lower() in text.lower()
    literal_id = any(needle and needle in text for needle in (gt_id, gt_ext))
    claim_id_hit = any(
        (c.get("pathway_id") or "").lower() in {gt_id.lower(), f"wp:{gt_ext.lower()}"}
        for c in (react_result.final_claims or [])
    )
    return {
        "narrative_mentions_gt_name": literal_name,
        "narrative_mentions_gt_id": literal_id,
        "any_claim_matches_gt_pathway_id": claim_id_hit,
        "bridging_signal": literal_name or literal_id or claim_id_hit,
        "claim_namespaces": sorted({
            (c.get("pathway_id") or "").split(":", 1)[0]
            for c in (react_result.final_claims or [])
            if c.get("pathway_id")
        }),
    }


def _per_task_signals(
    task: dict[str, Any],
    feedback_result,
) -> dict[str, Any]:
    """Reduce a ConcordFeedbackResult to D5 framework signals."""
    gt_pathway = task.get("ground_truth_pathway") or {}
    iters = list(feedback_result.iterations)
    final_idx = feedback_result.final_iter_idx

    per_iter = []
    best_iter_idx = 0
    best_quality = float("inf")
    best_bridge_iter_idx = None
    for rec in iters:
        rr = rec.react_result
        vo = rec.verification
        sig = _gt_pathway_namespaces_signal(rr, gt_pathway)
        ir = rr.iterations[0] if rr.iterations else None
        per_iter.append({
            "iter_idx": rec.iter_idx,
            "task_outcome": rr.task_outcome,
            "n_turns": ir.n_turns if ir else 0,
            "n_tool_calls": ir.n_tool_calls if ir else 0,
            "force_finalised": bool(ir and ir.force_finalised),
            "inner_retry_used": bool(ir and ir.inner_retry_used),
            "wall_seconds": rr.elapsed_seconds,
            "n_distinct_tools_called": rr.n_distinct_tools_called,
            "tools_called": rr.tools_called,
            "n_claims": len(rr.final_claims or []),
            "verifier_ok": vo.ok,
            "verifier_error": vo.error,
            "n_supported": vo.n_supported,
            "n_unsupported": vo.n_unsupported,
            "n_contradicted": vo.n_contradicted,
            "n_unverifiable_v0": vo.n_unverifiable_v0,
            "quality": vo.quality,
            **sig,
        })
        # Track best-quality iter (independent of rollback selection)
        if vo.quality < best_quality:
            best_quality = vo.quality
            best_iter_idx = rec.iter_idx
        # Track first iter that bridged (if any)
        if sig["bridging_signal"] and best_bridge_iter_idx is None:
            best_bridge_iter_idx = rec.iter_idx

    return {
        "task_id": feedback_result.task_id,
        "gt_pathway_name": gt_pathway.get("pathway_name"),
        "gt_external_id": gt_pathway.get("external_id"),
        "final_iter_idx": final_idx,
        "rollback_reason": feedback_result.rollback_reason,
        "n_feedback_iterations": feedback_result.n_feedback_iterations,
        "best_iter_idx": best_iter_idx,
        "best_iter_quality": best_quality,
        "framework_signal_best_ne_final": best_iter_idx != final_idx,
        "best_bridge_iter_idx": best_bridge_iter_idx,
        "framework_signal_bridge_in_iters": best_bridge_iter_idx is not None,
        "framework_signal_bridge_lost_to_rollback": (
            best_bridge_iter_idx is not None and best_bridge_iter_idx != final_idx
        ),
        "iter_calls_max": max((it["n_tool_calls"] for it in per_iter), default=0),
        "iter_calls_total": sum(it["n_tool_calls"] for it in per_iter),
        "iter_walls_total": sum(it["wall_seconds"] for it in per_iter),
        "per_iter": per_iter,
    }


# ---------------------------------------------------------------------------
# Batch driver
# ---------------------------------------------------------------------------


def _load_tasks(benchmark: Path, task_ids: list[str] | None,
                 limit: int | None) -> list[dict[str, Any]]:
    if not benchmark.exists():
        raise FileNotFoundError(f"benchmark missing at {benchmark}")
    wanted: set[str] | None = set(task_ids) if task_ids else None
    out: list[dict[str, Any]] = []
    with benchmark.open() as f:
        for line in f:
            row = json.loads(line)
            if wanted is not None and row.get("task_id") not in wanted:
                continue
            out.append(row)
            if limit is not None and len(out) >= limit:
                break
    if wanted is not None and len(out) < len(wanted):
        missing = wanted - {r["task_id"] for r in out}
        raise KeyError(
            f"task_ids not found in benchmark: {sorted(missing)}"
        )
    return out


def run_path_x_batch(
    *,
    benchmark: Path = _DEFAULT_BENCHMARK,
    task_ids: list[str] | None = None,
    limit: int | None = None,
    out_jsonl: Path,
    out_summary_json: Path,
    out_full_dir: Path | None = None,
    llm_model: str = "MiniMax-M2.7",
    llm_provider: str = "minimax",
) -> dict[str, Any]:
    tasks = _load_tasks(benchmark, task_ids, limit)
    runner = ConcordReactRunner(
        chat_with_tools=_llm_chat,
        verifier_fn=_b1_verify_sub6,
        llm_model=llm_model,
        llm_provider=llm_provider,
    )

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    if out_full_dir is not None:
        out_full_dir.mkdir(parents=True, exist_ok=True)
    per_task_signals: list[dict[str, Any]] = []
    started = time.time()
    with out_jsonl.open("w") as out:
        for i, task in enumerate(tasks):
            t0 = time.time()
            tid = task["task_id"]
            logging.info("[%d/%d] %s", i + 1, len(tasks), tid)
            try:
                fb = runner.run_task_with_feedback(task)
            except Exception as exc:
                logging.exception("task %s crashed: %s", tid, exc)
                signals = {
                    "task_id": tid,
                    "framework_signal_crash": f"{type(exc).__name__}: {exc}",
                    "wall_seconds": time.time() - t0,
                }
                per_task_signals.append(signals)
                out.write(json.dumps(signals) + "\n"); out.flush()
                continue
            signals = _per_task_signals(task, fb)
            per_task_signals.append(signals)
            out.write(json.dumps(signals) + "\n"); out.flush()
            if out_full_dir is not None:
                full_path = out_full_dir / f"{tid}.json"
                full_path.write_text(json.dumps(
                    dataclasses.asdict(fb), ensure_ascii=False,
                    indent=2, default=str,
                ))
            logging.info("[%d/%d] %s done in %.1fs final_iter=%s rollback=%s",
                         i + 1, len(tasks), tid, time.time() - t0,
                         signals.get("final_iter_idx"),
                         signals.get("rollback_reason"))

    elapsed = time.time() - started
    summary = aggregate_path_x(per_task_signals)
    summary["total_wall_seconds"] = elapsed
    out_summary_json.parent.mkdir(parents=True, exist_ok=True)
    out_summary_json.write_text(json.dumps(summary, indent=2))
    return summary


def aggregate_path_x(per_task: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(per_task)
    n_crash = sum(1 for r in per_task if r.get("framework_signal_crash"))
    valid = [r for r in per_task if not r.get("framework_signal_crash")]

    def _bool_count(key: str) -> int:
        return sum(1 for r in valid if r.get(key))

    outcomes: dict[str, int] = {}
    for r in valid:
        for it in (r.get("per_iter") or []):
            o = it.get("task_outcome", "unknown")
            outcomes[o] = outcomes.get(o, 0) + 1

    return {
        "n_tasks": n,
        "n_crash": n_crash,
        "n_valid": len(valid),
        "by_iter_outcome": outcomes,
        "early_exit_iter0": sum(1 for r in valid
                                  if r.get("n_feedback_iterations") == 0
                                  and (r.get("per_iter") or [{}])[0].get("quality") == 0),
        "n_feedback_iter1": sum(1 for r in valid
                                  if r.get("n_feedback_iterations") >= 1),
        "n_feedback_iter2": sum(1 for r in valid
                                  if r.get("n_feedback_iterations") >= 2),
        "rollback_total": _bool_count("rollback_reason"),
        "rollback_feedback_made_it_worse": sum(
            1 for r in valid if r.get("rollback_reason") == "feedback_made_it_worse"),
        "rollback_iter2_degraded": sum(
            1 for r in valid if (r.get("rollback_reason") or "").endswith("_degraded")),
        "framework_signal_bridge_in_iters": _bool_count("framework_signal_bridge_in_iters"),
        "framework_signal_bridge_lost_to_rollback": _bool_count("framework_signal_bridge_lost_to_rollback"),
        "framework_signal_best_ne_final": _bool_count("framework_signal_best_ne_final"),
        "tool_call_max_distribution": {
            "max":   max((r["iter_calls_max"] for r in valid), default=0),
            "p95":   _percentile([r["iter_calls_max"] for r in valid], 0.95),
            "median": _percentile([r["iter_calls_max"] for r in valid], 0.5),
            "n_over_25": sum(1 for r in valid if r["iter_calls_max"] > 25),
        },
        "mean_wall_seconds_per_task": (
            sum(r["iter_walls_total"] for r in valid) / max(1, len(valid))
        ),
    }


def _percentile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    idx = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return float(s[idx])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=_DEFAULT_BENCHMARK)
    parser.add_argument("--out-jsonl", type=Path,
                         default=Path("data/concord/w8_llm_agent/path_x_results.jsonl"))
    parser.add_argument("--out-summary", type=Path,
                         default=Path("data/concord/w8_llm_agent/path_x_summary.json"))
    parser.add_argument("--out-full-dir", type=Path,
                         default=Path("data/concord/w8_llm_agent/path_x_full"))
    parser.add_argument("--limit", type=int, default=None,
                         help="Cap task count; use --d5-stratified for the 5-task sample.")
    parser.add_argument("--d5-stratified", action="store_true",
                         help="Use the D5 5-task stratified sample (lipid + steroid + other).")
    parser.add_argument("--task-id", action="append", default=None,
                         help="Run a specific task_id (repeatable).")
    parser.add_argument("--model", default="MiniMax-M2.7")
    parser.add_argument("--provider", default="minimax")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s %(levelname)s %(name)s %(message)s")

    task_ids = list(args.task_id) if args.task_id else None
    if args.d5_stratified:
        task_ids = list(D5_STRATIFIED_TASK_IDS)
    summary = run_path_x_batch(
        benchmark=args.benchmark,
        task_ids=task_ids,
        limit=args.limit,
        out_jsonl=args.out_jsonl,
        out_summary_json=args.out_summary,
        out_full_dir=args.out_full_dir,
        llm_model=args.model,
        llm_provider=args.provider,
    )
    print(f"\n=== Path X (LLM-agent) — {summary['n_tasks']} tasks ===")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
