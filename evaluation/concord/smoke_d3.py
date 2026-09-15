"""W8 D3 — end-to-end smoke driver for ConcordReactRunner on sub6b-v3.

Usage:

    PYTHONPATH=. python3 evaluation/concord/smoke_d3.py \
        --task-id compound_only_enrich_mammalian_RAMP_P_000000421_seed1 \
        --out data/concord/w8_smoke/d3_steroid.json

Two tasks are the canonical D3 smoke pair (per W8 spec § D3):

  Smoke 1 — `compound_only_enrich_mammalian_RAMP_P_000000421_seed1`
            (steroid; ground-truth `Androgen and Estrogen Metabolism`)

  Smoke 2 — `compound_only_enrich_mammalian_lm_pathway_WP167_seed3`
            (lipid smoking gun; ground-truth `Eicosanoid synthesis`)

The driver prints a short verdict line + writes the full
ConcordReactResult to `--out` as JSON for review.
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

from concord.agent.react_runner import ConcordReactRunner


_DEFAULT_BENCHMARK = Path("data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")


def _load_task(benchmark: Path, task_id: str) -> dict[str, Any]:
    if not benchmark.exists():
        raise FileNotFoundError(
            f"sub6b-v3 benchmark not found at {benchmark}"
        )
    with benchmark.open() as f:
        for line in f:
            row = json.loads(line)
            if row.get("task_id") == task_id:
                return row
    raise KeyError(f"task_id {task_id!r} not found in {benchmark}")


def _save_result(result, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dataclasses.asdict(result)
    with out_path.open("w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def _short_verdict(result, task: dict[str, Any]) -> str:
    """One-line summary for the terminal."""
    gt = task.get("ground_truth_pathway") or {}
    gt_name = gt.get("pathway_name") or "<n/a>"
    gt_id = gt.get("pathway_id") or "<n/a>"
    # Smoking gun check — does the narrative mention ground truth or its
    # WP NS ID literally?
    narrative = result.final_narrative_text or ""
    mentions = []
    if gt_name and gt_name.lower() in narrative.lower():
        mentions.append(f"literal '{gt_name}'")
    if gt_id and gt_id.split(":")[-1] and gt_id.split(":")[-1] in narrative:
        mentions.append(f"namespace id '{gt_id}'")
    bridge_hit = bool(mentions)
    lines = [
        f"task_id          = {result.task_id}",
        f"ground_truth     = {gt_name} ({gt_id})",
        f"task_outcome     = {result.task_outcome}",
        f"n_turns          = {result.iterations[0].n_turns if result.iterations else 0} / {8}",
        f"n_tool_calls     = {result.iterations[0].n_tool_calls if result.iterations else 0}",
        f"distinct tools   = {result.n_distinct_tools_called}: {result.tools_called}",
        f"inner_retry_used = {result.iterations[0].inner_retry_used if result.iterations else False}",
        f"force_finalised  = {result.iterations[0].force_finalised if result.iterations else False}",
        f"wall_seconds     = {result.elapsed_seconds:.1f}",
        f"n_claims         = {len(result.final_claims)}",
        f"naming bridge    = " + (
            "★ HIT — " + ", ".join(mentions) if bridge_hit
            else "no literal mention of ground truth name / id"
        ),
        f"error            = {result.error or '(none)'}",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task-id", required=True,
        help="sub6b-v3 task_id; e.g. compound_only_enrich_mammalian_lm_pathway_WP167_seed3",
    )
    parser.add_argument(
        "--benchmark", type=Path, default=_DEFAULT_BENCHMARK,
        help=f"sub6b-v3 jsonl (default: {_DEFAULT_BENCHMARK})",
    )
    parser.add_argument(
        "--out", type=Path, required=True,
        help="where to dump the full ConcordReactResult JSON",
    )
    parser.add_argument(
        "--max-react-turns", type=int, default=8,
        help="W8 ceiling = 8",
    )
    parser.add_argument(
        "--model", default="gpt-5.5",
        help="LLM model name passed to common.llm_client",
    )
    parser.add_argument(
        "--provider", default="openai",
        help="LLM provider — 'minimax' or 'openai'",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    task = _load_task(args.benchmark, args.task_id)
    runner = ConcordReactRunner(
        llm_model=args.model,
        llm_provider=args.provider,
        max_react_turns=args.max_react_turns,
    )
    started = time.time()
    result = runner.run_task(task)
    elapsed = time.time() - started
    _save_result(result, args.out)

    print("\n=== D3 smoke verdict ===")
    print(_short_verdict(result, task))
    print(f"\nwall (driver)      = {elapsed:.1f}s")
    print(f"result JSON saved  = {args.out}")
    return 0 if result.task_outcome == "normal" else 1


if __name__ == "__main__":
    sys.exit(main())
