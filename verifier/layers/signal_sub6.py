"""Layer signal_sub6 - verify numeric enrichment-signal claims on Sub-6 tasks."""
from __future__ import annotations

from schemas.sub6_report import SubsixSourceReport
from verifier.helpers.enrichment_lookup import LookupResult, lookup_signal_evidence
from verifier.helpers.signal_extractor import SignalMention, extract_signal_mentions
from verifier.schemas import ClaimVerdict, ClassifiedClaim, EnrichmentContext, VerifiedClaim


def verify_signal_sub6(
    claim: ClassifiedClaim,
    source_report: SubsixSourceReport,
) -> VerifiedClaim:
    mentions = extract_signal_mentions(claim.claim_text)
    if not mentions:
        return _uv(claim, "Layer signal_sub6: no concrete signal metric could be extracted.")

    misses: list[SignalMention] = []
    for mention in mentions:
        lookup = lookup_signal_evidence(mention, source_report)
        if lookup is None:
            misses.append(mention)
            continue
        if lookup.matched:
            return _supported(claim, mention, lookup)
        return _contradicted(claim, mention, lookup)

    return _uv(
        claim,
        "Layer signal_sub6: extracted signal metric(s), but no matching enrichment result row was found.",
    )


def _supported(claim: ClassifiedClaim, mention: SignalMention, lookup: LookupResult) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.SUPPORTED,
        evidence=(
            f"ramp_enrichment_result: {lookup.pathway_name!r} has "
            f"{lookup.metric}={lookup.actual_value:g}, matching claim value {mention.value:g}."
        ),
        extracted_fields=claim.extracted_fields,
        verifier_layer="signal_sub6",
        tool_called="ramp_enrichment_result",
        trace_summary=f"signal_sub6 {lookup.metric} {lookup.match_type}",
        enrichment_context=_context(mention, lookup),
    )


def _contradicted(claim: ClassifiedClaim, mention: SignalMention, lookup: LookupResult) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.CONTRADICTED,
        evidence=(
            f"ramp_enrichment_result: {lookup.pathway_name!r} has "
            f"{lookup.metric}={lookup.actual_value:g}; claim says {mention.value:g}."
        ),
        correction=f"{lookup.actual_value:g}",
        extracted_fields=claim.extracted_fields,
        verifier_layer="signal_sub6",
        tool_called="ramp_enrichment_result",
        trace_summary=f"signal_sub6 {lookup.metric} mismatch",
        enrichment_context=_context(mention, lookup),
    )


def _uv(claim: ClassifiedClaim, evidence: str) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence=evidence,
        extracted_fields=claim.extracted_fields,
        verifier_layer="signal_sub6",
        trace_summary="signal_sub6 unverifiable",
    )


def _context(mention: SignalMention, lookup: LookupResult) -> EnrichmentContext:
    return EnrichmentContext(
        claimed_pathway=mention.pathway_hint,
        claimed_pathway_id=None,
        pathway_match_method="exact" if mention.pathway_hint else None,
        tool_evidence={
            "metric": lookup.metric,
            "claimed_value": mention.value,
            "actual_value": lookup.actual_value,
            "claimed_total": mention.total,
            "actual_total": lookup.actual_total,
            "operator": mention.operator,
            "match_type": lookup.match_type,
            "pathway_rank": lookup.pathway_rank,
        },
    )
