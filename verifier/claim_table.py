"""Build flattened claim tables from verifier claims."""
from __future__ import annotations

from typing import Literal

from verifier.schemas import (
    ClaimType,
    ClaimVerdict,
    VerifiedClaim,
    VerifiedClaimRow,
    VerifiedClaimTable,
)


_LAYER_BY_TYPE = {
    ClaimType.GROUNDED: "grounded",
    ClaimType.FACTUAL: "factual",
    ClaimType.BIOLOGICAL: "biological",
    ClaimType.CONSISTENCY: "consistency",
    ClaimType.LITERATURE: "literature",
    ClaimType.PEAK_MECHANISTIC: "peak_mechanistic",
}

_TOOL_BY_TYPE = {
    ClaimType.FACTUAL: "fetch_metabolite_info_or_classyfire",
    ClaimType.LITERATURE: "literature_search",
    ClaimType.PEAK_MECHANISTIC: "sirius",
    ClaimType.CONSISTENCY: "llm_consistency",
}

_SEVERITY_BY_VERDICT = {
    ClaimVerdict.SUPPORTED: "info",
    ClaimVerdict.UNVERIFIABLE_V0: "minor",
    ClaimVerdict.NEEDS_HUMAN_REVIEW: "minor",
    ClaimVerdict.INSUFFICIENT_EVIDENCE: "minor",
    ClaimVerdict.UNSUPPORTED: "major",
    ClaimVerdict.CONTRADICTED: "critical",
    ClaimVerdict.ERROR: "major",
}


def build_claim_table(
    claims: list[VerifiedClaim],
    pass_id: Literal["v1", "v2"],
) -> VerifiedClaimTable:
    """Return a UI/metrics-friendly table for one verifier pass."""
    rows: list[VerifiedClaimRow] = []
    for i, claim in enumerate(claims):
        claim_id = claim.claim_id or f"{pass_id}:c{i:03d}"
        severity = claim.severity or _SEVERITY_BY_VERDICT[claim.verdict]
        verifier_layer = claim.verifier_layer or _LAYER_BY_TYPE.get(claim.claim_type)
        tool_called = claim.tool_called or _TOOL_BY_TYPE.get(claim.claim_type)
        rows.append(
            VerifiedClaimRow(
                claim_id=claim_id,
                claim_text=claim.claim_text,
                claim_type=claim.claim_type,
                claim_subtype=claim.claim_subtype,
                subject=claim.subject,
                candidate_ref=claim.candidate_ref,
                verdict=claim.verdict,
                evidence_summary=claim.evidence,
                source_field=claim.source_field,
                correction=claim.correction,
                verifier_layer=verifier_layer,
                tool_called=tool_called,
                trace_summary=claim.trace_summary or claim.evidence,
                severity=severity,
                claim_group_id=claim.claim_group_id,
                parent_claim_id=claim.parent_claim_id,
                extracted_fields=claim.extracted_fields,
                evidence_refs=claim.evidence_refs,
            )
        )
    return VerifiedClaimTable(pass_id=pass_id, rows=rows)
