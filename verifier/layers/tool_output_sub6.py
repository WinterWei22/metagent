from __future__ import annotations

from typing import Any

from verifier.helpers.tool_output_lookup import ToolOutputEvidence, lookup_tool_output_evidence
from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim, VerifiedClaim


LAYER_NAME = "tool_output_sub6"
TOOL_OUTPUT_ELIGIBLE_TYPES = {ClaimType.GROUNDED, ClaimType.FACTUAL, ClaimType.BIOLOGICAL, ClaimType.SET_ENRICHMENT}


def verify_tool_output_sub6(claim: ClassifiedClaim, source_report: Any, **_: Any) -> VerifiedClaim:
    if claim.claim_type not in TOOL_OUTPUT_ELIGIBLE_TYPES:
        return _verified(claim, ClaimVerdict.UNVERIFIABLE_V0, "claim type is not tool-output eligible")
    evidence = lookup_tool_output_evidence(claim.claim_text, source_report)
    if evidence.status == "match":
        return _verified(claim, ClaimVerdict.SUPPORTED, _evidence_text(evidence), source_field=evidence.source_field)
    if evidence.status == "mismatch":
        return _verified(
            claim,
            ClaimVerdict.CONTRADICTED,
            _evidence_text(evidence),
            source_field=evidence.source_field,
            correction=_format_observed(evidence.observed),
        )
    return _verified(claim, ClaimVerdict.UNVERIFIABLE_V0, f"tool-output evidence {evidence.status}")


def verify_post_uv_only(prior_verdict: ClaimVerdict, claim: ClassifiedClaim, source_report: Any) -> VerifiedClaim:
    if prior_verdict != ClaimVerdict.UNVERIFIABLE_V0:
        return _verified(claim, prior_verdict, "prior layer already produced a verdict")
    return verify_tool_output_sub6(claim, source_report)


def _verified(
    claim: ClassifiedClaim,
    verdict: ClaimVerdict,
    evidence: str,
    *,
    source_field: str | None = None,
    correction: str | None = None,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=verdict,
        evidence=evidence,
        source_field=source_field,
        correction=correction,
        extracted_fields=claim.extracted_fields,
        verifier_layer=LAYER_NAME,
        trace_summary=f"{LAYER_NAME}:{verdict.value}",
    )


def _evidence_text(evidence: ToolOutputEvidence) -> str:
    return f"{evidence.method} {evidence.metric}: claim={evidence.claimed}; carrier={evidence.observed}"


def _format_observed(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
