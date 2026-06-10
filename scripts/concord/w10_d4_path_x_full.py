"""W10 D4 — Path X LLM-agent full 63-task re-run on trustworthy config.

Forked from `scripts/concord/w9_d5_path_x_full.py`. The W9 D5 numbers
were contaminated by the silent feedback-builder bug surfaced during
W10 D2 RED — contradicted / unsupported / UV / dropped claims were not
being forwarded to the iter ≥ 1 feedback prompt due to a
``str(Enum)`` enum-equality mismatch (Python 3.11+) and a missing wire
on the UV / dropped axes. W10 D2 + D2.5 + D3 closed all four feedback
axes plus regression-locked the zero-LLM extract path. **This rerun is
the first metagent-v2 paper-grade dataset.**

Differences from W9 D5 driver:
  - Trace prefix:        concord_w10_d4   (was concord_w9_d5)
  - Output dir:          data/concord/w10_d4_path_x_full/
  - LLM call log:        logs/concord/w10_d4_path_x.jsonl
  - Terminal verdict:    "W10 D4" framing
Everything else (K=10 concurrent, MiniMax-M2.7, max_react_turns=8,
max_feedback_iters=2, benchmark md5) is identical to W9 D5.

W10 prompt stop-conditions (D4 spec):
  - task wall > 1200s (single-task timeout, B1/W8 spec)
  - 2 consecutive task timeouts → halt
  - mid-run cost > $20 → ping
  - rate-limit > 5 affected → ping
  - ≥ 5 verifier crashes → halt
  - iter-2 degradation rate > W9 D5's 11.1% → halt (D2.5 fix regression)
  - total wall > 3h → halt

Run via:
    PYTHONPATH=. METAGENT_LLM_LOG_PATH=logs/concord/w10_d4_path_x.jsonl \\
        python scripts/concord/w10_d4_path_x_full.py
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from common.llm_client import chat_with_tools as _llm_chat
from verifier.helpers.judge_cost_cap import reset_run_level_tracker
from verifier.agent import verify_sub6 as _b1_verify_sub6

from concord.agent.react_runner import ConcordReactRunner
from evaluation.concord.path_x import _per_task_signals, aggregate_path_x


_BENCHMARK = Path("data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")
_DEFAULT_K = 10
_TRACE_PREFIX = "concord_w10_d4"


_write_lock = threading.Lock()


def _run_one(
    task: dict[str, Any],
    runner: ConcordReactRunner,
    out_full_dir: Path | None,
    out_jsonl_fh,
    progress_lock: threading.Lock,
    counter: dict[str, int],
    n_tasks: int,
) -> dict[str, Any] | None:
    """One worker: run + signal-extract + flush jsonl line.

    Returns the per-task signals dict (or None if crashed). Designed
    to be called under a ThreadPoolExecutor with shared runner +
    counters.
    """
    tid = task.get("task_id", "unknown")
    t0 = time.time()
    trace_id = f"{_TRACE_PREFIX}.{tid}"
    try:
        fb = runner.run_task_with_feedback(task, trace_id=trace_id)
    except Exception as exc:
        wall = time.time() - t0
        with progress_lock:
            counter["done"] += 1
            counter["crash"] += 1
            done = counter["done"]
        logging.exception("[%d/%d] %s crashed: %s", done, n_tasks, tid, exc)
        signals = {
            "task_id": tid,
            "framework_signal_crash": f"{type(exc).__name__}: {exc}",
            "wall_seconds": wall,
        }
        with _write_lock:
            out_jsonl_fh.write(json.dumps(signals) + "\n")
            out_jsonl_fh.flush()
        return signals

    wall = time.time() - t0
    signals = _per_task_signals(task, fb)
    signals["wall_seconds_observed"] = wall

    if out_full_dir is not None:
        # Save full ConcordFeedbackResult (3-iter trace) per task
        full_path = out_full_dir / f"{tid}.json"
        try:
            full_path.write_text(json.dumps(
                dataclasses.asdict(fb),
                ensure_ascii=False, indent=2, default=str,
            ))
        except Exception as exc:  # pragma: no cover
            logging.warning("failed to dump full result for %s: %s", tid, exc)

    with _write_lock:
        out_jsonl_fh.write(json.dumps(signals) + "\n")
        out_jsonl_fh.flush()
    with progress_lock:
        counter["done"] += 1
        done = counter["done"]
        if signals.get("rollback_reason") == "feedback_made_it_worse":
            counter["rollback"] += 1
        if signals.get("framework_signal_bridge_in_iters"):
            counter["bridge"] += 1
    logging.info(
        "[%d/%d] %s done in %.1fs  final_iter=%s rollback=%s bridge=%s",
        done, n_tasks, tid, wall,
        signals.get("final_iter_idx"),
        signals.get("rollback_reason") or "-",
        signals.get("framework_signal_bridge_in_iters"),
    )
    return signals


def _aggregate_token_usage(llm_log: Path, task_ids: list[str]) -> dict[str, Any]:
    """Parse the LLM call log produced during the D5 run and tally
    prompt + completion + total tokens, grouped by task_id (extracted
    from trace_id which starts with `concord_w9_d5.<task_id>`)."""
    if not llm_log.exists():
        return {"present": False, "reason": f"log file missing at {llm_log}"}

    per_task_prompt = {tid: 0 for tid in task_ids}
    per_task_completion = {tid: 0 for tid in task_ids}
    per_task_total = {tid: 0 for tid in task_ids}
    per_task_call_count = {tid: 0 for tid in task_ids}
    global_call_count = 0
    unattributed = 0
    with llm_log.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            trace = rec.get("trace_id") or ""
            if not trace.startswith(_TRACE_PREFIX):
                continue
            # trace shape: concord_w9_d5.<task_id>.iter0.turn1 / .verify.s1s2 etc.
            suffix = trace[len(_TRACE_PREFIX) + 1:]
            tid_match = None
            for tid in task_ids:
                if suffix.startswith(tid):
                    tid_match = tid
                    break
            if tid_match is None:
                unattributed += 1
                continue
            global_call_count += 1
            per_task_call_count[tid_match] += 1
            pt = rec.get("prompt_tokens") or 0
            ct = rec.get("completion_tokens") or 0
            tt = rec.get("total_tokens") or (pt + ct)
            per_task_prompt[tid_match] += pt
            per_task_completion[tid_match] += ct
            per_task_total[tid_match] += tt

    totals_list = sorted(per_task_total.values())
    n = len(totals_list)
    if n == 0:
        return {"present": True, "n_calls": 0, "reason": "no W9 D5 trace_ids in log"}

    def _pct(xs, q):
        i = max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1)))))
        return int(xs[i])

    saturate_threshold = 120_000  # MiniMax-M2.7 ~128k tokens; flag ≥120k
    n_saturate = sum(1 for t in totals_list if t >= saturate_threshold)
    return {
        "present": True,
        "n_calls_total": global_call_count,
        "n_calls_unattributed": unattributed,
        "per_task_total_tokens_median": _pct(totals_list, 0.5),
        "per_task_total_tokens_p95": _pct(totals_list, 0.95),
        "per_task_total_tokens_max": max(totals_list),
        "per_task_total_tokens_min": min(totals_list),
        "per_task_prompt_total": sum(per_task_prompt.values()),
        "per_task_completion_total": sum(per_task_completion.values()),
        "per_task_total_total": sum(per_task_total.values()),
        "saturate_threshold": saturate_threshold,
        "saturate_count": n_saturate,
        "saturate_pct_of_tasks": round(100.0 * n_saturate / n, 2),
        "per_task_breakdown": {
            tid: {
                "prompt": per_task_prompt[tid],
                "completion": per_task_completion[tid],
                "total": per_task_total[tid],
                "n_calls": per_task_call_count[tid],
            } for tid in task_ids
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=_BENCHMARK)
    parser.add_argument("--output", type=Path,
                         default=Path("data/concord/w10_d4_path_x_full/path_x_full63_results.jsonl"))
    parser.add_argument("--summary", type=Path,
                         default=Path("data/concord/w10_d4_path_x_full/path_x_full63_summary.json"))
    parser.add_argument("--full-dir", type=Path,
                         default=Path("data/concord/w10_d4_path_x_full/path_x_full"))
    parser.add_argument("--k-concurrent", type=int, default=_DEFAULT_K)
    parser.add_argument("--limit", type=int, default=None,
                         help="Cap task count for smoke testing the driver.")
    parser.add_argument("--llm", default="MiniMax-M2.7")
    parser.add_argument("--provider", default="minimax")
    parser.add_argument("--max-react-turns", type=int, default=8)
    parser.add_argument("--max-feedback-iters", type=int, default=2)
    parser.add_argument("--judge-cost-cap-usd", type=float, default=2.0)
    parser.add_argument(
        "--llm-log", type=Path,
        default=Path(os.environ.get("METAGENT_LLM_LOG_PATH")
                     or "logs/concord/w10_d4_path_x.jsonl"),
        help="LLM call log path (also set METAGENT_LLM_LOG_PATH env if "
             "running through shells that read it).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Ensure log dir exists (chat_with_tools writes here per LLM call)
    args.llm_log.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("METAGENT_LLM_LOG_PATH", str(args.llm_log))

    # Load benchmark (63 tasks)
    if not args.benchmark.exists():
        raise FileNotFoundError(f"benchmark missing at {args.benchmark}")
    tasks: list[dict[str, Any]] = []
    with args.benchmark.open() as f:
        for line in f:
            tasks.append(json.loads(line))
            if args.limit is not None and len(tasks) >= args.limit:
                break
    n_tasks = len(tasks)
    task_ids = [t["task_id"] for t in tasks]
    logging.info("Loaded %d tasks from %s", n_tasks, args.benchmark)
    reset_run_level_tracker(
        run_id=str(args.output),
        cap_usd=args.judge_cost_cap_usd,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.full_dir.mkdir(parents=True, exist_ok=True)

    runner = ConcordReactRunner(
        chat_with_tools=_llm_chat,
        verifier_fn=_b1_verify_sub6,
        llm_model=args.llm,
        llm_provider=args.provider,
        max_react_turns=args.max_react_turns,
        max_feedback_iters=args.max_feedback_iters,
    )

    progress_lock = threading.Lock()
    counter = {"done": 0, "crash": 0, "rollback": 0, "bridge": 0}
    per_task_signals_list: list[dict[str, Any]] = []
    started = time.time()
    with args.output.open("w") as out_fh, ThreadPoolExecutor(
        max_workers=args.k_concurrent
    ) as pool:
        futs = [
            pool.submit(
                _run_one, t, runner, args.full_dir,
                out_fh, progress_lock, counter, n_tasks,
            )
            for t in tasks
        ]
        for fut in as_completed(futs):
            try:
                sig = fut.result()
                if sig is not None:
                    per_task_signals_list.append(sig)
            except Exception as exc:  # pragma: no cover
                logging.exception("worker future raised: %s", exc)
    elapsed = time.time() - started

    # Aggregate framework signals
    summary = aggregate_path_x(per_task_signals_list)
    summary["total_wall_seconds"] = round(elapsed, 1)
    summary["wall_human"] = f"{elapsed / 60:.1f} min"
    summary["k_concurrent"] = args.k_concurrent
    summary["llm_model"] = args.llm
    summary["benchmark_md5_assumed"] = "331b30a64017debe9d5ce07ed238e4f5"

    # Aggregate token usage from LLM log
    token_stats = _aggregate_token_usage(args.llm_log, task_ids)
    summary["token_usage"] = token_stats

    args.summary.write_text(json.dumps(summary, indent=2, default=str))

    # Terminal verdict
    print()
    print("=" * 70)
    print("=== W10 D4 Path X full 63-task — post D2/D2.5/D3 trustworthy config ===")
    print("=" * 70)
    print(json.dumps(summary, indent=2, default=str))
    print(f"\n(wall {elapsed/60:.1f} min,  jsonl → {args.output})")
    return 0 if counter["crash"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
