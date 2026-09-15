from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from concord.agent.react_runner import ConcordReactResult
from concord.agent.verifier_adapter import (
    concord_result_to_b1_narrative,
    concord_result_to_b1_structured_payload,
    sub6b_task_to_subsix_source_report,
)
from verifier.agent import _extract_classify, _verify_per_claim_sub6
from verifier.schemas import ClaimVerdict, VerifiedClaim

import scripts.metagent.w22_uv_attribution as d1


OUT_DIR = ROOT / "data/metagent/w22_full59_paired_live"
FULL_DIR = OUT_DIR / "path_x_full"
RESULTS_JSONL = OUT_DIR / "path_x_results.jsonl"
LLM_LOG = ROOT / "logs/concord/w22_full59_paired_live.jsonl"
PER_CLAIM_OUT = OUT_DIR / "paired_per_claim.csv"
PER_TASK_OUT = OUT_DIR / "paired_per_task.csv"
METRICS_OUT = OUT_DIR / "paired_metrics.json"
SAMPLE_OUT = OUT_DIR / "manual_validation_candidates.csv"
SUMMARY_OUT = OUT_DIR / "paired_summary.md"

UV_VERDICTS = {ClaimVerdict.UNVERIFIABLE_V0.value, ClaimVerdict.ERROR.value}


@dataclass(frozen=True)
class ArmResult:
    task_id: str
    arm: str
    source_claims: int
    dropped: int
    claims: list[VerifiedClaim]
    suppressed_llm_calls: int


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    task_ids = _read_live_task_ids()
    tasks = d1._read_tasks(task_ids)

    arm_results: list[ArmResult] = []
    per_claim_rows: list[dict[str, Any]] = []
    for task_id in task_ids:
        task = tasks[task_id]
        dump = _read_dump(task_id)
        result = _react_result(task_id, dump)
        source_report = sub6b_task_to_subsix_source_report({
            **task,
            **(result.enrichment_carriers or {}),
        })

        prose = _run_arm(
            task_id,
            "prose",
            concord_result_to_b1_narrative(result, task),
            source_report,
            source_claims=None,
            method_aware=False,
            extractor_mode="rule-based",
        )
        structured = _run_arm(
            task_id,
            "structured_method_aware",
            concord_result_to_b1_structured_payload(result, task),
            source_report,
            source_claims=len(result.final_claims or []),
            method_aware=True,
            extractor_mode="llm",
        )
        arm_results.extend([prose, structured])
        per_claim_rows.extend(_claim_rows(prose))
        per_claim_rows.extend(_claim_rows(structured))

    per_task_rows = _per_task_rows(arm_results)
    metrics = _metrics(arm_results, per_task_rows)
    samples = _validation_candidates(per_claim_rows)

    _write_csv(PER_CLAIM_OUT, per_claim_rows)
    _write_csv(PER_TASK_OUT, per_task_rows)
    _write_csv(SAMPLE_OUT, samples)
    METRICS_OUT.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    _write_summary(metrics, samples)


def _read_live_task_ids() -> list[str]:
    ids: list[str] = []
    with RESULTS_JSONL.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            task_id = row.get("task_id")
            if task_id:
                ids.append(str(task_id))
    return ids


def _read_dump(task_id: str) -> dict[str, Any]:
    return json.loads((FULL_DIR / f"{task_id}.json").read_text(encoding="utf-8"))


def _react_result(task_id: str, dump: dict[str, Any]) -> ConcordReactResult:
    final = dump.get("final_react_result") or {}
    return ConcordReactResult(
        task_id=task_id,
        final_narrative_text=final.get("final_narrative_text") or "",
        final_claims=final.get("final_claims") or [],
        enrichment_carriers=final.get("enrichment_carriers") or {},
    )


def _run_arm(
    task_id: str,
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
        classified, llm_calls, warnings, dropped = _extract_classify_no_llm(
            payload,
            trace_id=f"w22.d7.{task_id}.{arm}",
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
            arm=arm,
            source_claims=source_claims if source_claims is not None else len(classified),
            dropped=len(dropped),
            claims=claims,
            suppressed_llm_calls=llm_calls,
        )
    finally:
        _restore_env("METAGENT_ENABLE_LLM_JUDGE_SUB6", old_judge)
        _restore_env("METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT", old_method)
        _restore_env("METAGENT_VERIFIER_EXTRACTOR", old_extractor)
        _restore_env("METAGENT_TOOL_OUTPUT_TRACE_PATH", old_trace)


def _extract_classify_no_llm(
    payload: str,
    *,
    trace_id: str,
) -> tuple[list[Any] | None, int, list[str], list[Any]]:
    import verifier.claim_classifier as classifier

    original = classifier._llm_classify
    try:
        classifier._llm_classify = lambda texts, trace_id: [None] * len(texts)
        classified, llm_calls, warnings, dropped = _extract_classify(
            payload,
            trace_id=trace_id,
        )
    finally:
        classifier._llm_classify = original
    return classified, llm_calls, warnings, dropped


def _restore_env(key: str, old_value: str | None) -> None:
    if old_value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = old_value


def _claim_rows(result: ArmResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, claim in enumerate(result.claims):
        rows.append({
            "task_id": result.task_id,
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


def _per_task_rows(results: list[ArmResult]) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        counts = Counter(claim.verdict.value for claim in result.claims)
        uv = sum(counts[v] for v in UV_VERDICTS)
        honest = result.source_claims or len(result.claims) + result.dropped
        rows.append({
            "task_id": result.task_id,
            "arm": result.arm,
            "source_claims": result.source_claims,
            "verified_claims": len(result.claims),
            "dropped": result.dropped,
            "supported": counts[ClaimVerdict.SUPPORTED.value],
            "contradicted": counts[ClaimVerdict.CONTRADICTED.value],
            "unsupported": counts[ClaimVerdict.UNSUPPORTED.value],
            "needs_human_review": counts[ClaimVerdict.NEEDS_HUMAN_REVIEW.value],
            "uv": uv,
            "supported_rate_honest": _ratio(counts[ClaimVerdict.SUPPORTED.value], honest),
            "unlanded_rate_honest": _ratio(uv + result.dropped, honest),
        })
    return rows


def _metrics(results: list[ArmResult], per_task_rows: list[dict[str, Any]]) -> dict[str, Any]:
    arms = {}
    for arm in sorted({r.arm for r in results}):
        selected = [r for r in results if r.arm == arm]
        counts = Counter(claim.verdict.value for r in selected for claim in r.claims)
        source = sum(r.source_claims for r in selected)
        dropped = sum(r.dropped for r in selected)
        verified = sum(len(r.claims) for r in selected)
        uv = sum(counts[v] for v in UV_VERDICTS)
        arms[arm] = {
            "tasks": len(selected),
            "source_claims": source,
            "verified_claims": verified,
            "dropped": dropped,
            "verdict_counts": dict(sorted(counts.items())),
            "supported_rate_honest": _ratio(counts[ClaimVerdict.SUPPORTED.value], source),
            "contradicted_rate_honest": _ratio(counts[ClaimVerdict.CONTRADICTED.value], source),
            "unsupported_rate_honest": _ratio(counts[ClaimVerdict.UNSUPPORTED.value], source),
            "needs_human_review_rate_honest": _ratio(counts[ClaimVerdict.NEEDS_HUMAN_REVIEW.value], source),
            "uv_rate_honest": _ratio(uv, source),
            "unlanded_rate_honest": _ratio(uv + dropped, source),
        }
    prose = arms["prose"]
    structured = arms["structured_method_aware"]
    live_cost = _llm_cost()
    return {
        "input": {
            "tasks": len({r.task_id for r in results}),
            "live_dump_dir": str(FULL_DIR.relative_to(ROOT)),
            "llm_log": str(LLM_LOG.relative_to(ROOT)),
            **live_cost,
            "cost_rate": "$0.30/M prompt + $1.20/M completion",
        },
        "arms": arms,
        "comparison": {
            "supported_gain_pp_structured_minus_prose": _pp(
                structured["supported_rate_honest"] - prose["supported_rate_honest"]
            ),
            "unlanded_change_pp_structured_minus_prose": _pp(
                structured["unlanded_rate_honest"] - prose["unlanded_rate_honest"]
            ),
            "uv_change_pp_structured_minus_prose": _pp(
                structured["uv_rate_honest"] - prose["uv_rate_honest"]
            ),
        },
        "per_task_delta": _per_task_delta(per_task_rows),
    }


def _per_task_delta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_task[row["task_id"]][row["arm"]] = row
    supported_deltas = []
    unlanded_deltas = []
    for arms in by_task.values():
        if "prose" not in arms or "structured_method_aware" not in arms:
            continue
        supported_deltas.append(
            arms["structured_method_aware"]["supported_rate_honest"]
            - arms["prose"]["supported_rate_honest"]
        )
        unlanded_deltas.append(
            arms["structured_method_aware"]["unlanded_rate_honest"]
            - arms["prose"]["unlanded_rate_honest"]
        )
    return {
        "mean_supported_gain_pp": _pp(sum(supported_deltas) / len(supported_deltas)),
        "mean_unlanded_change_pp": _pp(sum(unlanded_deltas) / len(unlanded_deltas)),
        "tasks_with_supported_gain": sum(1 for x in supported_deltas if x > 0),
        "tasks_with_supported_loss": sum(1 for x in supported_deltas if x < 0),
    }


def _validation_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_task_arm_claim: dict[tuple[str, str, str], dict[str, Any]] = {}
    by_task_text: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["claim_index"] == "__dropped__":
            continue
        by_task_arm_claim[(row["task_id"], row["arm"], str(row["claim_index"]))] = row
        by_task_text[(row["task_id"], _norm_text(row["claim_text"]))].append(row)

    gained: list[dict[str, Any]] = []
    contradicted: list[dict[str, Any]] = []
    for row in rows:
        if row["arm"] != "structured_method_aware" or row["claim_index"] == "__dropped__":
            continue
        if row["verifier_layer"] != "method_aware_enrichment":
            continue
        prose_matches = [
            r for r in by_task_text.get((row["task_id"], _norm_text(row["claim_text"])), [])
            if r["arm"] == "prose"
        ]
        prose_verdicts = {r["verdict"] for r in prose_matches}
        if row["verdict"] == ClaimVerdict.SUPPORTED.value and ClaimVerdict.SUPPORTED.value not in prose_verdicts:
            gained.append(_sample_row("pipeline_lost_to_supported", row, prose_verdicts))
        if row["verdict"] == ClaimVerdict.CONTRADICTED.value:
            contradicted.append(_sample_row("new_contradicted", row, prose_verdicts))
    return _pick_diverse(gained, 19) + _pick_diverse(contradicted, 1)


def _sample_row(group: str, row: dict[str, Any], prose_verdicts: set[str]) -> dict[str, Any]:
    return {
        "sample_group": group,
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


def _pick_diverse(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[row["tool_called"] or "unknown"].append(row)
    out: list[dict[str, Any]] = []
    while len(out) < n and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(out) < n:
                out.append(buckets[key].pop(0))
    return out


def _llm_cost() -> dict[str, Any]:
    rows = [json.loads(line) for line in LLM_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
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
        "actual_cost_usd": round(prompt * 0.30 / 1_000_000 + completion * 1.20 / 1_000_000, 6),
        "llm_errors": sum(1 for row in rows if row.get("error")),
        "models": sorted({row.get("model") for row in rows}),
    }


def _ratio(num: int, den: int) -> float:
    return round(num / den, 6) if den else 0.0


def _pp(value: float) -> float:
    return round(value * 100, 2)


def _norm_text(text: str) -> str:
    return " ".join(str(text).lower().split())


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(metrics: dict[str, Any], samples: list[dict[str, Any]]) -> None:
    arms = metrics["arms"]
    lines = [
        "# W22 D7 Full59 Paired Live",
        "",
        f"- Tasks: `{metrics['input']['tasks']}`",
        f"- MiniMax cost: `${metrics['input']['actual_cost_usd']:.4f}` from `{metrics['input']['prompt_tokens']}` prompt + `{metrics['input']['completion_tokens']}` completion tokens.",
        f"- LLM errors: `{metrics['input']['llm_errors']}`",
        "",
        "| arm | source | verified | dropped | supported | contradicted | unsupported | needs_review | UV | supported honest | unlanded honest |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm_name in ("prose", "structured_method_aware"):
        arm = arms[arm_name]
        counts = arm["verdict_counts"]
        uv = sum(counts.get(v, 0) for v in UV_VERDICTS)
        lines.append(
            f"| {arm_name} | {arm['source_claims']} | {arm['verified_claims']} | {arm['dropped']} | "
            f"{counts.get('supported', 0)} | {counts.get('contradicted', 0)} | "
            f"{counts.get('unsupported', 0)} | {counts.get('needs_human_review', 0)} | {uv} | "
            f"{arm['supported_rate_honest']:.2%} | {arm['unlanded_rate_honest']:.2%} |"
        )
    lines += [
        "",
        f"- Supported gain: `{metrics['comparison']['supported_gain_pp_structured_minus_prose']:+.2f} pp`",
        f"- Unlanded change: `{metrics['comparison']['unlanded_change_pp_structured_minus_prose']:+.2f} pp`",
        f"- Validation candidate rows: `{len(samples)}` in `{SAMPLE_OUT.relative_to(ROOT)}`",
    ]
    SUMMARY_OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
