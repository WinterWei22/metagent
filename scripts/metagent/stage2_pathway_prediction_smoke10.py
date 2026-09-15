#!/usr/bin/env python3
"""Run fixed Stage2 pathway_prediction contract smoke tasks.

This script is self-contained: parent and child `run-one` commands both use the
same output/log paths. It also installs a smoke-only per-tool timeout wrapper so
local tool hangs are recorded as envelopes instead of blocking the whole run.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import scripts.metagent.w22_d8_easyv3_stratified as w22
from concord.agent.react_runner import ConcordReactRunner
from evaluation.concord.path_x import _per_task_signals
from verifier.agent import verify_sub6


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data/metagent/stage2_pathway_prediction_contract_smoke10"
BASE_OUT_DIR = OUT_DIR
FULL_DIR = OUT_DIR / "path_x_full"
STATUS_DIR = OUT_DIR / "status"
RUN_JSONL = OUT_DIR / "path_x_results.jsonl"
SUMMARY_JSON = OUT_DIR / "path_x_summary.json"
LLM_LOG = ROOT / "logs/concord/stage2_pathway_prediction_contract_smoke10.jsonl"
MINIMAX_KEY_FILE = ROOT.parent / "metagent_day1_v5/api_key_minimax.txt"
MODEL = "MiniMax-M2.7-highspeed"
PROVIDER = "minimax"
TOOL_TIMEOUT_SECONDS = int(os.environ.get("METAGENT_SMOKE_TOOL_TIMEOUT_SECONDS", "120"))
TASK_IDS = [
    "sub6_easy_compound_only_enrich_mammalian_RAMP_P_000052855_seed0",
    "sub6_easy_compound_only_enrich_mammalian_RAMP_P_000000421_seed1",
    "sub6_easy_compound_only_enrich_mammalian_RAMP_P_000000421_seed2",
    "sub6_easy_compound_only_enrich_mammalian_RAMP_P_000000421_seed3",
    "sub6_easy_compound_only_enrich_mammalian_RAMP_P_000000421_seed4",
    "sub6_easy_compound_only_enrich_mammalian_RAMP_P_000000421_seed5",
    "hmdb_ramp_easy_kegg_RAMP_P_000000158_rep0",
    "hmdb_ramp_easy_kegg_RAMP_P_000000158_rep1",
    "hmdb_ramp_easy_kegg_RAMP_P_000000303_rep0",
    "hmdb_ramp_easy_kegg_RAMP_P_000000303_rep1",
    "hmdb_ramp_easy_kegg_RAMP_P_000025679_rep0",
    "hmdb_ramp_easy_kegg_RAMP_P_000025679_rep1",
]
PHASE1_TASK_ID = "sub6_easy_compound_only_enrich_mammalian_RAMP_P_000000421_seed1"


def configure(out_dir: Path = OUT_DIR) -> None:
    global OUT_DIR, FULL_DIR, STATUS_DIR, RUN_JSONL, SUMMARY_JSON, LLM_LOG
    OUT_DIR = out_dir
    FULL_DIR = OUT_DIR / "path_x_full"
    STATUS_DIR = OUT_DIR / "status"
    RUN_JSONL = OUT_DIR / "path_x_results.jsonl"
    SUMMARY_JSON = OUT_DIR / "path_x_summary.json"
    suffix = OUT_DIR.name
    LLM_LOG = ROOT / "logs/concord" / f"{suffix}.jsonl"
    w22.OUT_DIR = OUT_DIR
    w22.FULL_DIR = FULL_DIR
    w22.STATUS_DIR = STATUS_DIR
    w22.RUN_JSONL = RUN_JSONL
    w22.SUMMARY_JSON = SUMMARY_JSON
    w22.LLM_LOG = LLM_LOG
    w22.SMOKE_IDS = OUT_DIR / "task_ids.txt"
    w22.PER_CLAIM_OUT = OUT_DIR / "paired_per_claim.csv"
    w22.PER_TASK_OUT = OUT_DIR / "paired_per_task.csv"
    w22.METRICS_OUT = OUT_DIR / "paired_metrics_by_stratum.json"
    w22.VALIDATION_CANDIDATES_OUT = OUT_DIR / "manual_validation_candidates.csv"
    w22.SUMMARY_OUT = OUT_DIR / "paired_summary_by_stratum.md"
    w22.MODEL = MODEL
    w22.PROVIDER = PROVIDER


def install_smoke_tool_timeout() -> None:
    from concord.agent import react_runner as rr
    from concord.agent import tool_dispatcher as td

    original_dispatch = rr.dispatch

    def _timeout_handler(signum: int, frame: Any) -> None:
        raise TimeoutError(f"tool timed out after {TOOL_TIMEOUT_SECONDS}s")

    def timeout_dispatch(tool_call: dict[str, Any]) -> td.DispatchResult:
        name = ""
        call_id = ""
        try:
            name = str(tool_call.get("function", {}).get("name") or "")
            call_id = str(tool_call.get("id") or "")
            old_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(TOOL_TIMEOUT_SECONDS)
            try:
                return original_dispatch(tool_call)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        except TimeoutError as exc:
            return td.DispatchResult(
                tool_name=name or "unknown",
                tool_call_id=call_id,
                payload={
                    "error": f"tool_timeout: {exc}",
                    "fallback_suggested": "skip this tool and use another evidence source",
                    "_tool_name": name or "unknown",
                    "_timeout_seconds": TOOL_TIMEOUT_SECONDS,
                },
            )

    rr.dispatch = timeout_dispatch


def ensure_dirs() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    LLM_LOG.parent.mkdir(parents=True, exist_ok=True)


def task_map() -> dict[str, dict[str, Any]]:
    return {row["task_id"]: row for row in w22.read_tasks()}


def configure_llm_env() -> None:
    if not os.environ.get("MINIMAX_API_KEY") and MINIMAX_KEY_FILE.exists():
        os.environ["MINIMAX_API_KEY"] = MINIMAX_KEY_FILE.read_text(encoding="utf-8").strip()
    os.environ["METAGENT_LLM_LOG_PATH"] = str(LLM_LOG)
    os.environ["METAGENT_LLM_PROVIDER"] = PROVIDER
    os.environ["METAGENT_MINIMAX_MODEL"] = MODEL


def run_one(task_id: str) -> int:
    import common.llm_client as llm_client

    ensure_dirs()
    configure_llm_env()
    llm_client.set_log_path(LLM_LOG)
    install_smoke_tool_timeout()
    raw_task = task_map()[task_id]
    task = w22.to_sub6_shape(raw_task)
    started = time.time()
    runner = ConcordReactRunner(
        llm_model=MODEL,
        llm_provider=PROVIDER,
        verifier_fn=verify_sub6,
        task_timeout_seconds=1200.0,
    )
    try:
        fb = runner.run_task_with_feedback(task, trace_id=f"stage2.contract.{task_id}")
        signals = _per_task_signals(task, fb)
        signals["stratum"] = w22.stratum_of(raw_task)
        signals["framework_signal_crash"] = None
        (FULL_DIR / f"{task_id}.json").write_text(
            json.dumps(dataclasses.asdict(fb), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        w22.write_status(task_id, {
            "task_id": task_id,
            "stratum": w22.stratum_of(raw_task),
            "ok": True,
            "wall_seconds": round(time.time() - started, 3),
            "signals": signals,
        })
        return 0
    except Exception as exc:
        w22.write_status(task_id, {
            "task_id": task_id,
            "stratum": w22.stratum_of(raw_task),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "wall_seconds": round(time.time() - started, 3),
        })
        return 1


def run_scheduler(task_ids: list[str], k: int, timeout_seconds: int, cost_cap_usd: float) -> int:
    ensure_dirs()
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
            cmd = [sys.executable, str(Path(__file__).resolve()), "run-one", "--task-id", tid]
            if OUT_DIR.parent == BASE_OUT_DIR and OUT_DIR.name in {"old", "new"}:
                cmd.extend(["--arm", OUT_DIR.name])
            else:
                cmd.extend(["--out-dir", str(OUT_DIR)])
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
                    "ok": False,
                    "error": "terminated_cost_cap",
                })
            return 2
    return 0


def phase2_compare() -> dict[str, Any]:
    old_metrics = _load_metrics(BASE_OUT_DIR / "old" / "paired_metrics_by_stratum.json")
    new_metrics = _load_metrics(BASE_OUT_DIR / "new" / "paired_metrics_by_stratum.json")
    rows: list[dict[str, Any]] = []
    passed = True
    for stratum in sorted(set(old_metrics) | set(new_metrics)):
        for arm in ("structured_method_aware",):
            old = old_metrics.get(stratum, {}).get("arms", {}).get(arm, {})
            new = new_metrics.get(stratum, {}).get("arms", {}).get(arm, {})
            if not old or not new:
                passed = False
                rows.append({"stratum": stratum, "arm": arm, "error": "missing arm metrics"})
                continue
            row = _compare_arm(stratum, arm, old, new)
            if any(abs(row[key]) > 5.0 for key in ("supported_delta_pp", "uv_delta_pp", "dropped_delta_pp")):
                passed = False
            rows.append(row)
    out = {"pass": passed, "rows": rows}
    (BASE_OUT_DIR / "phase2_claim_regression.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def _load_metrics(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    obj = json.loads(path.read_text(encoding="utf-8"))
    return obj.get("strata") or obj.get("by_stratum") or {}


def _compare_arm(stratum: str, arm: str, old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    def pct(item: dict[str, Any], key: str) -> float:
        return float(item.get(key) or 0.0) * 100.0

    def dropped_pct(item: dict[str, Any]) -> float:
        source = float(item.get("source_claims") or 0.0)
        return (float(item.get("dropped") or 0.0) / source * 100.0) if source else 0.0

    return {
        "stratum": stratum,
        "arm": arm,
        "old_tasks": old.get("tasks", 0),
        "new_tasks": new.get("tasks", 0),
        "old_supported_honest_pct": pct(old, "supported_rate_honest"),
        "new_supported_honest_pct": pct(new, "supported_rate_honest"),
        "supported_delta_pp": round(pct(new, "supported_rate_honest") - pct(old, "supported_rate_honest"), 3),
        "old_unlanded_honest_pct": pct(old, "unlanded_rate_honest"),
        "new_unlanded_honest_pct": pct(new, "unlanded_rate_honest"),
        "uv_delta_pp": round(pct(new, "unlanded_rate_honest") - pct(old, "unlanded_rate_honest"), 3),
        "old_dropped_pct": dropped_pct(old),
        "new_dropped_pct": dropped_pct(new),
        "dropped_delta_pp": round(dropped_pct(new) - dropped_pct(old), 3),
    }


def finalise_outputs() -> None:
    w22.aggregate_run_outputs()
    w22.analyze()
    summary = {
        "task_ids": TASK_IDS,
        "llm_cost": w22.llm_cost(),
    }
    (OUT_DIR / "smoke10_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def validate_pathway_prediction(task_id: str) -> bool:
    path = FULL_DIR / f"{task_id}.json"
    if not path.exists():
        return False
    obj = json.loads(path.read_text(encoding="utf-8"))
    final = obj.get("final_react_result") or {}
    pred = final.get("pathway_prediction")
    return isinstance(pred, dict) and isinstance(pred.get("primary"), dict)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="phase1", choices=["phase1", "phase2", "full", "run-one", "analyze"])
    parser.add_argument("--task-id")
    parser.add_argument("--arm", choices=["old", "new"], default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--cost-cap-usd", type=float, default=8.0)
    args = parser.parse_args()
    if args.out_dir is not None:
        configure(args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir)
    elif args.arm:
        configure(BASE_OUT_DIR / args.arm)
    else:
        configure(BASE_OUT_DIR)
    ensure_dirs()
    w22.SMOKE_IDS.write_text("\n".join(TASK_IDS) + "\n", encoding="utf-8")
    if args.command == "run-one":
        if not args.task_id:
            raise SystemExit("--task-id is required")
        return run_one(args.task_id)
    if args.command == "analyze":
        finalise_outputs()
        return 0
    if args.command == "phase1":
        code = run_scheduler([args.task_id or PHASE1_TASK_ID], k=1, timeout_seconds=args.timeout_seconds, cost_cap_usd=args.cost_cap_usd)
        finalise_outputs()
        if code == 0 and validate_pathway_prediction(args.task_id or PHASE1_TASK_ID):
            return 0
        return code or 1
    if args.command == "full":
        code = run_scheduler(TASK_IDS, k=args.k, timeout_seconds=args.timeout_seconds, cost_cap_usd=args.cost_cap_usd)
        finalise_outputs()
        return code
    if args.command == "phase2":
        old_dir = BASE_OUT_DIR / "old"
        new_dir = BASE_OUT_DIR / "new"
        configure(old_dir)
        ensure_dirs()
        os.environ["METAGENT_DISABLE_PATHWAY_PREDICTION_CONTRACT"] = "1"
        old_code = run_scheduler(TASK_IDS, k=args.k, timeout_seconds=args.timeout_seconds, cost_cap_usd=args.cost_cap_usd)
        finalise_outputs()
        os.environ.pop("METAGENT_DISABLE_PATHWAY_PREDICTION_CONTRACT", None)
        configure(new_dir)
        ensure_dirs()
        new_code = run_scheduler(TASK_IDS, k=args.k, timeout_seconds=args.timeout_seconds, cost_cap_usd=args.cost_cap_usd)
        finalise_outputs()
        configure(BASE_OUT_DIR)
        compare = phase2_compare()
        return 0 if old_code == 0 and new_code == 0 and compare.get("pass") else 1
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
