from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from concord.agent.verifier_adapter import sub6b_task_to_subsix_source_report
from verifier.agent import _verify_per_claim_sub6
from verifier.claim_classifier import classify_claims
from verifier.claim_extractor import extract_claims_from_json, extract_claims_rulebased
from verifier.metrics import compute_claim_metrics
from verifier.schemas import ClaimVerdict, VerifiedClaim


BENCHMARK = ROOT / "data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl"
W18_CLEAN = ROOT / "data/metagent/w18_path_x_post_llm_judge_full63_d5_clean/path_x_full63_results.jsonl"
W18_FULL_DIRS = (
    ROOT / "data/metagent/w18_path_x_post_llm_judge_full63_d5/path_x_full",
    ROOT / "data/metagent/w18_path_x_post_llm_judge_full63_d5_rerun30/path_x_full",
)
OUT_DIR = ROOT / "data/metagent/w22_uv_attribution"


NON_UV = {
    ClaimVerdict.SUPPORTED,
    ClaimVerdict.CONTRADICTED,
    ClaimVerdict.UNSUPPORTED,
    ClaimVerdict.NEEDS_HUMAN_REVIEW,
}
UV = {ClaimVerdict.UNVERIFIABLE_V0, ClaimVerdict.ERROR}


@dataclass(frozen=True)
class ArmResult:
    task_id: str
    arm: str
    claims: list[VerifiedClaim]
    dropped: int
    extract_claim_count: int
    drop_reasons: dict[str, int] | None = None


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    task_ids = _read_clean_task_ids()
    tasks = _read_tasks(task_ids)
    dumps = _read_full_dumps(task_ids)

    arm_results: list[ArmResult] = []
    per_claim_rows: list[dict[str, Any]] = []
    attribution_rows: list[dict[str, Any]] = []

    for task_id in task_ids:
        task = tasks[task_id]
        dump = dumps[task_id]
        source_report = _source_report_for(task, dump)
        final = dump["final_react_result"]

        prose = run_prose_arm(task_id, final.get("final_narrative_text") or "", source_report)
        struct = run_struct_arm(task_id, final.get("final_claims") or [], source_report)
        arm_results.extend([prose, struct])
        per_claim_rows.extend(_claim_rows(prose))
        per_claim_rows.extend(_claim_rows(struct))
        attribution_rows.extend(_attribute_task(task_id, prose.claims, struct.claims))

    metrics = _metrics(arm_results, attribution_rows)
    _write_json(OUT_DIR / "two_arm_metrics.json", metrics)
    _write_csv(OUT_DIR / "per_claim_verdicts.csv", per_claim_rows)
    _write_csv(OUT_DIR / "per_claim_attribution.csv", attribution_rows)
    _write_summary(metrics)


def run_prose_arm(task_id: str, narrative: str, source_report: Any) -> ArmResult:
    extracted = extract_claims_rulebased(narrative, trace_id=f"w22.{task_id}.prose.extract")
    classified, _calls = _classify_no_llm(extracted, trace_id=f"w22.{task_id}.prose.classify")
    claims = _verify_no_llm(classified, source_report, task_id=task_id)
    return ArmResult(
        task_id=task_id,
        arm="prose",
        claims=claims,
        dropped=0,
        extract_claim_count=len(extracted),
        drop_reasons={},
    )


def run_struct_arm(task_id: str, raw_claims: list[dict[str, Any]], source_report: Any) -> ArmResult:
    converted_claims = []
    drop_reasons: Counter[str] = Counter()
    for claim in raw_claims:
        converted = _convert_final_claim(claim)
        if converted is None:
            drop_reasons[f"conversion_missing:{claim.get('claim_type') or 'unknown'}"] += 1
        else:
            converted_claims.append(converted)
    payload = {"narrative_text": "", "claims": converted_claims}
    extracted, dropped = extract_claims_from_json(
        payload,
        trace_id=f"w22.{task_id}.struct.extract",
    )
    for dropped_claim in dropped:
        drop_reasons[dropped_claim.drop_reason or "grammar_drop:unknown"] += 1
    classified, _calls = _classify_no_llm(extracted, trace_id=f"w22.{task_id}.struct.classify")
    claims = _verify_no_llm(classified, source_report, task_id=task_id)
    return ArmResult(
        task_id=task_id,
        arm="struct",
        claims=claims,
        dropped=sum(drop_reasons.values()),
        extract_claim_count=len(raw_claims),
        drop_reasons=dict(drop_reasons),
    )


def _classify_no_llm(extracted: list[Any], *, trace_id: str) -> tuple[list[Any], int]:
    import verifier.claim_classifier as classifier

    original = classifier._llm_classify
    try:
        classifier._llm_classify = lambda texts, trace_id: [None] * len(texts)
        classified, _calls = classify_claims(extracted, trace_id=trace_id)
    finally:
        classifier._llm_classify = original
    return classified, 0


def _verify_no_llm(classified: list[Any], source_report: Any, *, task_id: str) -> list[VerifiedClaim]:
    old_judge = os.environ.get("METAGENT_ENABLE_LLM_JUDGE_SUB6")
    old_trace = os.environ.get("METAGENT_TOOL_OUTPUT_TRACE_PATH")
    os.environ["METAGENT_ENABLE_LLM_JUDGE_SUB6"] = "0"
    os.environ.pop("METAGENT_TOOL_OUTPUT_TRACE_PATH", None)
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
        if old_trace is not None:
            os.environ["METAGENT_TOOL_OUTPUT_TRACE_PATH"] = old_trace


def _convert_final_claim(claim: dict[str, Any]) -> dict[str, Any] | None:
    claim_type = claim.get("claim_type")
    if claim_type == "PATHWAY_ENRICHMENT":
        term_id = str(claim.get("pathway_id") or "").strip()
        term_name = str(claim.get("pathway_name") or term_id).strip()
        if not term_id or not term_name:
            return None
        score_type = str(claim.get("score_type") or "").lower()
        out: dict[str, Any] = {
            "grammar": "pathway_enrichment",
            "claim_text": _claim_text(claim, _enrichment_text(claim, term_id, term_name)),
            "term_id": term_id,
            "term_name": term_name,
            "term_type": "pathway",
            "metabolite_set": [],
        }
        if score_type in {"fdr", "q_value", "q-value"}:
            out["fdr"] = claim.get("score")
        elif score_type in {"p_value", "p-value", "p"}:
            out["p_value"] = claim.get("score")
        return out
    if claim_type == "PATHWAY_MEMBERSHIP":
        subject = str(claim.get("compound_name") or claim.get("compound_id") or "").strip()
        pathway_name = str(claim.get("pathway_name") or claim.get("pathway_id") or "").strip()
        if not subject or not pathway_name:
            return None
        return {
            "grammar": "pathway_membership",
            "claim_text": _claim_text(claim, f"{subject} is a member of {pathway_name}."),
            "subject": subject,
            "pathway_name": pathway_name,
        }
    if claim_type == "METABOLITE_PATHWAY_LINK":
        subject = str(claim.get("compound_name") or claim.get("compound_id") or "").strip()
        pathway_name = str(claim.get("pathway_name") or claim.get("pathway_id") or "").strip()
        endpoint = str(claim.get("enzyme_or_reaction") or "").strip()
        if not subject or not pathway_name or not endpoint:
            return None
        return {
            "grammar": "metabolite_pathway_link",
            "claim_text": _claim_text(
                claim,
                f"{subject} participates in {pathway_name} via {endpoint}.",
            ),
            "subject": subject,
            "pathway_name": pathway_name,
            "enzyme_or_reaction": endpoint,
        }
    if claim_type == "DRIVER_METABOLITE":
        subject = str(claim.get("compound_name") or claim.get("compound_id") or "").strip()
        pathway_name = str(claim.get("pathway_name") or claim.get("pathway_id") or "").strip()
        signals = [str(x) for x in (claim.get("signal_compound_ids") or []) if str(x).strip()]
        if not subject or not pathway_name or not signals:
            return None
        return {
            "grammar": "driver_metabolite",
            "claim_text": _claim_text(claim, f"{subject} drives {pathway_name}."),
            "subject": subject,
            "pathway_name": pathway_name,
            "signal_compound_ids": signals,
        }
    return None


def _claim_text(claim: dict[str, Any], fallback: str) -> str:
    text = claim.get("claim_text")
    return str(text).strip() if isinstance(text, str) and text.strip() else fallback


def _enrichment_text(claim: dict[str, Any], term_id: str, term_name: str) -> str:
    method = str(claim.get("evidence_method") or "tool")
    rank = claim.get("rank")
    score = claim.get("score")
    score_type = str(claim.get("score_type") or "score")
    if rank is not None and score is not None:
        return f"{method} ranks {term_id} ({term_name}) at rank {rank} with {score_type} {score:.6g}."
    if rank is not None:
        return f"{method} ranks {term_id} ({term_name}) at rank {rank}."
    return f"{term_name} is enriched in the pathway analysis result."


def _source_report_for(task: dict[str, Any], dump: dict[str, Any]) -> Any:
    final = dump.get("final_react_result") or {}
    carriers = final.get("enrichment_carriers") or {}
    return sub6b_task_to_subsix_source_report({**task, **carriers})


def _read_clean_task_ids() -> list[str]:
    with W18_CLEAN.open() as handle:
        return [json.loads(line)["task_id"] for line in handle if line.strip()]


def _read_tasks(task_ids: list[str]) -> dict[str, dict[str, Any]]:
    wanted = set(task_ids)
    out: dict[str, dict[str, Any]] = {}
    with BENCHMARK.open() as handle:
        for line in handle:
            row = json.loads(line)
            task_id = row.get("task_id")
            if task_id in wanted:
                out[task_id] = row
    missing = sorted(wanted - set(out))
    if missing:
        raise FileNotFoundError(f"benchmark rows missing: {missing[:5]} total={len(missing)}")
    return out


def _read_full_dumps(task_ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for task_id in task_ids:
        for base in W18_FULL_DIRS:
            path = base / f"{task_id}.json"
            if path.exists():
                out[task_id] = json.loads(path.read_text())
                break
    missing = sorted(set(task_ids) - set(out))
    if missing:
        raise FileNotFoundError(f"W18 full dumps missing: {missing[:5]} total={len(missing)}")
    return out


def _claim_rows(result: ArmResult) -> list[dict[str, Any]]:
    rows = []
    for idx, claim in enumerate(result.claims):
        rows.append({
            "task_id": result.task_id,
            "arm": result.arm,
            "claim_index": idx,
            "claim_id": claim.claim_id or "",
            "claim_type": claim.claim_type.value,
            "claim_subtype": claim.claim_subtype.value,
            "verdict": claim.verdict.value,
            "verifier_layer": claim.verifier_layer or "",
            "subject": claim.subject or "",
            "evidence": claim.evidence or "",
            "claim_text": claim.claim_text,
        })
    return rows


def _attribute_task(task_id: str, prose_claims: list[VerifiedClaim], struct_claims: list[VerifiedClaim]) -> list[dict[str, Any]]:
    rows = []
    for prose_idx, prose in enumerate(prose_claims):
        if prose.verdict not in UV:
            continue
        match_idx, match, score = _best_struct_match(prose, struct_claims)
        if match is None or score < 0.28:
            bucket = "UNMAPPABLE"
            matched_verdict = ""
        elif match.verdict == ClaimVerdict.SUPPORTED:
            bucket = "PIPELINE-LOST"
            matched_verdict = match.verdict.value
        elif match.verdict in UV:
            bucket = "REACT-UNGROUNDED"
            matched_verdict = match.verdict.value
        else:
            bucket = "STRUCT-NON-UV-NON-SUPPORTED"
            matched_verdict = match.verdict.value
        rows.append({
            "task_id": task_id,
            "prose_claim_index": prose_idx,
            "prose_verdict": prose.verdict.value,
            "prose_layer": prose.verifier_layer or "",
            "prose_claim_text": prose.claim_text,
            "matched_struct_index": "" if match_idx is None else match_idx,
            "match_score": round(score, 4),
            "matched_struct_verdict": matched_verdict,
            "matched_struct_layer": "" if match is None else (match.verifier_layer or ""),
            "matched_struct_claim_text": "" if match is None else match.claim_text,
            "attribution": bucket,
        })
    return rows


def _best_struct_match(prose: VerifiedClaim, struct_claims: list[VerifiedClaim]) -> tuple[int | None, VerifiedClaim | None, float]:
    best: tuple[int | None, VerifiedClaim | None, float] = (None, None, 0.0)
    prose_text = _norm(prose.claim_text)
    prose_subject = _norm(prose.subject or "")
    prose_path = _norm(getattr(prose.extracted_fields, "pathway_name", None) or "")
    for idx, struct in enumerate(struct_claims):
        text_score = SequenceMatcher(None, prose_text, _norm(struct.claim_text)).ratio()
        subject_score = 0.0
        if prose_subject and _norm(struct.subject or ""):
            subject_score = SequenceMatcher(None, prose_subject, _norm(struct.subject or "")).ratio()
        path_score = 0.0
        struct_path = _norm(getattr(struct.extracted_fields, "pathway_name", None) or "")
        if prose_path and struct_path:
            path_score = SequenceMatcher(None, prose_path, struct_path).ratio()
        score = max(text_score, 0.65 * text_score + 0.25 * subject_score + 0.10 * path_score)
        if score > best[2]:
            best = (idx, struct, score)
    return best


def _norm(value: str) -> str:
    return " ".join((value or "").lower().replace(":", " ").replace("_", " ").split())


def _metrics(results: list[ArmResult], attribution_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, list[ArmResult]] = defaultdict(list)
    for result in results:
        by_arm[result.arm].append(result)

    arm_metrics = {}
    for arm, arm_results in sorted(by_arm.items()):
        claims = [claim for result in arm_results for claim in result.claims]
        cm = compute_claim_metrics(claims, claims)
        verdicts = Counter(claim.verdict.value for claim in claims)
        drop_reasons = Counter()
        for result in arm_results:
            drop_reasons.update(result.drop_reasons or {})
        arm_metrics[arm] = {
            "tasks": len(arm_results),
            "source_claims": sum(r.extract_claim_count for r in arm_results),
            "verified_claims": len(claims),
            "dropped": sum(r.dropped for r in arm_results),
            "verdict_counts": dict(sorted(verdicts.items())),
            "drop_reasons": dict(drop_reasons.most_common()),
            "uv_rate": round((cm.unverifiable_claims + cm.error_claims) / cm.total_claims, 6)
            if cm.total_claims else None,
            "supported_rate": round(cm.supported_claims / cm.total_claims, 6) if cm.total_claims else None,
            "non_uv_rate": round(
                sum(1 for claim in claims if claim.verdict in NON_UV) / cm.total_claims,
                6,
            ) if cm.total_claims else None,
            "claim_metrics": cm.model_dump(mode="json"),
        }

    prose_uv = arm_metrics["prose"]["uv_rate"] or 0.0
    struct_uv = arm_metrics["struct"]["uv_rate"] or 0.0
    attr_counts = Counter(row["attribution"] for row in attribution_rows)
    mapped = len(attribution_rows) - attr_counts["UNMAPPABLE"]
    return {
        "input": {
            "w18_clean_tasks": len(by_arm.get("prose", [])),
            "w18_clean_results": str(W18_CLEAN.relative_to(ROOT)),
            "w18_full_dirs": [str(p.relative_to(ROOT)) for p in W18_FULL_DIRS],
            "deterministic_only": True,
            "llm_or_react_rerun_cost_usd": 0.0,
        },
        "arms": arm_metrics,
        "uv_delta_prose_minus_struct_pp": round((prose_uv - struct_uv) * 100, 2),
        "attribution": {
            "prose_uv_claims": len(attribution_rows),
            "mapped_claims": mapped,
            "mapping_success_rate": round(mapped / len(attribution_rows), 6) if attribution_rows else None,
            "counts": dict(sorted(attr_counts.items())),
            "rates": {
                key: round(value / len(attribution_rows), 6) if attribution_rows else None
                for key, value in sorted(attr_counts.items())
            },
        },
        "method_notes": [
            "Arm-Prose uses existing rule-based sentence extraction plus deterministic Sub-6 verifier layers; LLM extraction/classification/consistency are disabled.",
            "Arm-Struct converts saved W18 final_claims[] to the existing grammar-v2 JSON extractor path, then uses the same deterministic Sub-6 verifier layers.",
            "The two arms do not produce identical claim sets, so UV-rate gap is primary and per-claim attribution is best-effort auxiliary evidence.",
        ],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(metrics: dict[str, Any]) -> None:
    prose = metrics["arms"]["prose"]
    struct = metrics["arms"]["struct"]
    attr = metrics["attribution"]
    lines = [
        "# W22 D1 UV Attribution Offline Summary",
        "",
        "## Scope",
        "",
        "- Input: W18 clean 59-task saved dumps.",
        "- Cost: $0. No ReAct rerun and no LLM calls.",
        "- Verifier changes: none. This script calls existing verifier helpers only.",
        "",
        "## Two-arm Metrics",
        "",
        "| arm | tasks | source claims | verified claims | dropped | supported | contradicted | unsupported | UV+error | UV rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, arm in (("prose", prose), ("struct", struct)):
        counts = arm["verdict_counts"]
        uv_count = counts.get("unverifiable_v0", 0) + counts.get("error", 0)
        lines.append(
            f"| {name} | {arm['tasks']} | {arm['source_claims']} | {arm['verified_claims']} | "
            f"{arm['dropped']} | {counts.get('supported', 0)} | {counts.get('contradicted', 0)} | "
            f"{counts.get('unsupported', 0)} | {uv_count} | {arm['uv_rate']:.2%} |"
        )
    lines += [
        "",
        f"- UV delta (Arm-Prose minus Arm-Struct): {metrics['uv_delta_prose_minus_struct_pp']:.2f} pp",
        "",
        "## Per-claim Attribution",
        "",
        f"- Prose UV claims attributed: {attr['prose_uv_claims']}",
        f"- Mapping success rate: {attr['mapping_success_rate']:.2%}" if attr["mapping_success_rate"] is not None else "- Mapping success rate: n/a",
    ]
    for key, value in attr["counts"].items():
        rate = attr["rates"][key]
        lines.append(f"- {key}: {value} ({rate:.2%})")
    if struct.get("drop_reasons"):
        lines += ["", "## Struct Drop Reasons", ""]
        for reason, count in struct["drop_reasons"].items():
            lines.append(f"- {count}: {reason}")
    lines += [
        "",
        "## Interpretation Guardrails",
        "",
        "- Structured claims[] and prose re-extraction are different claim sets, so the UV-rate gap is the primary signal.",
        "- Per-claim mapping is best-effort by text/subject/pathway similarity; high UNMAPPABLE is itself evidence of lossy translation.",
        "- A populated structured field was not counted as support unless the existing deterministic verifier produced a non-UV verdict.",
    ]
    (OUT_DIR / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
