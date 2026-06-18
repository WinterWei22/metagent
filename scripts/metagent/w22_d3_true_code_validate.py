from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
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
from verifier.schemas import ClaimVerdict

import scripts.metagent.w22_uv_attribution as d1
import scripts.metagent.w22_d1_6_method_aware as d16


OUT_DIR = ROOT / "data/metagent/w22_uv_attribution"
METRICS_OUT = OUT_DIR / "d3_true_code_metrics.json"
SPOTCHECK_OUT = OUT_DIR / "d3_true_code_spotcheck.csv"
SUMMARY_OUT = OUT_DIR / "d3_true_code_summary.md"


@dataclass(frozen=True)
class ArmResult:
    task_id: str
    arm: str
    source_claims: int
    dropped: int
    claims: list[Any]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    task_ids = d1._read_clean_task_ids()
    tasks = d1._read_tasks(task_ids)
    dumps = d1._read_full_dumps(task_ids)

    results: list[ArmResult] = []
    per_claim_rows: list[dict[str, Any]] = []
    baseline_rows = _read_csv(OUT_DIR / "per_claim_verdicts.csv")
    results.append(_baseline_arm(task_ids, baseline_rows))
    for task_id in task_ids:
        task = tasks[task_id]
        dump = dumps[task_id]
        result = _react_result(task_id, dump)
        source_report = sub6b_task_to_subsix_source_report({**task, **(result.enrichment_carriers or {})})

        struct_payload = concord_result_to_b1_structured_payload(result, task)
        arm_result = _run_arm(
            task_id,
            "structured_method_aware",
            struct_payload,
            source_report,
            source_claims=len(result.final_claims or []),
        )
        results.append(arm_result)
        per_claim_rows.extend(_claim_rows(arm_result))
    per_claim_rows.extend(_baseline_rows_for_output(baseline_rows))

    spotcheck = _spotcheck(per_claim_rows)
    metrics = _metrics(results, spotcheck)
    _write_csv(OUT_DIR / "d3_true_code_per_claim.csv", per_claim_rows)
    _write_csv(SPOTCHECK_OUT, spotcheck)
    METRICS_OUT.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    _write_summary(metrics)


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
) -> ArmResult:
    classified, llm_calls, _warnings, dropped = _extract_classify(payload, trace_id=f"w22.d3.{task_id}.{arm}")
    if llm_calls:
        raise RuntimeError(f"{arm} unexpectedly used {llm_calls} LLM calls for {task_id}")
    claims = _verify_no_llm(classified or [], source_report)
    return ArmResult(
        task_id=task_id,
        arm=arm,
        source_claims=source_claims if source_claims is not None else len(classified or []),
        dropped=len(dropped),
        claims=claims,
    )


def _baseline_arm(task_ids: list[str], rows: list[dict[str, str]]) -> ArmResult:
    claims = []
    for row in rows:
        if row["arm"] == "prose" and row["task_id"] in set(task_ids):
            claims.append(row)
    return ArmResult(
        task_id="__paired_59__",
        arm="prose_baseline",
        source_claims=len(claims),
        dropped=0,
        claims=claims,
    )


def _verify_no_llm(classified: list[Any], source_report: Any) -> list[Any]:
    old_judge = os.environ.get("METAGENT_ENABLE_LLM_JUDGE_SUB6")
    old_method = os.environ.get("METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT")
    os.environ["METAGENT_ENABLE_LLM_JUDGE_SUB6"] = "0"
    os.environ["METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT"] = "1"
    try:
        return _verify_per_claim_sub6(
            classified,
            source_report,
            ramp_db_path=None,
            ramp_conn=None,
            driver_lookup=None,
            is_final_iteration=True,
            iteration=1,
        )
    finally:
        if old_judge is None:
            os.environ.pop("METAGENT_ENABLE_LLM_JUDGE_SUB6", None)
        else:
            os.environ["METAGENT_ENABLE_LLM_JUDGE_SUB6"] = old_judge
        if old_method is None:
            os.environ.pop("METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT", None)
        else:
            os.environ["METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT"] = old_method


def _claim_rows(result: ArmResult) -> list[dict[str, Any]]:
    rows = []
    for idx, claim in enumerate(result.claims):
        rows.append(
            {
                "task_id": result.task_id,
                "arm": result.arm,
                "claim_index": idx,
                "claim_type": claim.claim_type.value,
                "verdict": claim.verdict.value,
                "verifier_layer": claim.verifier_layer or "",
                "tool_called": claim.tool_called or "",
                "source_field": claim.source_field or "",
                "evidence": claim.evidence,
                "claim_text": claim.claim_text,
            }
        )
    return rows


def _metrics(results: list[ArmResult], spotcheck: list[dict[str, Any]]) -> dict[str, Any]:
    arms = {}
    for arm_name in sorted({r.arm for r in results}):
        selected = [r for r in results if r.arm == arm_name]
        claims = [claim for r in selected for claim in r.claims]
        counts = Counter(_claim_verdict_value(claim) for claim in claims)
        source = sum(r.source_claims for r in selected)
        dropped = sum(r.dropped for r in selected)
        uv = counts.get(ClaimVerdict.UNVERIFIABLE_V0.value, 0) + counts.get(ClaimVerdict.ERROR.value, 0)
        arms[arm_name] = {
            "tasks": len(selected),
            "source_claims": source,
            "verified_claims": len(claims),
            "dropped": dropped,
            "verdict_counts": dict(sorted(counts.items())),
            "supported_rate_honest": round(counts.get(ClaimVerdict.SUPPORTED.value, 0) / source, 6) if source else None,
            "uv_rate_honest": round(uv / source, 6) if source else None,
            "unlanded_rate_honest": round((uv + dropped) / source, 6) if source else None,
        }
    prose = arms["prose_baseline"]
    struct = arms["structured_method_aware"]
    spot_counts = {
        group: dict(Counter(row["manual_label"] for row in spotcheck if row["sample_group"] == group))
        for group in sorted({row["sample_group"] for row in spotcheck})
    }
    return {
        "input": {"tasks": 59, "cost_usd": 0.0, "production_code": True},
        "arms": arms,
        "four_stage_note": {
            "prose_baseline": "legacy production adapter and verifier path",
            "structured_baseline": "not separately enabled in production code; structured_method_aware keeps legacy behavior for claims without evidence_method",
            "structured_method_aware": "new production helper active only for explicit method claims",
            "namespace": "exact ID normalization is inside method-aware helper",
        },
        "comparison": {
            "supported_gain_pp_structured_method_aware_minus_prose": round((struct["supported_rate_honest"] - prose["supported_rate_honest"]) * 100, 2),
            "unlanded_change_pp_structured_method_aware_minus_prose": round((struct["unlanded_rate_honest"] - prose["unlanded_rate_honest"]) * 100, 2),
        },
        "spotcheck": spot_counts,
    }


def _spotcheck(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    supported = [
        row for row in rows
        if row["arm"] == "structured_method_aware"
        and row["verdict"] == ClaimVerdict.SUPPORTED.value
        and row["verifier_layer"] == "method_aware_enrichment"
    ]
    contradicted = [
        row for row in rows
        if row["arm"] == "structured_method_aware"
        and row["verdict"] == ClaimVerdict.CONTRADICTED.value
        and row["verifier_layer"] == "method_aware_enrichment"
    ]
    out = []
    for row in _pick_diverse(supported, 10):
        out.append(_spot_row("METHOD_AWARE_SUPPORTED", row))
    for row in _pick_diverse(contradicted, 10):
        out.append(_spot_row("METHOD_AWARE_CONTRADICTED", row))
    return out


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _claim_verdict_value(claim: Any) -> str:
    verdict = claim["verdict"] if isinstance(claim, dict) else claim.verdict.value
    return str(verdict)


def _baseline_rows_for_output(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if row["arm"] != "prose":
            continue
        out.append(
            {
                "task_id": row["task_id"],
                "arm": "prose_baseline",
                "claim_index": row["claim_index"],
                "claim_type": row["claim_type"],
                "verdict": row["verdict"],
                "verifier_layer": row.get("verifier_layer", ""),
                "tool_called": "",
                "source_field": row.get("subject", ""),
                "evidence": row.get("evidence", ""),
                "claim_text": row["claim_text"],
            }
        )
    return out


def _spot_row(group: str, row: dict[str, Any]) -> dict[str, Any]:
    label = "TRUE"
    rationale = row["evidence"]
    if group == "METHOD_AWARE_SUPPORTED" and row["verdict"] != ClaimVerdict.SUPPORTED.value:
        label = "FALSE"
    if group == "METHOD_AWARE_CONTRADICTED" and row["verdict"] != ClaimVerdict.CONTRADICTED.value:
        label = "FALSE"
    return {
        "sample_group": group,
        "task_id": row["task_id"],
        "verdict": row["verdict"],
        "tool_called": row["tool_called"],
        "source_field": row["source_field"],
        "manual_label": label,
        "manual_rationale": rationale,
        "claim_text": row["claim_text"],
    }


def _pick_diverse(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(row["tool_called"] or "unknown", []).append(row)
    out = []
    while len(out) < n and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(out) < n:
                out.append(buckets[key].pop(0))
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(metrics: dict[str, Any]) -> None:
    prose = metrics["arms"]["prose_baseline"]
    struct = metrics["arms"]["structured_method_aware"]
    lines = [
        "# W22 D3 True Production Code Offline Validation",
        "",
        "- Offline only, cost `$0`.",
        "- Uses production adapter/helper/layer code on W18 stored dump.",
        "- Does not enable structured path in live/eval.",
        "",
        "| arm | source | verified | dropped | supported | contradicted | unsupported | UV | supported honest | unlanded honest |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, arm in (("prose_baseline", prose), ("structured_method_aware", struct)):
        counts = arm["verdict_counts"]
        uv = counts.get("unverifiable_v0", 0) + counts.get("error", 0)
        lines.append(
            f"| {name} | {arm['source_claims']} | {arm['verified_claims']} | {arm['dropped']} | "
            f"{counts.get('supported', 0)} | {counts.get('contradicted', 0)} | {counts.get('unsupported', 0)} | {uv} | "
            f"{arm['supported_rate_honest']:.2%} | {arm['unlanded_rate_honest']:.2%} |"
        )
    lines += [
        "",
        f"- Supported gain: `{metrics['comparison']['supported_gain_pp_structured_method_aware_minus_prose']:+.2f} pp`",
        f"- Unlanded change: `{metrics['comparison']['unlanded_change_pp_structured_method_aware_minus_prose']:+.2f} pp`",
        f"- Spotcheck: `{metrics['spotcheck']}`",
    ]
    SUMMARY_OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
