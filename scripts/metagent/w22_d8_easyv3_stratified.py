from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from concord.agent.react_runner import ConcordReactResult, ConcordReactRunner
from concord.agent.verifier_adapter import (
    concord_result_to_b1_narrative,
    concord_result_to_b1_structured_payload,
    sub6b_task_to_subsix_source_report,
)
from evaluation.concord.path_x import _per_task_signals, aggregate_path_x
from verifier.agent import _extract_classify, _verify_per_claim_sub6, verify_sub6
from verifier.schemas import ClaimVerdict, VerifiedClaim


BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
OUT_DIR = ROOT / "data/metagent/w22_easyv3_stratified_paired"
FULL_DIR = OUT_DIR / "path_x_full"
STATUS_DIR = OUT_DIR / "status"
RUN_JSONL = OUT_DIR / "path_x_results.jsonl"
SUMMARY_JSON = OUT_DIR / "path_x_summary.json"
LLM_LOG = ROOT / "logs/concord/w22_easyv3_stratified_paired.jsonl"
MINIMAX_KEY_FILE = ROOT.parent / "metagent_day1_v5/api_key_minimax.txt"
SMOKE_IDS = OUT_DIR / "phase_a_smoke_task_ids.txt"
PER_CLAIM_OUT = OUT_DIR / "paired_per_claim.csv"
PER_TASK_OUT = OUT_DIR / "paired_per_task.csv"
METRICS_OUT = OUT_DIR / "paired_metrics_by_stratum.json"
VALIDATION_CANDIDATES_OUT = OUT_DIR / "manual_validation_candidates.csv"
SUMMARY_OUT = OUT_DIR / "paired_summary_by_stratum.md"

MODEL = "MiniMax-M2.7-highspeed"
PROVIDER = "minimax"
PROMPT_COST_PER_M = 0.30
COMPLETION_COST_PER_M = 1.20
UV_VERDICTS = {ClaimVerdict.UNVERIFIABLE_V0.value, ClaimVerdict.ERROR.value}


@dataclass(frozen=True)
class ArmResult:
    task_id: str
    stratum: str
    arm: str
    source_claims: int
    dropped: int
    claims: list[VerifiedClaim]
    suppressed_llm_calls: int


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["smoke", "full", "analyze", "run-one", "aggregate"])
    parser.add_argument("--task-id")
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--cost-cap-usd", type=float, default=25.0)
    parser.add_argument("--smoke-per-stratum", type=int, default=12)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    LLM_LOG.parent.mkdir(parents=True, exist_ok=True)

    if args.command == "run-one":
        if not args.task_id:
            raise SystemExit("--task-id is required for run-one")
        return run_one(args.task_id)
    if args.command == "smoke":
        task_ids = select_smoke_ids(args.smoke_per_stratum)
        SMOKE_IDS.write_text("\n".join(task_ids) + "\n", encoding="utf-8")
        code = run_scheduler(task_ids, args.k, args.timeout_seconds, args.cost_cap_usd)
        aggregate_run_outputs()
        analyze()
        return code
    if args.command == "full":
        task_ids = [row["task_id"] for row in read_tasks()]
        code = run_scheduler(task_ids, args.k, args.timeout_seconds, args.cost_cap_usd)
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


def read_tasks() -> list[dict[str, Any]]:
    with BENCHMARK.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def task_map() -> dict[str, dict[str, Any]]:
    return {row["task_id"]: row for row in read_tasks()}


def stratum_of(task: dict[str, Any]) -> str:
    source = task.get("provenance", {}).get("source") or ""
    if source == "Cooke 2025 simulatedPA":
        return "cooke_human1_recon22"
    if source == "Sub-6 HMDB/RaMP mammalian constructed enrichment":
        return "sub6_hmdb_ramp_enrichment"
    if source == "HMDB/RaMP constructed pathway-membership easy expansion":
        return "hmdb_ramp_pathway_membership"
    return "unknown"


def select_smoke_ids(per_stratum: int) -> list[str]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in read_tasks():
        buckets[stratum_of(row)].append(row["task_id"])
    selected: list[str] = []
    for stratum in (
        "cooke_human1_recon22",
        "sub6_hmdb_ramp_enrichment",
        "hmdb_ramp_pathway_membership",
    ):
        selected.extend(buckets[stratum][:per_stratum])
    return selected


def run_scheduler(
    task_ids: list[str],
    k: int,
    timeout_seconds: int,
    cost_cap_usd: float,
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
            env = dict(os.environ)
            if not env.get("MINIMAX_API_KEY") and MINIMAX_KEY_FILE.exists():
                env["MINIMAX_API_KEY"] = MINIMAX_KEY_FILE.read_text(encoding="utf-8").strip()
            env["METAGENT_LLM_LOG_PATH"] = str(LLM_LOG)
            env["METAGENT_LLM_PROVIDER"] = PROVIDER
            env["METAGENT_MINIMAX_MODEL"] = MODEL
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
                write_status(tid, {
                    "task_id": tid,
                    "ok": False,
                    "error": f"task_timeout_after_{timeout_seconds}s",
                    "wall_seconds": round(time.time() - started, 3),
                })
                running.pop(tid)
                print(f"timeout {tid}")

        cost = llm_cost()["actual_cost_usd"]
        if cost >= cost_cap_usd:
            print(f"STOP cost cap reached: ${cost:.6f} >= ${cost_cap_usd:.2f}")
            for tid, (proc, _) in running.items():
                proc.terminate()
                write_status(tid, {
                    "task_id": tid,
                    "ok": False,
                    "error": "terminated_cost_cap",
                })
            return 2
    return 0


def run_one(task_id: str) -> int:
    import common.llm_client as llm_client

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
        fb = runner.run_task_with_feedback(task, trace_id=f"w22.d8.{task_id}")
        signals = _per_task_signals(task, fb)
        signals["stratum"] = stratum_of(raw_task)
        signals["framework_signal_crash"] = None
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
        write_status(task_id, {
            "task_id": task_id,
            "stratum": stratum_of(raw_task),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "wall_seconds": round(time.time() - started, 3),
        })
        return 1


def to_sub6_shape(task: dict[str, Any]) -> dict[str, Any]:
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
        },
        "ground_truth_signal_compounds": [metabolite_key(met) for met in metabolites],
        "ground_truth_noise_compounds": [],
        "ramp_enrichment_result": {"top_pathways": []},
        "provenance": task.get("provenance", {}),
    }


def metabolite_key(metabolite: dict[str, Any]) -> str:
    for key in ("kegg_id", "id", "hmdb_id", "name"):
        value = metabolite.get(key)
        if value:
            return str(value)
    return json.dumps(metabolite, sort_keys=True)


def status_path(task_id: str) -> Path:
    return STATUS_DIR / f"{task_id}.json"


def write_status(task_id: str, row: dict[str, Any]) -> None:
    status_path(task_id).write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


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
    arm_results: list[ArmResult] = []
    per_claim_rows: list[dict[str, Any]] = []
    for task_id in task_ids:
        raw_task = tasks[task_id]
        task = to_sub6_shape(raw_task)
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
        per_claim_rows.extend(claim_rows(prose))
        per_claim_rows.extend(claim_rows(structured))

    per_task_rows = per_task_rows_from_results(arm_results)
    metrics = metrics_by_stratum(arm_results, per_task_rows)
    samples = validation_candidates(per_claim_rows)
    write_csv(PER_CLAIM_OUT, per_claim_rows)
    write_csv(PER_TASK_OUT, per_task_rows)
    write_csv(VALIDATION_CANDIDATES_OUT, samples)
    METRICS_OUT.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    write_summary(metrics, samples)


def react_result(task_id: str, dump: dict[str, Any]) -> ConcordReactResult:
    final = dump.get("final_react_result") or {}
    return ConcordReactResult(
        task_id=task_id,
        final_narrative_text=final.get("final_narrative_text") or "",
        final_claims=final.get("final_claims") or [],
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
) -> ArmResult:
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
        classified, llm_calls, warnings, dropped = extract_classify_no_llm(
            payload,
            trace_id=f"w22.d8.{task_id}.{arm}",
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
        return ArmResult(
            task_id=task_id,
            stratum=stratum,
            arm=arm,
            source_claims=source_claims if source_claims is not None else len(classified),
            dropped=len(dropped),
            claims=claims,
            suppressed_llm_calls=llm_calls,
        )
    finally:
        restore_env("METAGENT_ENABLE_LLM_JUDGE_SUB6", old_judge)
        restore_env("METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT", old_method)
        restore_env("METAGENT_VERIFIER_EXTRACTOR", old_extractor)
        restore_env("METAGENT_TOOL_OUTPUT_TRACE_PATH", old_trace)


def extract_classify_no_llm(payload: str, *, trace_id: str) -> tuple[list[Any] | None, int, list[str], list[Any]]:
    import verifier.claim_classifier as classifier

    original = classifier._llm_classify
    try:
        classifier._llm_classify = lambda texts, trace_id: [None] * len(texts)
        classified, llm_calls, warnings, dropped = _extract_classify(payload, trace_id=trace_id)
    finally:
        classifier._llm_classify = original
    return classified, llm_calls, warnings, dropped


def restore_env(key: str, old_value: str | None) -> None:
    if old_value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = old_value


def claim_rows(result: ArmResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, claim in enumerate(result.claims):
        rows.append({
            "task_id": result.task_id,
            "stratum": result.stratum,
            "arm": result.arm,
            "claim_index": idx,
            "claim_type": claim.claim_type.value,
            "claim_subtype": claim.claim_subtype.value if claim.claim_subtype else "",
            "grammar": claim.grammar or "",
            "verdict": claim.verdict.value,
            "verifier_layer": claim.verifier_layer or "",
            "tool_called": claim.tool_called or "",
            "source_field": claim.source_field or "",
            "subject": claim.subject or "",
            "evidence_method": getattr(claim.extracted_fields, "evidence_method", None) or "",
            "pathway_id": getattr(claim.extracted_fields, "pathway_id", None) or "",
            "pathway_name": getattr(claim.extracted_fields, "pathway_name", None) or "",
            "rank": getattr(claim.extracted_fields, "rank", None) or "",
            "score_value": getattr(claim.extracted_fields, "score_value", None) or "",
            "evidence": claim.evidence or "",
            "claim_text": claim.claim_text,
        })
    if result.dropped:
        rows.append({
            "task_id": result.task_id,
            "stratum": result.stratum,
            "arm": result.arm,
            "claim_index": "__dropped__",
            "claim_type": "",
            "claim_subtype": "",
            "grammar": "",
            "verdict": "dropped",
            "verifier_layer": "grammar",
            "tool_called": "",
            "source_field": "",
            "subject": "",
            "evidence_method": "",
            "pathway_id": "",
            "pathway_name": "",
            "rank": "",
            "score_value": "",
            "evidence": f"{result.dropped} claims dropped by grammar",
            "claim_text": "",
        })
    return rows


def per_task_rows_from_results(results: list[ArmResult]) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        counts = Counter(claim.verdict.value for claim in result.claims)
        uv = sum(counts[v] for v in UV_VERDICTS)
        honest = result.source_claims or len(result.claims) + result.dropped
        rows.append({
            "task_id": result.task_id,
            "stratum": result.stratum,
            "arm": result.arm,
            "source_claims": result.source_claims,
            "verified_claims": len(result.claims),
            "dropped": result.dropped,
            "supported": counts[ClaimVerdict.SUPPORTED.value],
            "contradicted": counts[ClaimVerdict.CONTRADICTED.value],
            "unsupported": counts[ClaimVerdict.UNSUPPORTED.value],
            "needs_human_review": counts[ClaimVerdict.NEEDS_HUMAN_REVIEW.value],
            "uv": uv,
            "supported_rate_honest": ratio(counts[ClaimVerdict.SUPPORTED.value], honest),
            "unlanded_rate_honest": ratio(uv + result.dropped, honest),
            "method_aware_hits": sum(1 for claim in result.claims if claim.verifier_layer == "method_aware_enrichment"),
        })
    return rows


def metrics_by_stratum(results: list[ArmResult], per_task_rows: list[dict[str, Any]]) -> dict[str, Any]:
    strata: dict[str, Any] = {}
    for stratum in sorted({r.stratum for r in results}):
        strata[stratum] = metrics_for_results(
            [r for r in results if r.stratum == stratum],
            [r for r in per_task_rows if r["stratum"] == stratum],
        )
    return {
        "input": {
            "benchmark": str(BENCHMARK.relative_to(ROOT)),
            "tasks_completed": len({r.task_id for r in results}),
            "llm_log": str(LLM_LOG.relative_to(ROOT)),
            **llm_cost(),
            "cost_rate": "$0.30/M prompt + $1.20/M completion",
        },
        "strata": strata,
    }


def metrics_for_results(results: list[ArmResult], per_task_rows: list[dict[str, Any]]) -> dict[str, Any]:
    arms = {}
    for arm in sorted({r.arm for r in results}):
        selected = [r for r in results if r.arm == arm]
        counts = Counter(claim.verdict.value for r in selected for claim in r.claims)
        source = sum(r.source_claims for r in selected)
        dropped = sum(r.dropped for r in selected)
        verified = sum(len(r.claims) for r in selected)
        uv = sum(counts[v] for v in UV_VERDICTS)
        method_hits = sum(
            1 for r in selected for claim in r.claims
            if claim.verifier_layer == "method_aware_enrichment"
        )
        arms[arm] = {
            "tasks": len(selected),
            "source_claims": source,
            "verified_claims": verified,
            "dropped": dropped,
            "verdict_counts": dict(sorted(counts.items())),
            "supported_rate_honest": ratio(counts[ClaimVerdict.SUPPORTED.value], source),
            "contradicted_rate_honest": ratio(counts[ClaimVerdict.CONTRADICTED.value], source),
            "unsupported_rate_honest": ratio(counts[ClaimVerdict.UNSUPPORTED.value], source),
            "needs_human_review_rate_honest": ratio(counts[ClaimVerdict.NEEDS_HUMAN_REVIEW.value], source),
            "uv_rate_honest": ratio(uv, source),
            "unlanded_rate_honest": ratio(uv + dropped, source),
            "method_aware_hit_rate": ratio(method_hits, verified),
        }
    prose = arms.get("prose", {})
    structured = arms.get("structured_method_aware", {})
    return {
        "arms": arms,
        "comparison": {
            "supported_gain_pp_structured_minus_prose": pp(
                structured.get("supported_rate_honest", 0.0) - prose.get("supported_rate_honest", 0.0)
            ),
            "unlanded_change_pp_structured_minus_prose": pp(
                structured.get("unlanded_rate_honest", 0.0) - prose.get("unlanded_rate_honest", 0.0)
            ),
            "uv_change_pp_structured_minus_prose": pp(
                structured.get("uv_rate_honest", 0.0) - prose.get("uv_rate_honest", 0.0)
            ),
        },
        "per_task_delta": per_task_delta(per_task_rows),
    }


def per_task_delta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_task[row["task_id"]][row["arm"]] = row
    supported_deltas = []
    unlanded_deltas = []
    for arms in by_task.values():
        if "prose" not in arms or "structured_method_aware" not in arms:
            continue
        supported_deltas.append(
            arms["structured_method_aware"]["supported_rate_honest"] - arms["prose"]["supported_rate_honest"]
        )
        unlanded_deltas.append(
            arms["structured_method_aware"]["unlanded_rate_honest"] - arms["prose"]["unlanded_rate_honest"]
        )
    return {
        "mean_supported_gain_pp": pp(sum(supported_deltas) / len(supported_deltas)) if supported_deltas else 0.0,
        "mean_unlanded_change_pp": pp(sum(unlanded_deltas) / len(unlanded_deltas)) if unlanded_deltas else 0.0,
        "tasks_with_supported_gain": sum(1 for x in supported_deltas if x > 0),
        "tasks_with_supported_loss": sum(1 for x in supported_deltas if x < 0),
    }


def validation_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_task_text: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["claim_index"] != "__dropped__":
            by_task_text[(row["task_id"], norm_text(row["claim_text"]))].append(row)
    gained_by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    contradicted_by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["arm"] != "structured_method_aware" or row["claim_index"] == "__dropped__":
            continue
        if row["verifier_layer"] != "method_aware_enrichment":
            continue
        prose_matches = [
            r for r in by_task_text.get((row["task_id"], norm_text(row["claim_text"])), [])
            if r["arm"] == "prose"
        ]
        prose_verdicts = {r["verdict"] for r in prose_matches}
        if row["verdict"] == ClaimVerdict.SUPPORTED.value and ClaimVerdict.SUPPORTED.value not in prose_verdicts:
            gained_by_stratum[row["stratum"]].append(sample_row("pipeline_lost_to_supported", row, prose_verdicts))
        if row["verdict"] == ClaimVerdict.CONTRADICTED.value:
            contradicted_by_stratum[row["stratum"]].append(sample_row("new_contradicted_do_not_trust_yet", row, prose_verdicts))
    out: list[dict[str, Any]] = []
    for stratum in sorted(set(gained_by_stratum) | set(contradicted_by_stratum)):
        out.extend(pick_diverse(gained_by_stratum[stratum], 10))
        out.extend(pick_diverse(contradicted_by_stratum[stratum], 2))
    return out


def sample_row(group: str, row: dict[str, Any], prose_verdicts: set[str]) -> dict[str, Any]:
    return {
        "sample_group": group,
        "stratum": row["stratum"],
        "task_id": row["task_id"],
        "structured_verdict": row["verdict"],
        "prose_verdicts_same_text": ";".join(sorted(prose_verdicts)),
        "tool_called": row["tool_called"],
        "source_field": row["source_field"],
        "pathway_id": row["pathway_id"],
        "pathway_name": row["pathway_name"],
        "rank": row["rank"],
        "score_value": row["score_value"],
        "evidence": row["evidence"],
        "claim_text": row["claim_text"],
        "manual_label": "",
        "manual_rationale": "",
    }


def pick_diverse(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[row["tool_called"] or "unknown"].append(row)
    out: list[dict[str, Any]] = []
    while len(out) < n and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(out) < n:
                out.append(buckets[key].pop(0))
    return out


def llm_cost() -> dict[str, Any]:
    if not LLM_LOG.exists():
        return {
            "llm_rows": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
            "actual_cost_usd": 0.0,
            "llm_errors": 0,
            "models": [],
        }
    rows = []
    for line in LLM_LOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    prompt = sum(int(row.get("prompt_tokens") or 0) for row in rows)
    completion = sum(int(row.get("completion_tokens") or 0) for row in rows)
    cached = sum(int(row.get("cached_tokens") or 0) for row in rows)
    total = sum(int(row.get("total_tokens") or 0) for row in rows)
    return {
        "llm_rows": len(rows),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cached_tokens": cached,
        "total_tokens": total,
        "actual_cost_usd": round(prompt * PROMPT_COST_PER_M / 1_000_000 + completion * COMPLETION_COST_PER_M / 1_000_000, 6),
        "llm_errors": sum(1 for row in rows if row.get("error")),
        "models": sorted({row.get("model") for row in rows}),
    }


def ratio(num: int, den: int) -> float:
    return round(num / den, 6) if den else 0.0


def pp(value: float) -> float:
    return round(value * 100, 2)


def norm_text(text: str) -> str:
    return " ".join(str(text).lower().split())


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_summary(metrics: dict[str, Any], samples: list[dict[str, Any]]) -> None:
    lines = [
        "# W22 D8 easy_v3 stratified paired evaluation",
        "",
        f"- Completed tasks in paired analysis: `{metrics['input']['tasks_completed']}`",
        f"- MiniMax cost: `${metrics['input']['actual_cost_usd']:.6f}` from `{metrics['input']['prompt_tokens']}` prompt + `{metrics['input']['completion_tokens']}` completion tokens.",
        f"- LLM errors: `{metrics['input']['llm_errors']}`",
        f"- Models: `{', '.join(str(x) for x in metrics['input']['models'])}`",
        "",
        "| stratum | arm | tasks | source | verified | dropped | supported | contradicted | unsupported | needs_review | UV | method-aware hit | supported honest | unlanded honest |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for stratum, block in metrics["strata"].items():
        for arm_name in ("prose", "structured_method_aware"):
            arm = block["arms"].get(arm_name, {})
            counts = arm.get("verdict_counts", {})
            uv = sum(counts.get(v, 0) for v in UV_VERDICTS)
            lines.append(
                f"| {stratum} | {arm_name} | {arm.get('tasks', 0)} | {arm.get('source_claims', 0)} | "
                f"{arm.get('verified_claims', 0)} | {arm.get('dropped', 0)} | "
                f"{counts.get('supported', 0)} | {counts.get('contradicted', 0)} | "
                f"{counts.get('unsupported', 0)} | {counts.get('needs_human_review', 0)} | {uv} | "
                f"{arm.get('method_aware_hit_rate', 0):.2%} | "
                f"{arm.get('supported_rate_honest', 0):.2%} | {arm.get('unlanded_rate_honest', 0):.2%} |"
            )
    lines += [
        "",
        "| stratum | supported gain | UV change | unlanded change | task mean supported gain | supported gain tasks/loss tasks |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for stratum, block in metrics["strata"].items():
        comp = block["comparison"]
        delta = block["per_task_delta"]
        lines.append(
            f"| {stratum} | {comp['supported_gain_pp_structured_minus_prose']:+.2f} pp | "
            f"{comp['uv_change_pp_structured_minus_prose']:+.2f} pp | "
            f"{comp['unlanded_change_pp_structured_minus_prose']:+.2f} pp | "
            f"{delta['mean_supported_gain_pp']:+.2f} pp | "
            f"{delta['tasks_with_supported_gain']}/{delta['tasks_with_supported_loss']} |"
        )
    lines += [
        "",
        f"- Validation candidate rows: `{len(samples)}` in `{VALIDATION_CANDIDATES_OUT.relative_to(ROOT)}`",
        "- Contradicted rows remain caveated because the D7 scientific-notation parser bug is intentionally not fixed here.",
    ]
    SUMMARY_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
