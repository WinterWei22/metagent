from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from verifier.helpers.contradicted_validator import validate_contradicted_pointer
from verifier.helpers.judge_cost_cap import JudgeCostTracker
from verifier.helpers.judge_response_parser import parse_judge_response
from verifier.helpers.judge_trace import write_judge_trace
from verifier.helpers.llm_judge_prompt import build_llm_judge_prompt, build_source_report_excerpt
from verifier.schemas import ClaimType, ClaimVerdict, VerifiedClaim


JUDGE_ELIGIBLE_TYPES = {
    ClaimType.GROUNDED,
    ClaimType.BIOLOGICAL,
    ClaimType.FACTUAL,
}
JUDGE_CONFIDENCE_THRESHOLD = 0.85
CONTRADICTED_CONFIDENCE_THRESHOLD = 0.90
SIGNAL_SUB6_CATCH_ALL_ENABLED = False
LAYER_NAME = "llm_judge_sub6"
ESTIMATED_JUDGE_CALL_COST_USD = 0.0021

JudgeCall = Callable[..., Any]


def verify_llm_judge_sub6(
    claim: Any,
    source_report: Any,
    judge_call: JudgeCall | None = None,
    cost_tracker: JudgeCostTracker | None = None,
    trace_path: str | Path | None = None,
    iteration: int | None = None,
) -> VerifiedClaim:
    claim_type = _claim_type_of(claim)
    if claim_type not in JUDGE_ELIGIBLE_TYPES:
        return _verified(claim, ClaimVerdict.UNVERIFIABLE_V0, "claim type is not LLM-judge eligible")
    if cost_tracker and not cost_tracker.can_call():
        return _verified(claim, ClaimVerdict.UNVERIFIABLE_V0, "LLM-judge cost cap exceeded")
    call = judge_call or _default_judge_call
    parsed = parse_judge_response(call(claim=claim, source_report=source_report))
    if cost_tracker:
        cost_tracker.record(ESTIMATED_JUDGE_CALL_COST_USD)
    _write_trace(
        claim=claim,
        source_report=source_report,
        parsed=parsed,
        trace_path=trace_path,
        iteration=iteration,
    )
    if parsed.confidence < 0.50 or parsed.verdict == ClaimVerdict.UNVERIFIABLE_V0:
        return _verified(claim, ClaimVerdict.UNVERIFIABLE_V0, parsed.rationale)
    if parsed.confidence < JUDGE_CONFIDENCE_THRESHOLD:
        return _verified(
            claim,
            ClaimVerdict.NEEDS_HUMAN_REVIEW,
            parsed.rationale,
            feedback_hint=parsed.rationale,
            source_field=parsed.evidence_pointer,
        )
    if parsed.verdict == ClaimVerdict.CONTRADICTED:
        if parsed.confidence < CONTRADICTED_CONFIDENCE_THRESHOLD or not validate_contradicted_pointer(
            source_report, parsed.evidence_pointer, parsed.rationale,
        ):
            return _verified(
                claim,
                ClaimVerdict.NEEDS_HUMAN_REVIEW,
                parsed.rationale,
                feedback_hint=parsed.rationale,
                source_field=parsed.evidence_pointer,
            )
        return _verified(claim, ClaimVerdict.CONTRADICTED, parsed.rationale, source_field=parsed.evidence_pointer)
    return _verified(claim, parsed.verdict, parsed.rationale, source_field=parsed.evidence_pointer)


def verify_post_uv_only(
    prior_verdict: ClaimVerdict,
    claim: Any,
    source_report: Any,
    judge_call: JudgeCall,
    cost_tracker: JudgeCostTracker | None = None,
) -> VerifiedClaim:
    if prior_verdict != ClaimVerdict.UNVERIFIABLE_V0:
        return _verified(claim, prior_verdict, "prior layer already produced a verdict")
    return verify_llm_judge_sub6(claim, source_report, judge_call, cost_tracker=cost_tracker)


def sub6_dispatch_order_for(claim_type: ClaimType) -> list[str]:
    if claim_type in (ClaimType.FACTUAL, ClaimType.GROUNDED):
        return ["factual_sub6", LAYER_NAME]
    if claim_type == ClaimType.BIOLOGICAL:
        return ["biological_sub6", LAYER_NAME]
    return [LAYER_NAME]


def quality_score_for_verdict(verdict: ClaimVerdict) -> float:
    if verdict == ClaimVerdict.SUPPORTED:
        return 1.0
    if verdict == ClaimVerdict.NEEDS_HUMAN_REVIEW:
        return 0.6
    return 0.0


def _default_judge_call(*, claim: Any, source_report: Any) -> str:
    from common.llm_client import chat

    prompt = build_llm_judge_prompt(
        claim_text=_claim_text_of(claim),
        claim_type=_claim_type_of(claim),
        source_report_excerpt=build_source_report_excerpt(source_report),
    )
    return chat(
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=1000,
        trace_id="w18.llm_judge_sub6",
        caller="verifier.llm_judge_sub6",
        response_format={"type": "json_object"},
    )


def _claim_type_of(claim: Any) -> ClaimType:
    value = _claim_value(claim, "claim_type")
    if isinstance(value, ClaimType):
        return value
    return ClaimType(value)


def _claim_text_of(claim: Any) -> str:
    return str(_claim_value(claim, "claim_text") or "")


def _claim_value(claim: Any, name: str) -> Any:
    if isinstance(claim, dict):
        return claim.get(name)
    return getattr(claim, name, None)


def _source_value(source_report: Any, name: str) -> Any:
    if isinstance(source_report, dict):
        return source_report.get(name)
    return getattr(source_report, name, None)


def _write_trace(
    *,
    claim: Any,
    source_report: Any,
    parsed: Any,
    trace_path: str | Path | None,
    iteration: int | None,
) -> None:
    write_judge_trace(
        path=trace_path,
        task_id=_source_value(source_report, "task_id"),
        iteration=iteration,
        claim_id=_claim_value(claim, "claim_id"),
        claim_type=_claim_type_of(claim),
        verdict=_trace_verdict_label(parsed.verdict),
        parser_success=not (
            parsed.verdict == ClaimVerdict.UNVERIFIABLE_V0
            and parsed.confidence == 0.0
            and parsed.evidence_pointer == ""
        ),
        cost_usd=ESTIMATED_JUDGE_CALL_COST_USD,
        confidence=parsed.confidence,
    )


def _trace_verdict_label(verdict: ClaimVerdict) -> str:
    if verdict == ClaimVerdict.UNVERIFIABLE_V0:
        return "UV"
    if verdict == ClaimVerdict.NEEDS_HUMAN_REVIEW:
        return "HEDGED"
    return verdict.name


def _verified(
    claim: Any,
    verdict: ClaimVerdict,
    evidence: str,
    *,
    feedback_hint: str | None = None,
    source_field: str | None = None,
) -> VerifiedClaim:
    claim_type = _claim_type_of(claim)
    return VerifiedClaim(
        claim_id=_claim_value(claim, "claim_id"),
        claim_text=_claim_text_of(claim),
        claim_type=claim_type,
        verdict=verdict,
        evidence=evidence or verdict.value,
        source_field=source_field,
        verifier_layer=LAYER_NAME,
        feedback_hint=feedback_hint,
        trace_summary=f"{LAYER_NAME}:{verdict.value}",
    )


__all__ = [
    "CONTRADICTED_CONFIDENCE_THRESHOLD",
    "ESTIMATED_JUDGE_CALL_COST_USD",
    "JUDGE_CONFIDENCE_THRESHOLD",
    "JUDGE_ELIGIBLE_TYPES",
    "JudgeCostTracker",
    "SIGNAL_SUB6_CATCH_ALL_ENABLED",
    "quality_score_for_verdict",
    "sub6_dispatch_order_for",
    "verify_llm_judge_sub6",
    "verify_post_uv_only",
]
