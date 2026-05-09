"""A2 D4 — 3-way smoke (single-call / react-only / react+feedback) on 5 v3 tasks.

Per A2 phase plan:
  Step 1: MiniMax single-call narrative (run_sub6b)
  Step 2: MiniMax ReAct-only narrative  (run_sub6b_react library call —
          A1 CLI's openai-only guard is bypassed by direct invocation)
  Step 3: MiniMax ReAct + verifier feedback (run_sub6b_feedback_from_narrative
          reusing Step 2's narrative as iter 0 — saves ~50% wall time
          and prevents the LLM-nondeterminism drift that re-running
          ReAct would introduce)

Acceptance gate (no metric interpretation; D5 does that):
  - 5 task × 3 variants × 1 verifier-grading-pass each = 15 narratives,
    15 verdict files all on disk
  - sha256(react narrative) == sha256(feedback iter-0 narrative) for all
    5 tasks (the reuse check)
  - Schema-consistent: all narrative records have {task_id, narrative,
    elapsed_seconds, ...}; all verdict records have
    {task_id, verdicts_total, claims}.

Output layout::

    data/eval/sub6/v4_a2_d4/single/{task_id}/narrative.json
                                   verdict.json
                            react/{task_id}/narrative.json
                                   verdict.json
                            feedback/{task_id}/result.json
                                       verdict.json
                                       persist/...   (D2 turns + iterations)
                            summary.json
                            hash_check.json
"""
from __future__ import annotations

import argparse
import hashlib
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
from evaluation.sub6.persist import TaskPersister
from evaluation.sub6.run_sub6b import run_sub6b, _resolve_api_key
from evaluation.sub6.run_sub6b_react import run_sub6b_react
from evaluation.sub6.run_sub6b_react_feedback import (
    VerdictReport,
    run_sub6b_feedback_from_narrative,
)
from scripts.eval_sub6.grade_with_verifier import (
    _build_driver_lookup,
    _build_source_report,
)
from verifier.agent import verify_sub6

logger = logging.getLogger(__name__)


# Default 5-task pick (deterministic).
DEFAULT_TASK_IDS = [
    "compound_only_enrich_mammalian_RAMP_P_000000016_seed1",       # amino_acid
    "compound_only_enrich_mammalian_RAMP_P_000000398_seed0",       # central
    "compound_only_enrich_mammalian_RAMP_P_000053306_seed1",       # nucleotide (F4)
    "compound_only_enrich_mammalian_lm_pathway_WP167_seed4",       # lipid (D3 reuse)
    "compound_only_enrich_mammalian_RAMP_P_000050021_seed0",       # other
]


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _verdict_summary(claims) -> dict[str, int]:
    return dict(Counter(c.verdict.value for c in claims))


def _make_verifier_fn(task: dict, *, ramp_db_path: str, driver_lookup: dict[str, str]):
    """Build a (narrative -> VerdictReport) closure for the feedback runner."""
    source_report = _build_source_report(task)

    def call(narrative: str) -> VerdictReport:
        if not narrative.strip():
            return VerdictReport([], {})
        v = verify_sub6(
            narrative, source_report,
            trace_id=f"{task['task_id']}.a2_d4",
            ramp_db_path=ramp_db_path,
            driver_lookup=driver_lookup,
        )
        return VerdictReport(
            claims=list(v.claims_v2),
            verdicts_total=_verdict_summary(v.claims_v2),
        )

    return call


def _grade_narrative(
    *,
    narrative: str,
    task: dict,
    ramp_db_path: str,
    driver_lookup: dict[str, str],
    track: str,
) -> dict:
    """Grade one narrative and return a serialisable verdict record.

    Never raises. Network/MiniMax failures are captured into the record
    so a single bad call does not kill the whole D4 batch.
    """
    if not narrative.strip():
        return {
            "task_id": task["task_id"], "track": track,
            "verdicts_total": {}, "claims": [],
            "warning": "empty narrative — verifier skipped",
        }
    try:
        source_report = _build_source_report(task)
        v = verify_sub6(
            narrative, source_report,
            trace_id=f"{task['task_id']}.{track}.grade",
            ramp_db_path=ramp_db_path,
            driver_lookup=driver_lookup,
        )
    except Exception as exc:
        logger.warning(
            "verifier crashed on %s.%s: %s", task["task_id"], track, exc
        )
        return {
            "task_id": task["task_id"], "track": track,
            "verdicts_total": {}, "claims": [],
            "error": f"verifier_failed: {type(exc).__name__}: {exc}",
        }
    return {
        "task_id": task["task_id"],
        "track": track,
        "verdicts_total": _verdict_summary(v.claims_v2),
        "claims": [c.model_dump(mode="json") for c in v.claims_v2],
    }


def _persist_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )


def _process_one_task(
    task: dict,
    *,
    out_root: Path,
    ramp_db_path: str,
    driver_lookup: dict[str, str],
    max_react_turns: int,
    max_feedback_iters: int,
    total_timeout: float,
) -> dict:
    """Run all three variants for one task. Resume-aware: existing
    narrative.json / result.json files on disk are reused so a re-run
    after a crash skips the LLM-burning steps.

    Returns a dict with ``summary`` and ``hash_pair`` keys.
    """
    tid = task["task_id"]

    # ---------- Step 1: single ----------
    single_dir = out_root / "single" / tid
    single_narrative_path = single_dir / "narrative.json"
    if single_narrative_path.is_file():
        rec = json.loads(single_narrative_path.read_text())
        single_narrative = rec.get("narrative", "")
        single_elapsed = rec.get("elapsed_seconds", 0.0)
        single_error = rec.get("error")
        print(f"  single  : (resume) narr_chars={len(single_narrative)}")
    else:
        t0 = time.perf_counter()
        single_result = run_sub6b(
            task,
            model="MiniMax-M2.7", provider="minimax",
            caller="a2_d4_single", llm_retries=1,
        )
        single_elapsed = time.perf_counter() - t0
        single_narrative = single_result.narrative
        single_error = single_result.error
        _persist_json(
            single_narrative_path,
            {**asdict(single_result), "elapsed_seconds": single_elapsed},
        )
        print(f"  single  : err={single_error} narr_chars={len(single_narrative)} elapsed={single_elapsed:.1f}s")

    single_verdict_path = single_dir / "verdict.json"
    if single_verdict_path.is_file():
        single_verdict = json.loads(single_verdict_path.read_text())
    else:
        single_verdict = _grade_narrative(
            narrative=single_narrative, task=task,
            ramp_db_path=ramp_db_path, driver_lookup=driver_lookup,
            track="a2_d4_single",
        )
        _persist_json(single_verdict_path, single_verdict)

    # ---------- Step 2: react ----------
    react_dir = out_root / "react" / tid
    react_narrative_path = react_dir / "narrative.json"
    if react_narrative_path.is_file():
        rec = json.loads(react_narrative_path.read_text())
        react_narrative = rec.get("narrative", "")
        react_elapsed = rec.get("elapsed_seconds", 0.0)
        react_n_tool_calls = rec.get("n_tool_calls", 0)
        react_n_turns = rec.get("n_turns", 0)
        react_force_fin = rec.get("force_finalised", False)
        react_error = rec.get("error")
        print(f"  react   : (resume) narr_chars={len(react_narrative)}")
    else:
        t0 = time.perf_counter()
        react_result = run_sub6b_react(
            task,
            model="MiniMax-M2.7", provider="minimax",
            max_turns=max_react_turns, total_timeout=total_timeout,
            caller="a2_d4_react",
        )
        react_elapsed = time.perf_counter() - t0
        react_narrative = react_result.narrative
        react_n_tool_calls = react_result.n_tool_calls
        react_n_turns = react_result.n_turns
        react_force_fin = react_result.force_finalised
        react_error = react_result.error
        _persist_json(react_narrative_path, asdict(react_result))
        print(f"  react   : err={react_error} turns={react_n_turns} tools={react_n_tool_calls} elapsed={react_elapsed:.1f}s")

    react_verdict_path = react_dir / "verdict.json"
    if react_verdict_path.is_file():
        react_verdict = json.loads(react_verdict_path.read_text())
    else:
        react_verdict = _grade_narrative(
            narrative=react_narrative, task=task,
            ramp_db_path=ramp_db_path, driver_lookup=driver_lookup,
            track="a2_d4_react",
        )
        _persist_json(react_verdict_path, react_verdict)

    # ---------- Step 3: feedback (iter 0 reused from Step 2) ----------
    feedback_dir = out_root / "feedback" / tid
    feedback_result_path = feedback_dir / "result.json"
    if feedback_result_path.is_file():
        rec = json.loads(feedback_result_path.read_text())
        feedback_final_narrative = rec.get("final_narrative", "")
        feedback_iters = rec.get("iterations", [])
        feedback_n_iterations = rec.get("n_feedback_iterations", 0)
        feedback_final_iter_idx = rec.get("final_iter_idx", 0)
        feedback_rollback = rec.get("rollback_reason")
        feedback_term = rec.get("termination_reason")
        feedback_elapsed = rec.get("elapsed_seconds", 0.0)
        feedback_qualities = [it.get("quality") for it in feedback_iters]
        feedback_error = rec.get("error")
        feedback_iter0_narrative = (
            feedback_iters[0].get("narrative", "") if feedback_iters else ""
        )
        print(f"  feedback: (resume) iters={feedback_n_iterations} q={feedback_qualities}")
    else:
        verifier_fn = _make_verifier_fn(
            task, ramp_db_path=ramp_db_path, driver_lookup=driver_lookup,
        )
        persister = TaskPersister(feedback_dir / "persist", tid)
        feedback_result = run_sub6b_feedback_from_narrative(
            task,
            iter0_narrative=react_narrative,
            iter0_n_tool_calls=react_n_tool_calls,
            iter0_n_turns=react_n_turns,
            iter0_force_finalised=react_force_fin,
            verifier_fn=verifier_fn,
            model="MiniMax-M2.7", provider="minimax",
            max_react_turns=max_react_turns,
            max_feedback_iterations=max_feedback_iters,
            total_timeout=total_timeout,
            persister=persister,
            caller="a2_d4_feedback",
        )
        _persist_json(feedback_result_path, asdict(feedback_result))
        feedback_final_narrative = feedback_result.final_narrative
        feedback_n_iterations = feedback_result.n_feedback_iterations
        feedback_final_iter_idx = feedback_result.final_iter_idx
        feedback_rollback = feedback_result.rollback_reason
        feedback_term = feedback_result.termination_reason
        feedback_elapsed = feedback_result.elapsed_seconds
        feedback_qualities = [it.quality for it in feedback_result.iterations]
        feedback_error = feedback_result.error
        feedback_iter0_narrative = (
            feedback_result.iterations[0].narrative if feedback_result.iterations else ""
        )
        print(
            f"  feedback: err={feedback_error} "
            f"final_iter={feedback_final_iter_idx} q={feedback_qualities} "
            f"rollback={feedback_rollback} term={feedback_term} "
            f"elapsed={feedback_elapsed:.1f}s"
        )

    feedback_verdict_path = feedback_dir / "verdict.json"
    if feedback_verdict_path.is_file():
        feedback_verdict = json.loads(feedback_verdict_path.read_text())
    else:
        feedback_verdict = _grade_narrative(
            narrative=feedback_final_narrative, task=task,
            ramp_db_path=ramp_db_path, driver_lookup=driver_lookup,
            track="a2_d4_feedback",
        )
        _persist_json(feedback_verdict_path, feedback_verdict)

    # ---------- Hash check ----------
    react_hash = _sha256_text(react_narrative)
    feedback_iter0_hash = _sha256_text(feedback_iter0_narrative)
    match = react_hash == feedback_iter0_hash
    print(f"  hash    : react={react_hash[:12]} feedback_iter0={feedback_iter0_hash[:12]} match={match}")

    return {
        "summary": {
            "task_id": tid,
            "single": {
                "narr_chars": len(single_narrative),
                "elapsed_s": round(single_elapsed, 1),
                "verdicts": single_verdict.get("verdicts_total", {}),
                "error": single_error,
            },
            "react": {
                "narr_chars": len(react_narrative),
                "n_tool_calls": react_n_tool_calls,
                "n_turns": react_n_turns,
                "elapsed_s": round(react_elapsed, 1),
                "verdicts": react_verdict.get("verdicts_total", {}),
                "error": react_error,
            },
            "feedback": {
                "narr_chars": len(feedback_final_narrative),
                "n_iterations": feedback_n_iterations,
                "final_iter_idx": feedback_final_iter_idx,
                "rollback_reason": feedback_rollback,
                "termination_reason": feedback_term,
                "elapsed_s": round(feedback_elapsed, 1),
                "verdicts": feedback_verdict.get("verdicts_total", {}),
                "qualities": feedback_qualities,
                "error": feedback_error,
            },
        },
        "hash_pair": {
            "task_id": tid,
            "react_sha256": react_hash,
            "feedback_iter0_sha256": feedback_iter0_hash,
            "match": match,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tasks",
        default="data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl",
    )
    parser.add_argument(
        "--out-dir",
        default="data/eval/sub6/v4_a2_d4",
    )
    parser.add_argument(
        "--curated",
        default="data/benchmark/sub6/curated_hmdb_mammalian.jsonl",
    )
    parser.add_argument(
        "--ramp-db",
        default=os.environ.get(
            "METAGENT_RAMP_PATH",
            "/data/weiwentao/llm_agent_metabolomics/ramp.sqlite",
        ),
    )
    parser.add_argument("--task-id", action="append", help="Override default 5 task IDs (repeatable)")
    parser.add_argument("--max-react-turns", type=int, default=5)
    parser.add_argument("--max-feedback-iters", type=int, default=2)
    parser.add_argument("--total-timeout", type=float, default=600.0)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    task_ids = args.task_id or DEFAULT_TASK_IDS
    tasks_by_id = {t["task_id"]: t for t in iter_jsonl(args.tasks) if t.get("task_id") in task_ids}
    missing = set(task_ids) - set(tasks_by_id)
    if missing:
        sys.stderr.write(f"ERROR: tasks not in {args.tasks}: {sorted(missing)}\n")
        return 2

    # Resolve API keys for both providers (single-call uses minimax via run_sub6b;
    # react/feedback also use minimax through chat_with_tools).
    _resolve_api_key("minimax", "MiniMax-M2.7")

    out_root = Path(args.out_dir)
    driver_lookup = _build_driver_lookup(Path(args.curated))

    summary_rows: list[dict] = []
    hash_pairs: list[dict] = []

    for tid in task_ids:
        task = tasks_by_id[tid]
        print(f"\n=== {tid} ===")
        try:
            row = _process_one_task(
                task,
                out_root=out_root,
                ramp_db_path=args.ramp_db,
                driver_lookup=driver_lookup,
                max_react_turns=args.max_react_turns,
                max_feedback_iters=args.max_feedback_iters,
                total_timeout=args.total_timeout,
            )
            summary_rows.append(row["summary"])
            hash_pairs.append(row["hash_pair"])
        except Exception as exc:
            logger.exception("task %s crashed at top level", tid)
            summary_rows.append({"task_id": tid, "fatal": f"{type(exc).__name__}: {exc}"})
            hash_pairs.append({
                "task_id": tid, "react_sha256": None, "feedback_iter0_sha256": None,
                "match": False, "error": f"{type(exc).__name__}: {exc}",
            })

    _persist_json(out_root / "summary.json", summary_rows)
    _persist_json(
        out_root / "hash_check.json",
        {
            "all_match": all(p["match"] for p in hash_pairs),
            "n_match": sum(1 for p in hash_pairs if p["match"]),
            "n_total": len(hash_pairs),
            "per_task": hash_pairs,
        },
    )

    all_match = all(p["match"] for p in hash_pairs)
    print()
    print(f"=== D4 SUMMARY ===")
    print(f"tasks processed     : {len(summary_rows)}")
    print(f"hash_check all_match: {all_match}  ({sum(1 for p in hash_pairs if p['match'])}/{len(hash_pairs)})")
    print(f"summary             : {out_root / 'summary.json'}")
    print(f"hash_check          : {out_root / 'hash_check.json'}")
    return 0 if all_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
