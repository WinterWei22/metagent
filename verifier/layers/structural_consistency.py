"""Layer 2D — structural consistency fallback for SET_ENRICHMENT claims.

Triggered when ``verify_set_enrichment`` returns UNVERIFIABLE_V0.  An LLM
judge asks: "are these metabolites' chemical structures consistent with the
claimed pathway?"

Verdict logic (mirrors llm_judge_sub6 thresholds):
  SUPPORTED          — LLM returns SUPPORTED with confidence >= 0.85
  NEEDS_HUMAN_REVIEW — confidence in [0.50, 0.85), or LLM returns HEDGED
  UNVERIFIABLE_V0    — LLM returns UV, confidence < 0.50, parse failure,
                       cost cap exceeded, or insufficient SMILES data

This layer never emits CONTRADICTED — structural reasoning from SMILES alone
is insufficient for a definitive contradiction verdict.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from verifier.helpers.judge_cost_cap import JudgeCostTracker
from verifier.helpers.judge_response_parser import parse_judge_response
from verifier.helpers.judge_trace import write_judge_trace
from verifier.helpers.structural_prompt import (
    STRUCTURAL_CONSISTENCY_SYSTEM_PROMPT,
    build_structural_consistency_prompt,
    extract_metabolites_with_smiles,
    extract_pathway_from_claim,
)
from verifier.schemas import ClaimSubtype, ClaimType, ClaimVerdict, VerifiedClaim

LAYER_NAME = "structural_consistency"
ESTIMATED_CALL_COST_USD = 0.0030
JUDGE_CONFIDENCE_THRESHOLD = 0.85
MIN_METABOLITES_WITH_SMILES = 1

JudgeCall = Callable[..., Any]


def verify_structural_consistency(
    claim: Any,
    source_report: Any,
    judge_call: JudgeCall | None = None,
    cost_tracker: JudgeCostTracker | None = None,
    trace_path: str | Path | None = None,
    iteration: int | None = None,
) -> VerifiedClaim:
    """Verify a SET_ENRICHMENT claim by structural consistency.

    Returns SUPPORTED / NEEDS_HUMAN_REVIEW / UNVERIFIABLE_V0.
    """
    if _get_claim_type(claim) != ClaimType.SET_ENRICHMENT:
        return _uv(claim, "structural_consistency only applies to SET_ENRICHMENT claims")

    pathway_name = extract_pathway_from_claim(claim)
    if not pathway_name:
        return _uv(claim, "no pathway name or ID could be extracted from claim")

    metabolites = extract_metabolites_with_smiles(source_report)
    if len(metabolites) < MIN_METABOLITES_WITH_SMILES:
        return _uv(
            claim,
            "fewer than the minimum number of metabolites have usable SMILES; "
            "structural consistency check not possible",
        )

    if cost_tracker and not cost_tracker.can_call(ESTIMATED_CALL_COST_USD):
        return _uv(claim, "LLM judge cost cap exceeded")

    call = judge_call or _default_judge_call
    raw_response = call(claim=claim, source_report=source_report)

    if cost_tracker:
        cost_tracker.record(ESTIMATED_CALL_COST_USD)

    parsed = parse_judge_response(raw_response)

    _write_trace(
        claim=claim,
        source_report=source_report,
        parsed=parsed,
        trace_path=trace_path,
        iteration=iteration,
    )

    if parsed.confidence < 0.50 or parsed.verdict == ClaimVerdict.UNVERIFIABLE_V0:
        return _uv(claim, parsed.rationale or "low confidence or UV from judge")

    if parsed.confidence < JUDGE_CONFIDENCE_THRESHOLD:
        return _verified(
            claim,
            ClaimVerdict.NEEDS_HUMAN_REVIEW,
            parsed.rationale,
            feedback_hint=parsed.rationale,
            source_field=parsed.evidence_pointer,
        )

    if parsed.verdict == ClaimVerdict.NEEDS_HUMAN_REVIEW:
        return _verified(
            claim,
            ClaimVerdict.NEEDS_HUMAN_REVIEW,
            parsed.rationale,
            feedback_hint=parsed.rationale,
            source_field=parsed.evidence_pointer,
        )

    if parsed.verdict == ClaimVerdict.SUPPORTED:
        return _verified(
            claim,
            ClaimVerdict.SUPPORTED,
            parsed.rationale,
            source_field=parsed.evidence_pointer,
        )

    # UNSUPPORTED / CONTRADICTED with high confidence → UV (no definitive
    # contradiction from SMILES alone)
    return _uv(claim, parsed.rationale or "structural judge returned non-SUPPORTED verdict")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _default_judge_call(*, claim: Any, source_report: Any) -> str:
    from common.llm_client import chat

    pathway_name = extract_pathway_from_claim(claim)
    metabolites = extract_metabolites_with_smiles(source_report)
    prompt = build_structural_consistency_prompt(
        claim_text=_get_text(claim),
        pathway_name=pathway_name or "(unknown)",
        metabolites=metabolites,
    )
    return chat(
        [
            {"role": "system", "content": STRUCTURAL_CONSISTENCY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=800,
        trace_id="v3.structural_consistency",
        caller="verifier.structural_consistency",
        response_format={"type": "json_object"},
    )


def _get_claim_type(claim: Any) -> ClaimType:
    val = _field(claim, "claim_type")
    if isinstance(val, ClaimType):
        return val
    try:
        return ClaimType(val)
    except (ValueError, TypeError):
        return ClaimType.OTHER


def _get_text(claim: Any) -> str:
    return str(_field(claim, "claim_text") or "")


def _field(claim: Any, name: str) -> Any:
    if isinstance(claim, dict):
        return claim.get(name)
    return getattr(claim, name, None)


def _source_task_id(source_report: Any) -> str | None:
    if isinstance(source_report, dict):
        val = source_report.get("task_id")
    else:
        val = getattr(source_report, "task_id", None)
    return str(val) if val is not None else None


def _write_trace(
    *,
    claim: Any,
    source_report: Any,
    parsed: Any,
    trace_path: str | Path | None,
    iteration: int | None,
) -> None:
    verdict_label = parsed.verdict.name if hasattr(parsed.verdict, "name") else str(parsed.verdict)
    write_judge_trace(
        path=trace_path,
        task_id=_source_task_id(source_report),
        iteration=iteration,
        claim_id=_field(claim, "claim_id"),
        claim_type=_get_claim_type(claim),
        verdict=verdict_label,
        parser_success=not (
            parsed.verdict == ClaimVerdict.UNVERIFIABLE_V0
            and parsed.confidence == 0.0
            and parsed.evidence_pointer == ""
        ),
        cost_usd=ESTIMATED_CALL_COST_USD,
        confidence=parsed.confidence,
    )


def _uv(claim: Any, evidence: str) -> VerifiedClaim:
    return _verified(claim, ClaimVerdict.UNVERIFIABLE_V0, evidence)


def _verified(
    claim: Any,
    verdict: ClaimVerdict,
    evidence: str,
    *,
    feedback_hint: str | None = None,
    source_field: str | None = None,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=_field(claim, "claim_id"),
        claim_text=_get_text(claim),
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=_field(claim, "subject"),
        subject_kind=_field(claim, "subject_kind"),
        candidate_ref=_field(claim, "candidate_ref"),
        verdict=verdict,
        evidence=evidence or verdict.value,
        source_field=source_field,
        verifier_layer=LAYER_NAME,
        feedback_hint=feedback_hint,
        trace_summary=f"{LAYER_NAME}:{verdict.value}",
        extracted_fields=_field(claim, "extracted_fields"),
    )
