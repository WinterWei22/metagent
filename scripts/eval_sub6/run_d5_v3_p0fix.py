"""Phase B1 P0 Stage A — D5 v3 P0 fix rerun (seed 0 only).

Runs the full 63-task v3 benchmark with the P0-fixed ``_quality_score``
(commit 2a2eeb9). Mirrors the D5 v2 config (T=0, K=10, max_iter=2,
literature tool exposed, RaMP tool exposed) so the new run can be
compared field-for-field against ``b1_d5_v2_full_feedback_lit/``.

Output layout (mirrors D5 v2):

    data/eval/sub6/b1_d5_v3_p0fix_seed0/
        seed_0/
            <task_id>/result.json
            <task_id>/verdict_final.json
            <task_id>/persist/...
            seed_summary.json          (post-run, via canonical aggregator)

Usage:
    PYTHONPATH=. python scripts/eval_sub6/run_d5_v3_p0fix.py \
        --out-dir data/eval/sub6/b1_d5_v3_p0fix_seed0/seed_0 \
        --workers 10
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evaluation.sub6.io_utils import iter_jsonl
from evaluation.sub6.parallel_runner import (
    make_progress_logger,
    run_tasks_parallel,
)
from evaluation.sub6.run_sub6b import _resolve_api_key
from evaluation.sub6.run_sub6b_react_feedback import (
    DEFAULT_MAX_FEEDBACK_ITERS,
    DEFAULT_MAX_REACT_TURNS,
    DEFAULT_TOTAL_TIMEOUT,
    TaskPersister,
    VerdictReport,
    run_sub6b_react_feedback,
)
from scripts.eval_sub6.grade_with_verifier import (
    _build_driver_lookup,
    _build_source_report,
)
from verifier.agent import verify_sub6


def _build_verifier_fn(task: dict, ramp_db_path: str, driver_lookup):
    source_report = _build_source_report(task)

    def verifier_fn(narrative: str) -> VerdictReport:
        v = verify_sub6(
            narrative, source_report,
            trace_id=f"{task['task_id']}.d5_v3_p0fix",
            ramp_db_path=ramp_db_path,
            driver_lookup=driver_lookup,
        )
        total = Counter(c.verdict.value for c in v.claims_v2)
        return VerdictReport(
            claims=list(v.claims_v2),
            verdicts_total=dict(total),
            dropped_claims=list(getattr(v, "dropped_claims", []) or []),
            task_outcome=getattr(
                getattr(v, "task_outcome", None), "value", "normal"
            ),
        )

    return verifier_fn


def _verdict_final_from_report(report: VerdictReport) -> dict:
    """Produce verdict_final.json contents matching D5 v2 schema."""
    claims = report.claims
    dropped = report.dropped_claims or []
    return {
        "task_outcome": report.task_outcome,
        "n_emitted": len(claims) + len(dropped),
        "n_post_grammar": len(claims),
        "n_dropped": len(dropped),
        "verdicts_total": dict(report.verdicts_total or {}),
    }


def make_processor(
    *, out_root: Path, ramp_db_path: str, driver_lookup,
    max_react_turns: int, max_feedback_iters: int, total_timeout: float,
    model: str, provider: str,
):
    def process_one(task: dict) -> dict:
        tid = task["task_id"]
        task_dir = out_root / tid
        task_dir.mkdir(parents=True, exist_ok=True)
        result_path = task_dir / "result.json"
        verdict_path = task_dir / "verdict_final.json"
        if result_path.exists() and verdict_path.exists():
            # Idempotent resume.
            return {"task_id": tid, "resumed": True}

        verifier_fn = _build_verifier_fn(task, ramp_db_path, driver_lookup)
        persister = TaskPersister(task_dir / "persist", tid)
        t0 = time.perf_counter()
        result = run_sub6b_react_feedback(
            task,
            verifier_fn=verifier_fn,
            model=model,
            provider=provider,
            max_react_turns=max_react_turns,
            max_feedback_iterations=max_feedback_iters,
            total_timeout=total_timeout,
            persister=persister,
        )
        elapsed = time.perf_counter() - t0

        # Persist result.
        result_path.write_text(
            json.dumps(asdict(result), ensure_ascii=False, default=str, indent=None) + "\n"
        )

        # Re-grade the final narrative to obtain verdict_final.json with
        # the full schema (n_emitted / n_post_grammar / n_dropped /
        # task_outcome / verdicts_total). The runner only stored
        # per-iter verdict_total inline; we need the wider schema for
        # the canonical aggregator's NORMAL-only ratios.
        try:
            final_verdict = verifier_fn(result.final_narrative or "")
        except Exception as e:  # noqa: BLE001
            final_verdict = VerdictReport(
                claims=[], verdicts_total={}, dropped_claims=[],
                task_outcome="empty_system_failure",
            )
        verdict_path.write_text(
            json.dumps(_verdict_final_from_report(final_verdict), indent=2)
        )

        return {
            "task_id": tid,
            "elapsed": elapsed,
            "n_feedback_iterations": result.n_feedback_iterations,
            "final_iter_idx": result.final_iter_idx,
            "error": result.error,
        }

    return process_one


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--tasks",
        default="data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl",
    )
    p.add_argument(
        "--curated",
        default="data/benchmark/sub6/curated_hmdb_mammalian.jsonl",
    )
    p.add_argument(
        "--ramp-db",
        default=os.environ.get(
            "METAGENT_RAMP_PATH",
            "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite",
        ),
    )
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--workers", type=int, default=10)
    p.add_argument("--max-react-turns", type=int, default=DEFAULT_MAX_REACT_TURNS)
    p.add_argument("--max-feedback-iters", type=int, default=DEFAULT_MAX_FEEDBACK_ITERS)
    p.add_argument("--total-timeout", type=float, default=DEFAULT_TOTAL_TIMEOUT)
    p.add_argument("--model", default="MiniMax-M2.7")
    p.add_argument("--provider", default="minimax", choices=("minimax", "openai"))
    p.add_argument("--task-id", action="append", help="Optional whitelist (debug)")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    all_tasks = list(iter_jsonl(args.tasks))
    if args.task_id:
        wanted = set(args.task_id)
        all_tasks = [t for t in all_tasks if t["task_id"] in wanted]
    print(f"Running {len(all_tasks)} tasks with K={args.workers} workers")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    driver_lookup = _build_driver_lookup(Path(args.curated))

    _resolve_api_key(args.provider, args.model)

    processor = make_processor(
        out_root=args.out_dir,
        ramp_db_path=args.ramp_db,
        driver_lookup=driver_lookup,
        max_react_turns=args.max_react_turns,
        max_feedback_iters=args.max_feedback_iters,
        total_timeout=args.total_timeout,
        model=args.model,
        provider=args.provider,
    )

    progress = make_progress_logger(total=len(all_tasks), prefix="task")
    t0 = time.perf_counter()
    outcomes = run_tasks_parallel(
        all_tasks, processor,
        max_workers=args.workers,
        on_progress=progress,
    )
    elapsed = time.perf_counter() - t0

    n_ok = sum(1 for o in outcomes if o.error is None)
    n_err = len(outcomes) - n_ok
    print(f"\nDone in {elapsed:.0f}s. ok={n_ok} err={n_err}")
    if n_err:
        for o in outcomes:
            if o.error:
                print(f"  ERROR {o.task_id}: {o.error}")
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
