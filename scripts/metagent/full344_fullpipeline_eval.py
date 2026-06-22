#!/usr/bin/env python3
"""Full 344-task Stage2 baseline pipeline evaluation.

This script keeps the live run incremental and writes enough metadata to
reconstruct the exact baseline configuration.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import common.llm_client as llm_client
import scripts.metagent.w22_d8_easyv3_stratified as w22
from concord.agent.react_runner import ConcordReactRunner
from concord.agent.verifier_adapter import (
    concord_result_to_b1_narrative,
    concord_result_to_b1_structured_payload,
    sub6b_task_to_subsix_source_report,
)
from evaluation.concord.path_x import _per_task_signals, aggregate_path_x
from verifier.agent import _extract_classify, _verify_per_claim_sub6, verify_sub6
from verifier.helpers.human1_metabolite_crosswalk import (
    DEFAULT_REFERENCE_PATH,
    ENABLE_ENV,
    apply_human1_crosswalk_to_task,
)
from verifier.schemas import ClaimVerdict, VerifiedClaim


BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
OUT_DIR = ROOT / "data/metagent/full344_fullpipeline_eval"
FULL_DIR = OUT_DIR / "path_x_full"
STATUS_DIR = OUT_DIR / "status"
RUN_JSONL = OUT_DIR / "path_x_results.jsonl"
SUMMARY_JSON = OUT_DIR / "path_x_summary.json"
PER_CLAIM_OUT = OUT_DIR / "paired_per_claim.csv"
PER_TASK_OUT = OUT_DIR / "paired_per_task.csv"
CLAIM_METRICS_OUT = OUT_DIR / "claim_metrics_by_stratum.json"
VALIDATION_CANDIDATES_OUT = OUT_DIR / "manual_validation_candidates.csv"
CLAIM_SUMMARY_OUT = OUT_DIR / "claim_summary_by_stratum.md"
VERSION_HEADER = OUT_DIR / "version_header.json"
PHASE1_IDS = OUT_DIR / "phase1_task_ids.txt"
LLM_LOG = ROOT / "logs/concord/full344_fullpipeline_eval.jsonl"
MINIMAX_KEY_FILE = ROOT.parent / "metagent_day1_v5/api_key_minimax.txt"
OPENAI_KEY_FILE = ROOT.parent / "metagent_day1_v5/api_key_gpt.txt"
DEFAULT_PROVIDER = os.environ.get("METAGENT_FULL344_PROVIDER") or "minimax"
DEFAULT_MODEL = (
    os.environ.get("METAGENT_FULL344_MODEL")
    or ("gpt-5.5" if DEFAULT_PROVIDER == "openai" else "MiniMax-M2.7-highspeed")
)
TOOL_TIMEOUT_SECONDS = int(os.environ.get("METAGENT_FULL344_TOOL_TIMEOUT_SECONDS", "180"))
TASK_TIMEOUT_SECONDS = 1200
PROMPT_COST_PER_M = 0.30
COMPLETION_COST_PER_M = 1.20
UV_VERDICTS = {ClaimVerdict.UNVERIFIABLE_V0.value, ClaimVerdict.ERROR.value}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["phase0", "smoke", "full", "run-one", "aggregate", "analyze"])
    parser.add_argument("--task-id")
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=int, default=TASK_TIMEOUT_SECONDS)
    parser.add_argument("--tool-timeout-seconds", type=int, default=TOOL_TIMEOUT_SECONDS)
    parser.add_argument("--cost-cap-usd", type=float, default=35.0)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    configure_paths(args.out_dir)
    ensure_dirs()

    if args.command == "phase0":
        write_version_header(args.tool_timeout_seconds, args.timeout_seconds, args.provider, args.model)
        return 0
    if args.command == "run-one":
        if not args.task_id:
            raise SystemExit("--task-id is required for run-one")
        return run_one(args.task_id, args.tool_timeout_seconds, args.timeout_seconds, args.provider, args.model)
    if args.command == "smoke":
        task_ids = select_phase1_ids()
        PHASE1_IDS.write_text("\n".join(task_ids) + "\n", encoding="utf-8")
        code = run_scheduler(task_ids, args.k, args.timeout_seconds, args.cost_cap_usd, args.tool_timeout_seconds, args.provider, args.model)
        aggregate_run_outputs()
        analyze()
        return code
    if args.command == "full":
        task_ids = [row["task_id"] for row in read_tasks()]
        code = run_scheduler(task_ids, args.k, args.timeout_seconds, args.cost_cap_usd, args.tool_timeout_seconds, args.provider, args.model)
        aggregate_run_outputs()
        analyze()
        return code
    if args.command == "aggregate":
        aggregate_run_outputs()
        return 0
    if args.command == "analyze":
        analyze()
        return 0
    raise AssertionError(args.command)


def configure_paths(out_dir: Path) -> None:
    global OUT_DIR, FULL_DIR, STATUS_DIR, RUN_JSONL, SUMMARY_JSON, PER_CLAIM_OUT, PER_TASK_OUT
    global CLAIM_METRICS_OUT, VALIDATION_CANDIDATES_OUT, CLAIM_SUMMARY_OUT, VERSION_HEADER, PHASE1_IDS, LLM_LOG
    OUT_DIR = out_dir
    FULL_DIR = OUT_DIR / "path_x_full"
    STATUS_DIR = OUT_DIR / "status"
    RUN_JSONL = OUT_DIR / "path_x_results.jsonl"
    SUMMARY_JSON = OUT_DIR / "path_x_summary.json"
    PER_CLAIM_OUT = OUT_DIR / "paired_per_claim.csv"
    PER_TASK_OUT = OUT_DIR / "paired_per_task.csv"
    CLAIM_METRICS_OUT = OUT_DIR / "claim_metrics_by_stratum.json"
    VALIDATION_CANDIDATES_OUT = OUT_DIR / "manual_validation_candidates.csv"
    CLAIM_SUMMARY_OUT = OUT_DIR / "claim_summary_by_stratum.md"
    VERSION_HEADER = OUT_DIR / "version_header.json"
    PHASE1_IDS = OUT_DIR / "phase1_task_ids.txt"
    LLM_LOG = ROOT / "logs/concord" / f"{OUT_DIR.name}.jsonl"


def ensure_dirs() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    LLM_LOG.parent.mkdir(parents=True, exist_ok=True)


def read_tasks() -> list[dict[str, Any]]:
    with BENCHMARK.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def task_map() -> dict[str, dict[str, Any]]:
    return {row["task_id"]: row for row in read_tasks()}


def stratum_of(task: dict[str, Any]) -> str:
    ontology = str(task.get("ground_truth", {}).get("perturbed_pathway", {}).get("ontology") or "")
    if ontology == "Human1":
        return "human1"
    if ontology == "Recon2.2":
        return "recon22"
    if ontology.startswith("RaMP:"):
        return "hmdb_ramp"
    return "unknown"


def select_phase1_ids() -> list[str]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for task in read_tasks():
        buckets[stratum_of(task)].append(task["task_id"])
    selected: list[str] = []
    for stratum in ("human1", "recon22", "hmdb_ramp"):
        selected.extend(buckets[stratum][:2])
    return selected


def to_sub6_shape(
    task: dict[str, Any],
    *,
    enable_human1_crosswalk: bool = True,
    crosswalk_reference: str | Path = DEFAULT_REFERENCE_PATH,
) -> dict[str, Any]:
    gt = task.get("ground_truth", {}).get("perturbed_pathway", {})
    ontology = str(gt.get("ontology") or "")
    pathway_id = str(gt.get("id") or "")
    pathway_name = str(gt.get("name") or pathway_id)
    metabolites = list(task.get("input", {}).get("differential_metabolites") or [])
    converted = {
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
        "ground_truth_signal_compounds": [metabolite_key(met) for met in metabolites],
        "ground_truth_noise_compounds": [],
        "ramp_enrichment_result": {"top_pathways": []},
        "provenance": task.get("provenance", {}),
    }
    return apply_human1_crosswalk_to_task(
        converted,
        reference_path=crosswalk_reference,
        enabled=enable_human1_crosswalk,
    )


def metabolite_key(metabolite: dict[str, Any]) -> str:
    for key in ("kegg_id", "id", "hmdb_id", "name"):
        value = metabolite.get(key)
        if value:
            return str(value)
    return json.dumps(metabolite, sort_keys=True)


def llm_env_for_child(
    *,
    provider: str,
    model: str,
    log_path: Path,
    minimax_key_file: Path = MINIMAX_KEY_FILE,
    openai_key_file: Path = OPENAI_KEY_FILE,
) -> dict[str, str]:
    env = dict(os.environ)
    provider = provider.strip().lower()
    env["METAGENT_LLM_PROVIDER"] = provider
    env["METAGENT_LLM_LOG_PATH"] = str(log_path)
    if provider == "openai":
        if not env.get("METAGENT_OPENAI_API_KEY") and openai_key_file.exists():
            env["METAGENT_OPENAI_API_KEY"] = openai_key_file.read_text(encoding="utf-8").strip()
        env["METAGENT_OPENAI_MODEL"] = model
        env.pop("METAGENT_MINIMAX_MODEL", None)
    else:
        if not env.get("MINIMAX_API_KEY") and minimax_key_file.exists():
            env["MINIMAX_API_KEY"] = minimax_key_file.read_text(encoding="utf-8").strip()
        env["METAGENT_MINIMAX_MODEL"] = model
    env["METAGENT_VERIFY_STRUCTURED_CLAIMS"] = "1"
    env["METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT"] = "1"
    env[ENABLE_ENV] = "1"
    return env


def configure_llm_env(provider: str, model: str) -> None:
    os.environ.update(
        llm_env_for_child(provider=provider, model=model, log_path=LLM_LOG)
    )
    os.environ["METAGENT_VERIFY_STRUCTURED_CLAIMS"] = "1"
    os.environ["METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT"] = "1"
    os.environ[ENABLE_ENV] = "1"
    llm_client.set_log_path(LLM_LOG)


def install_tool_timeout(timeout_seconds: int) -> None:
    from concord.agent import react_runner as rr
    from concord.agent import tool_dispatcher as td

    original_dispatch = rr.dispatch

    def _timeout_handler(signum: int, frame: Any) -> None:
        raise TimeoutError(f"tool timed out after {timeout_seconds}s")

    def timeout_dispatch(tool_call: dict[str, Any]) -> td.DispatchResult:
        name = str(tool_call.get("function", {}).get("name") or "")
        call_id = str(tool_call.get("id") or "")
        old_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout_seconds)
        try:
            return original_dispatch(tool_call)
        except TimeoutError as exc:
            return td.DispatchResult(
                tool_name=name or "unknown",
                tool_call_id=call_id,
                payload={
                    "error": f"tool_timeout: {exc}",
                    "fallback_suggested": "skip this tool and use another evidence source",
                    "_tool_name": name or "unknown",
                    "_timeout_seconds": timeout_seconds,
                },
            )
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    rr.dispatch = timeout_dispatch


def run_scheduler(
    task_ids: list[str],
    k: int,
    timeout_seconds: int,
    cost_cap_usd: float,
    tool_timeout_seconds: int,
    provider: str,
    model: str,
) -> int:
    pending = [tid for tid in task_ids if not status_path(tid).exists()]
    running: dict[str, tuple[subprocess.Popen[bytes], float]] = {}
    print(f"pending={len(pending)} already_done={len(task_ids) - len(pending)} k={k}")
    while pending or running:
        while pending and len(running) < k:
            cost = llm_cost()["actual_cost_usd"]
            if cost >= cost_cap_usd:
                print(f"STOP cost cap reached before launch: ${cost:.6f} >= ${cost_cap_usd:.2f}")
                return 2
            tid = pending.pop(0)
            env = llm_env_for_child(provider=provider, model=model, log_path=LLM_LOG)
            env["METAGENT_FULL344_TOOL_TIMEOUT_SECONDS"] = str(tool_timeout_seconds)
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "run-one",
                "--task-id",
                tid,
                "--out-dir",
                str(OUT_DIR),
                "--tool-timeout-seconds",
                str(tool_timeout_seconds),
                "--timeout-seconds",
                str(timeout_seconds),
                "--provider",
                provider,
                "--model",
                model,
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
                raw_task = task_map().get(tid, {})
                write_status(tid, {
                    "task_id": tid,
                    "stratum": stratum_of(raw_task),
                    "ok": False,
                    "error": f"task_timeout_after_{timeout_seconds}s",
                    "invalid_reason": "timeout",
                    "wall_seconds": round(time.time() - started, 3),
                })
                running.pop(tid)
                print(f"timeout {tid}")

        cost = llm_cost()["actual_cost_usd"]
        if cost >= cost_cap_usd:
            print(f"STOP cost cap reached: ${cost:.6f} >= ${cost_cap_usd:.2f}")
            for tid, (proc, _) in running.items():
                proc.terminate()
                raw_task = task_map().get(tid, {})
                write_status(tid, {
                    "task_id": tid,
                    "stratum": stratum_of(raw_task),
                    "ok": False,
                    "error": "terminated_cost_cap",
                    "invalid_reason": "cost_cap",
                })
            return 2
    return 0


def run_one(task_id: str, tool_timeout_seconds: int, timeout_seconds: int, provider: str, model: str) -> int:
    configure_llm_env(provider, model)
    install_tool_timeout(tool_timeout_seconds)
    raw_task = task_map()[task_id]
    task = to_sub6_shape(raw_task, enable_human1_crosswalk=True)
    started = time.time()
    runner = ConcordReactRunner(
        llm_model=model,
        llm_provider=provider,
        verifier_fn=verify_sub6,
        task_timeout_seconds=float(timeout_seconds),
    )
    try:
        fb = runner.run_task_with_feedback(task, trace_id=f"full344.{task_id}")
        signals = _per_task_signals(task, fb)
        signals["stratum"] = stratum_of(raw_task)
        signals["framework_signal_crash"] = None
        signals["human1_crosswalk"] = task.get("human1_crosswalk")
        signals["pathway_prediction_primary_present"] = bool(
            ((fb.final_react_result.pathway_prediction or {}).get("primary"))
        )
        (FULL_DIR / f"{task_id}.json").write_text(
            json.dumps(dataclasses.asdict(fb), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        write_status(task_id, {
            "task_id": task_id,
            "stratum": stratum_of(raw_task),
            "ok": True,
            "wall_seconds": round(time.time() - started, 3),
            "signals": signals,
        })
        return 0
    except Exception as exc:
        invalid = "RateLimitError" if "RateLimitError" in f"{type(exc).__name__}: {exc}" else ""
        write_status(task_id, {
            "task_id": task_id,
            "stratum": stratum_of(raw_task),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "invalid_reason": invalid,
            "wall_seconds": round(time.time() - started, 3),
        })
        return 1


def status_path(task_id: str) -> Path:
    return STATUS_DIR / f"{task_id}.json"


def write_status(task_id: str, row: dict[str, Any]) -> None:
    status_path(task_id).write_text(
        json.dumps(row, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def aggregate_run_outputs() -> None:
    rows: list[dict[str, Any]] = []
    statuses = []
    for path in sorted(STATUS_DIR.glob("*.json")):
        status = json.loads(path.read_text(encoding="utf-8"))
        statuses.append(status)
        if status.get("ok") and status.get("signals"):
            rows.append(status["signals"])
        else:
            rows.append({
                "task_id": status.get("task_id") or path.stem,
                "stratum": status.get("stratum") or "",
                "framework_signal_crash": status.get("error") or "unknown_error",
                "invalid_reason": status.get("invalid_reason") or "",
                "wall_seconds": status.get("wall_seconds"),
            })
    with RUN_JSONL.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    summary = aggregate_path_x(rows)
    summary["by_stratum"] = dict(Counter(row.get("stratum") or "unknown" for row in rows))
    summary["status_ok"] = sum(1 for row in statuses if row.get("ok"))
    summary["status_failed"] = sum(1 for row in statuses if not row.get("ok"))
    summary["llm_cost"] = llm_cost()
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")


def analyze() -> None:
    tasks = task_map()
    task_ids = [
        json.loads(line)["task_id"]
        for line in RUN_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip() and not json.loads(line).get("framework_signal_crash")
    ]
    arm_results: list[w22.ArmResult] = []
    per_claim_rows: list[dict[str, Any]] = []
    for task_id in task_ids:
        raw_task = tasks[task_id]
        task = to_sub6_shape(raw_task, enable_human1_crosswalk=True)
        dump = json.loads((FULL_DIR / f"{task_id}.json").read_text(encoding="utf-8"))
        result = react_result(task_id, dump)
        source_report = sub6b_task_to_subsix_source_report({
            **task,
            **(result.enrichment_carriers or {}),
        })
        stratum = stratum_of(raw_task)
        prose = run_arm(
            task_id,
            stratum,
            "prose",
            concord_result_to_b1_narrative(result, task),
            source_report,
            source_claims=None,
            method_aware=False,
            extractor_mode="rule-based",
        )
        structured = run_arm(
            task_id,
            stratum,
            "structured_method_aware",
            concord_result_to_b1_structured_payload(result, task),
            source_report,
            source_claims=len(result.final_claims or []),
            method_aware=True,
            extractor_mode="llm",
        )
        arm_results.extend([prose, structured])
        per_claim_rows.extend(w22.claim_rows(prose))
        per_claim_rows.extend(w22.claim_rows(structured))

    per_task_rows = w22.per_task_rows_from_results(arm_results)
    metrics = metrics_by_stratum(arm_results, per_task_rows, expected_tasks=read_tasks())
    samples = w22.validation_candidates(per_claim_rows)
    write_csv(PER_CLAIM_OUT, per_claim_rows)
    write_csv(PER_TASK_OUT, per_task_rows)
    write_csv(VALIDATION_CANDIDATES_OUT, samples)
    CLAIM_METRICS_OUT.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    write_claim_summary(metrics, samples)


def react_result(task_id: str, dump: dict[str, Any]):
    final = dump.get("final_react_result") or {}
    from concord.agent.react_runner import ConcordReactResult

    return ConcordReactResult(
        task_id=task_id,
        final_narrative_text=final.get("final_narrative_text") or "",
        final_claims=final.get("final_claims") or [],
        pathway_prediction=final.get("pathway_prediction"),
        enrichment_carriers=final.get("enrichment_carriers") or {},
    )


def run_arm(
    task_id: str,
    stratum: str,
    arm: str,
    payload: str,
    source_report: Any,
    *,
    source_claims: int | None,
    method_aware: bool,
    extractor_mode: str,
) -> w22.ArmResult:
    old_judge = os.environ.get("METAGENT_ENABLE_LLM_JUDGE_SUB6")
    old_method = os.environ.get("METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT")
    old_extractor = os.environ.get("METAGENT_VERIFIER_EXTRACTOR")
    old_trace = os.environ.get("METAGENT_TOOL_OUTPUT_TRACE_PATH")
    os.environ["METAGENT_ENABLE_LLM_JUDGE_SUB6"] = "0"
    os.environ["METAGENT_VERIFIER_EXTRACTOR"] = extractor_mode
    os.environ.pop("METAGENT_TOOL_OUTPUT_TRACE_PATH", None)
    if method_aware:
        os.environ["METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT"] = "1"
    else:
        os.environ.pop("METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT", None)
    try:
        classified, llm_calls, warnings, dropped = w22.extract_classify_no_llm(
            payload,
            trace_id=f"full344.{task_id}.{arm}",
        )
        if warnings:
            print(f"WARN {task_id} {arm}: {warnings}", file=sys.stderr)
        if classified is None:
            classified = []
        claims = _verify_per_claim_sub6(
            classified,
            source_report,
            ramp_db_path=None,
            ramp_conn=None,
            driver_lookup=None,
            is_final_iteration=True,
            iteration=1,
        )
        return w22.ArmResult(
            task_id=task_id,
            stratum=stratum,
            arm=arm,
            source_claims=source_claims if source_claims is not None else len(classified),
            dropped=len(dropped),
            claims=claims,
            suppressed_llm_calls=llm_calls,
        )
    finally:
        w22.restore_env("METAGENT_ENABLE_LLM_JUDGE_SUB6", old_judge)
        w22.restore_env("METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT", old_method)
        w22.restore_env("METAGENT_VERIFIER_EXTRACTOR", old_extractor)
        w22.restore_env("METAGENT_TOOL_OUTPUT_TRACE_PATH", old_trace)


def metrics_by_stratum(
    results: list[w22.ArmResult],
    per_task_rows: list[dict[str, Any]],
    *,
    expected_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_counts = Counter(stratum_of(task) for task in expected_tasks)
    strata: dict[str, Any] = {}
    for stratum in ("human1", "recon22", "hmdb_ramp"):
        strata[stratum] = metrics_for_results(
            [r for r in results if r.stratum == stratum],
            [r for r in per_task_rows if r["stratum"] == stratum],
            expected_tasks=expected_counts[stratum],
        )
    return {
        "input": {
            "benchmark": str(BENCHMARK.relative_to(ROOT)),
            "tasks_completed": len({r.task_id for r in results}),
            "expected_tasks_by_stratum": dict(expected_counts),
            "llm_log": str(LLM_LOG.relative_to(ROOT)),
            **llm_cost(),
            "cost_rate": "$0.30/M prompt + $1.20/M completion",
        },
        "strata": strata,
    }


def metrics_for_results(
    results: list[w22.ArmResult],
    per_task_rows: list[dict[str, Any]],
    *,
    expected_tasks: int,
) -> dict[str, Any]:
    item = w22.metrics_for_results(results, per_task_rows) if results else {
        "arms": {},
        "comparison": {},
        "per_task_delta": {},
    }
    item["expected_tasks"] = expected_tasks
    item["completed_tasks"] = len({r.task_id for r in results})
    return item


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_claim_summary(metrics: dict[str, Any], samples: list[dict[str, Any]]) -> None:
    lines = [
        "# Full344 Claim-Level Scorecard",
        "",
        "Claim metrics are reported separately from pathway_prediction accuracy. Contradicted rates are shown but not used as success claims.",
        "",
        "| stratum | expected tasks | completed tasks | arm | source claims | supported honest | UV honest | unlanded honest | method-aware hit |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for stratum, block in metrics["strata"].items():
        for arm, item in (block.get("arms") or {}).items():
            lines.append(
                f"| {stratum} | {block['expected_tasks']} | {block['completed_tasks']} | {arm} | "
                f"{item.get('source_claims', 0)} | {item.get('supported_rate_honest', 0.0):.2%} | "
                f"{item.get('uv_rate_honest', 0.0):.2%} | {item.get('unlanded_rate_honest', 0.0):.2%} | "
                f"{item.get('method_aware_hit_rate', 0.0):.2%} |"
            )
    lines.extend(["", f"Manual validation candidate rows: {len(samples)}"])
    CLAIM_SUMMARY_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def llm_cost() -> dict[str, Any]:
    prompt_tokens = 0
    completion_tokens = 0
    rows = 0
    if LLM_LOG.exists():
        for line in LLM_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            prompt_tokens += int(row.get("prompt_tokens") or 0)
            completion_tokens += int(row.get("completion_tokens") or 0)
    return {
        "log_path": str(LLM_LOG),
        "rows": rows,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "actual_cost_usd": round(
            prompt_tokens / 1_000_000 * PROMPT_COST_PER_M
            + completion_tokens / 1_000_000 * COMPLETION_COST_PER_M,
            6,
        ),
    }


def write_version_header(
    tool_timeout_seconds: int,
    task_timeout_seconds: int,
    provider: str,
    model: str,
) -> None:
    model_env_key = "METAGENT_OPENAI_MODEL" if provider == "openai" else "METAGENT_MINIMAX_MODEL"
    header = {
        "head": git_output(["rev-parse", "HEAD"]),
        "head_oneline": git_output(["log", "--oneline", "-1"]),
        "branch": git_output(["branch", "--show-current"]),
        "status_short": git_output(["status", "--short"]),
        "model": model,
        "provider": provider,
        "flags": {
            "METAGENT_LLM_PROVIDER": provider,
            model_env_key: model,
            "METAGENT_VERIFY_STRUCTURED_CLAIMS": "1",
            "METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT": "1",
            ENABLE_ENV: "1",
            "METAGENT_FULL344_TOOL_TIMEOUT_SECONDS": str(tool_timeout_seconds),
        },
        "paths": {
            "benchmark": str(BENCHMARK),
            "human1_crosswalk": str(DEFAULT_REFERENCE_PATH),
            "llm_log": str(LLM_LOG),
            "out_dir": str(OUT_DIR),
            "ramp_db_path": os.environ.get("RAMP_DB_PATH", ""),
        },
        "timeouts": {
            "task_timeout_seconds": task_timeout_seconds,
            "tool_timeout_seconds": tool_timeout_seconds,
        },
        "task_counts": dict(Counter(stratum_of(task) for task in read_tasks())),
    }
    VERSION_HEADER.write_text(json.dumps(header, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(header, ensure_ascii=False, indent=2))


def git_output(args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
