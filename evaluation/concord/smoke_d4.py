"""W8 D4 — closed-loop smoke driver: ConcordReactRunner + B1 verifier feedback.

Wires `common.llm_client.chat_with_tools` + `verifier.agent.verify_sub6`
into the runner and exercises `run_task_with_feedback` (iter 0 → up to
2 feedback iterations with quality rollback).

The driver's verdict line answers the W8 paper-critical question for
the lipid smoking-gun task: did the closed-loop verifier feedback
bridge the LLM from "Arachidonic acid metabolism (MUMM:00002)" to
"Eicosanoid synthesis (WP:WP167)" between iter 0 and iter 1/2?
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

from common.llm_client import chat_with_tools as llm_chat
from verifier.agent import verify_sub6 as b1_verify_sub6

from concord.agent.react_runner import ConcordReactRunner


_DEFAULT_BENCHMARK = Path("data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")


def _load_task(benchmark: Path, task_id: str) -> dict[str, Any]:
    if not benchmark.exists():
        raise FileNotFoundError(f"benchmark missing at {benchmark}")
    with benchmark.open() as f:
        for line in f:
            row = json.loads(line)
            if row.get("task_id") == task_id:
                return row
    raise KeyError(f"task_id {task_id!r} not found in {benchmark}")


def _save(obj, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = dataclasses.asdict(obj)
    with out.open("w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def _scan_pathway_namespace_bridge(react_result, gt_pathway: dict) -> dict[str, Any]:
    """Inspect one iter's narrative + claims for namespace-bridging
    evidence relative to ground truth."""
    text = (react_result.final_narrative_text or "").lower()
    claims_pid_ns = sorted({
        (c.get("pathway_id") or "").split(":", 1)[0]
        for c in (react_result.final_claims or [])
        if c.get("pathway_id")
    })
    gt_name = (gt_pathway.get("pathway_name") or "").lower()
    gt_id = gt_pathway.get("pathway_id") or ""
    gt_ext = gt_pathway.get("external_id") or ""

    literal_name_hit = bool(gt_name) and gt_name in text
    literal_id_hit = any(needle in (react_result.final_narrative_text or "")
                          for needle in (gt_id, gt_ext) if needle)
    claim_id_hit = any(
        (c.get("pathway_id") or "").lower() in {gt_id.lower(), f"wp:{gt_ext.lower()}"}
        for c in (react_result.final_claims or [])
    )
    return {
        "namespaces_in_claims": claims_pid_ns,
        "narrative_mentions_gt_name": literal_name_hit,
        "narrative_mentions_gt_id": literal_id_hit,
        "any_claim_matches_gt_pathway_id": claim_id_hit,
        "bridging_signal": literal_name_hit or literal_id_hit or claim_id_hit,
    }


def _print_iteration_verdict(idx: int, react_result, verification, gt_pathway) -> None:
    bridge = _scan_pathway_namespace_bridge(react_result, gt_pathway)
    flag = "★ HIT" if bridge["bridging_signal"] else "no bridge"
    print(f"\n--- iter {idx} ---")
    print(f"  outcome={react_result.task_outcome}  turns={react_result.iterations[0].n_turns if react_result.iterations else 0}/8  tool_calls={react_result.iterations[0].n_tool_calls if react_result.iterations else 0}  wall={react_result.elapsed_seconds:.1f}s")
    print(f"  verdict   sup={verification.n_supported}  unsup={verification.n_unsupported}  contra={verification.n_contradicted}  unv={verification.n_unverifiable_v0}  quality={verification.quality}  ok={verification.ok}")
    if verification.error:
        print(f"  verifier_error: {verification.error}")
    print(f"  namespaces in claims: {bridge['namespaces_in_claims']}")
    print(f"  ★ naming bridge: {flag}  (literal name: {bridge['narrative_mentions_gt_name']} / literal id: {bridge['narrative_mentions_gt_id']} / claim-pid match: {bridge['any_claim_matches_gt_pathway_id']})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--benchmark", type=Path, default=_DEFAULT_BENCHMARK)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="MiniMax-M2.7")
    parser.add_argument("--provider", default="minimax")
    parser.add_argument("--max-feedback-iters", type=int, default=2)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    task = _load_task(args.benchmark, args.task_id)

    runner = ConcordReactRunner(
        chat_with_tools=llm_chat,
        verifier_fn=b1_verify_sub6,
        llm_model=args.model,
        llm_provider=args.provider,
        max_feedback_iters=args.max_feedback_iters,
    )

    started = time.time()
    feedback_result = runner.run_task_with_feedback(task)
    elapsed = time.time() - started
    _save(feedback_result, args.out)

    gt = task.get("ground_truth_pathway") or {}
    print(f"\n=== D4 closed-loop verdict — task {task['task_id']} ===")
    print(f"ground_truth: {gt.get('pathway_name')} ({gt.get('pathway_id')})  external_id={gt.get('external_id')}")
    print(f"iters_run: {len(feedback_result.iterations)} (max_feedback_iters={args.max_feedback_iters})")
    print(f"final_iter_idx: {feedback_result.final_iter_idx}")
    print(f"rollback_reason: {feedback_result.rollback_reason or '(none)'}")
    for rec in feedback_result.iterations:
        _print_iteration_verdict(rec.iter_idx, rec.react_result, rec.verification, gt)
    print(f"\nwall (driver): {elapsed:.1f}s")
    print(f"result JSON: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
