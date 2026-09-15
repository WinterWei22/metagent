#!/usr/bin/env python3
"""Human1-only live rerun with metabolite crosswalk enabled.

This reuses the W22 D8 paired analysis code but writes to an independent
output directory and filters strictly to Human1 tasks.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import common.llm_client as llm_client
import scripts.metagent.w22_d8_easyv3_stratified as w22
from concord.agent.react_runner import ConcordReactRunner
from evaluation.concord.path_x import _per_task_signals
from verifier.agent import verify_sub6
from verifier.helpers.human1_metabolite_crosswalk import apply_human1_crosswalk_to_task


OUT_DIR = ROOT / "data/metagent/human1_crosswalk_full117"
FULL_DIR = OUT_DIR / "path_x_full"
STATUS_DIR = OUT_DIR / "status"
RUN_JSONL = OUT_DIR / "path_x_results.jsonl"
SUMMARY_JSON = OUT_DIR / "path_x_summary.json"
PER_CLAIM_OUT = OUT_DIR / "paired_per_claim.csv"
PER_TASK_OUT = OUT_DIR / "paired_per_task.csv"
METRICS_OUT = OUT_DIR / "paired_metrics_by_stratum.json"
VALIDATION_CANDIDATES_OUT = OUT_DIR / "manual_validation_candidates.csv"
SUMMARY_OUT = OUT_DIR / "paired_summary_by_stratum.md"
LLM_LOG = ROOT / "logs/concord/human1_crosswalk_full117.jsonl"
MINIMAX_KEY_FILE = ROOT.parent / "metagent_day1_v5/api_key_minimax.txt"
MODEL = "MiniMax-M2.7-highspeed"
PROVIDER = "minimax"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["full", "run-one", "aggregate", "analyze"])
    parser.add_argument("--task-id")
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--cost-cap-usd", type=float, default=15.0)
    args = parser.parse_args()

    configure_w22_outputs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    LLM_LOG.parent.mkdir(parents=True, exist_ok=True)

    if args.command == "run-one":
        if not args.task_id:
            raise SystemExit("--task-id is required")
        return run_one(args.task_id)
    if args.command == "full":
        task_ids = [row["task_id"] for row in read_human1_tasks()]
        code = run_scheduler(task_ids, args.k, args.timeout_seconds, args.cost_cap_usd)
        w22.aggregate_run_outputs()
        w22.analyze()
        return code
    if args.command == "aggregate":
        w22.aggregate_run_outputs()
        return 0
    if args.command == "analyze":
        w22.analyze()
        return 0
    raise AssertionError(args.command)


def configure_w22_outputs() -> None:
    w22.OUT_DIR = OUT_DIR
    w22.FULL_DIR = FULL_DIR
    w22.STATUS_DIR = STATUS_DIR
    w22.RUN_JSONL = RUN_JSONL
    w22.SUMMARY_JSON = SUMMARY_JSON
    w22.LLM_LOG = LLM_LOG
    w22.PER_CLAIM_OUT = PER_CLAIM_OUT
    w22.PER_TASK_OUT = PER_TASK_OUT
    w22.METRICS_OUT = METRICS_OUT
    w22.VALIDATION_CANDIDATES_OUT = VALIDATION_CANDIDATES_OUT
    w22.SUMMARY_OUT = SUMMARY_OUT
    w22.MODEL = MODEL
    w22.PROVIDER = PROVIDER
    w22.to_sub6_shape = to_sub6_shape
    w22.stratum_of = lambda task: "human1_crosswalk"


def read_human1_tasks() -> list[dict[str, Any]]:
    rows = []
    for task in w22.read_tasks():
        gt = task.get("ground_truth", {}).get("perturbed_pathway", {})
        if gt.get("ontology") == "Human1":
            rows.append(task)
    return rows


def task_map() -> dict[str, dict[str, Any]]:
    return {row["task_id"]: row for row in read_human1_tasks()}


def to_sub6_shape(task: dict[str, Any]) -> dict[str, Any]:
    converted = w22.__dict__["to_sub6_shape_original"](task) if "to_sub6_shape_original" in w22.__dict__ else _base_to_sub6_shape(task)
    return apply_human1_crosswalk_to_task(converted, enabled=True)


def _base_to_sub6_shape(task: dict[str, Any]) -> dict[str, Any]:
    gt = task.get("ground_truth", {}).get("perturbed_pathway", {})
    ontology = str(gt.get("ontology") or "")
    pathway_id = str(gt.get("id") or "")
    pathway_name = str(gt.get("name") or pathway_id)
    metabolites = list(task.get("input", {}).get("differential_metabolites") or [])
    return {
        "task_id": task["task_id"],
        "task_type": "compound_only_enrichment",
        "domain": "mammalian",
        "difficulty": task.get("difficulty"),
        "differential_metabolites": metabolites,
        "ground_truth_pathway": {
            "pathway_id": pathway_id,
            "pathway_name": pathway_name,
            "external_id": pathway_id,
            "pathway_source": ontology,
            "ontology": ontology,
        },
        "ground_truth_signal_compounds": [w22.metabolite_key(met) for met in metabolites],
        "ground_truth_noise_compounds": [],
        "ramp_enrichment_result": {"top_pathways": []},
        "provenance": task.get("provenance", {}),
    }


def run_scheduler(
    task_ids: list[str],
    k: int,
    timeout_seconds: int,
    cost_cap_usd: float,
) -> int:
    pending = [tid for tid in task_ids if not w22.status_path(tid).exists()]
    running: dict[str, tuple[subprocess.Popen[bytes], float]] = {}
    print(f"pending={len(pending)} already_done={len(task_ids) - len(pending)} k={k}")
    while pending or running:
        while pending and len(running) < k:
            cost = w22.llm_cost()["actual_cost_usd"]
            if cost >= cost_cap_usd:
                print(f"STOP cost cap reached before launch: ${cost:.6f} >= ${cost_cap_usd:.2f}")
                return 2
            tid = pending.pop(0)
            env = dict(os.environ)
            if not env.get("MINIMAX_API_KEY") and MINIMAX_KEY_FILE.exists():
                env["MINIMAX_API_KEY"] = MINIMAX_KEY_FILE.read_text(encoding="utf-8").strip()
            env["METAGENT_LLM_LOG_PATH"] = str(LLM_LOG)
            env["METAGENT_LLM_PROVIDER"] = PROVIDER
            env["METAGENT_MINIMAX_MODEL"] = MODEL
            env["METAGENT_ENABLE_HUMAN1_CROSSWALK"] = "1"
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "run-one",
                "--task-id",
                tid,
            ]
            proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env)
            running[tid] = (proc, time.time())
            print(f"launched {tid}")

        time.sleep(2)
        for tid, (proc, started) in list(running.items()):
            rc = proc.poll()
            if rc is not None:
                running.pop(tid)
                print(f"finished {tid} rc={rc}")
                continue
            if time.time() - started > timeout_seconds:
                proc.kill()
                proc.wait(timeout=10)
                w22.write_status(tid, {
                    "task_id": tid,
                    "stratum": "human1_crosswalk",
                    "ok": False,
                    "error": f"task_timeout_after_{timeout_seconds}s",
                    "wall_seconds": round(time.time() - started, 3),
                })
                running.pop(tid)
                print(f"timeout {tid}")

        cost = w22.llm_cost()["actual_cost_usd"]
        if cost >= cost_cap_usd:
            print(f"STOP cost cap reached: ${cost:.6f} >= ${cost_cap_usd:.2f}")
            for tid, (proc, _) in running.items():
                proc.terminate()
                w22.write_status(tid, {
                    "task_id": tid,
                    "stratum": "human1_crosswalk",
                    "ok": False,
                    "error": "terminated_cost_cap",
                })
            return 2
    return 0


def run_one(task_id: str) -> int:
    configure_w22_outputs()
    if not os.environ.get("MINIMAX_API_KEY") and MINIMAX_KEY_FILE.exists():
        os.environ["MINIMAX_API_KEY"] = MINIMAX_KEY_FILE.read_text(encoding="utf-8").strip()
    os.environ["METAGENT_LLM_PROVIDER"] = PROVIDER
    os.environ["METAGENT_MINIMAX_MODEL"] = MODEL
    os.environ["METAGENT_ENABLE_HUMAN1_CROSSWALK"] = "1"
    llm_client.set_log_path(LLM_LOG)
    tasks = task_map()
    raw_task = tasks[task_id]
    task = to_sub6_shape(raw_task)
    started = time.time()
    runner = ConcordReactRunner(
        llm_model=MODEL,
        llm_provider=PROVIDER,
        verifier_fn=verify_sub6,
        task_timeout_seconds=1200.0,
    )
    try:
        fb = runner.run_task_with_feedback(task, trace_id=f"human1.crosswalk.{task_id}")
        signals = _per_task_signals(task, fb)
        signals["stratum"] = "human1_crosswalk"
        signals["framework_signal_crash"] = None
        signals["human1_crosswalk"] = task.get("human1_crosswalk")
        (FULL_DIR / f"{task_id}.json").write_text(
            json.dumps(dataclasses.asdict(fb), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        w22.write_status(task_id, {
            "task_id": task_id,
            "stratum": "human1_crosswalk",
            "ok": True,
            "wall_seconds": round(time.time() - started, 3),
            "signals": signals,
        })
        return 0
    except Exception as exc:
        w22.write_status(task_id, {
            "task_id": task_id,
            "stratum": "human1_crosswalk",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "wall_seconds": round(time.time() - started, 3),
        })
        return 1


if not hasattr(w22, "to_sub6_shape_original"):
    w22.to_sub6_shape_original = w22.to_sub6_shape


if __name__ == "__main__":
    raise SystemExit(main())
