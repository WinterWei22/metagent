"""Layer 6a — verify Type ``SET_ENRICHMENT`` claims.

A SET_ENRICHMENT claim asserts that a group of metabolites is enriched in
some pathway (e.g. "These metabolites are enriched in Tyrosine metabolism").
Verification compares the claimed pathway against
``SubsixSourceReport.ramp_enrichment_result.top_pathways`` per the rules
in ``reports/benchmark/sub6_evaluation_guide.md`` §3 pitfall 3 and §4.

Verdict policy (concretised from the brief):

* Match in ``top_pathways[:3]``  → ``SUPPORTED``
* Match in ``top_pathways[3:10]`` → ``UNSUPPORTED`` (weak evidence)
* No match in ``top_pathways[:10]`` → ``CONTRADICTED``
* Pathway phrase / ID could not be lifted from the claim → ``UNVERIFIABLE_V0``
* ``ramp_enrichment_result`` missing or empty → ``UNVERIFIABLE_V0``

Pathway matching:

1. Pathway IDs (e.g. ``map00350``, ``RAMP_P_000000106``, ``WP430``) are
   matched first, exact-equal on ``pathway_id`` / ``pathway_external_id``.
2. Pathway names fall back to substring fuzzy match (claim ⊂ canonical
   OR canonical ⊂ claim, both lowercased + whitespace-collapsed). This is
   the same convention as Layer C and the eval guide §3 pitfall 3.
"""
from __future__ import annotations

import re
from typing import Any

from schemas.sub6_report import SubsixSourceReport
from verifier.schemas import (
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    EnrichmentContext,
    PathwayMatch,
    VerifiedClaim,
)


_TOP_K_SUPPORTED = 3
_TOP_K_TOLERATED = 10

# RaMP pathway IDs look like RAMP_P_000000106; KEGG mapXXXXX; WikiPathways
# WPNNNN; Reactome R-HSA-NNNN; SMPDB SMPNNNN. Be generous — we just need
# to spot one to short-circuit the fuzzy phrase path.
_PATHWAY_ID_RE = re.compile(
    r"\b("
    r"RAMP_P_\d+"
    r"|map\d{5}"
    r"|hsa\d{5}"
    r"|R-HSA-\d+"
    r"|SMP\d+"
    r"|WP\d+"
    r")\b",
    re.IGNORECASE,
)

# Re-uses the phrase regex from Layer C with the addition of a few extra
# enrichment idioms we expect from Sub-6 narratives.
_PATHWAY_PHRASE_RE = re.compile(
    r"\b("
    r"[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,5}\s+"
    r"(?:metabolism|biosynthesis|degradation|catabolism|anabolism|"
    r"synthesis|disease|syndrome|cycle|oxidations?|signal[l]?ing|"
    r"transduction|disorder|inhibition|production|pathways?)"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def verify_set_enrichment(
    claim: ClassifiedClaim,
    source_report: SubsixSourceReport,
) -> VerifiedClaim:
    """Verify one SET_ENRICHMENT claim against the task's enrichment result."""
    top_pathways = _extract_top_pathways(source_report)
    if not top_pathways:
        return _unverifiable(
            claim,
            evidence=(
                "ramp_enrichment_result.top_pathways is empty or missing; "
                "no enrichment ground truth to compare against."
            ),
            ctx=EnrichmentContext(),
        )

    # Echo top-3 into context regardless of match outcome — auditors want
    # to see what was being compared against.
    matched_top = [
        _pathway_match_from_dict(p, rank=i + 1)
        for i, p in enumerate(top_pathways[:_TOP_K_SUPPORTED])
    ]

    pathway_id, pathway_name = _extract_pathway_from_claim(claim)

    # ID match wins.
    if pathway_id:
        for i, p in enumerate(top_pathways[:_TOP_K_TOLERATED]):
            if _id_match(pathway_id, p):
                return _verdict_for_rank(
                    claim,
                    matched=p,
                    rank=i + 1,
                    method="id",
                    matched_top=matched_top,
                    pathway_id=pathway_id,
                    pathway_name=pathway_name,
                )

    # Forward fuzzy match: the regex-lifted phrase against canonical names.
    if pathway_name:
        norm_claim = _normalise(pathway_name)
        for i, p in enumerate(top_pathways[:_TOP_K_TOLERATED]):
            canon = _normalise(p.get("pathway_name") or "")
            if not canon:
                continue
            if canon == norm_claim:
                return _verdict_for_rank(
                    claim,
                    matched=p,
                    rank=i + 1,
                    method="exact",
                    matched_top=matched_top,
                    pathway_id=pathway_id,
                    pathway_name=pathway_name,
                )
            if norm_claim in canon or canon in norm_claim:
                return _verdict_for_rank(
                    claim,
                    matched=p,
                    rank=i + 1,
                    method="substring_either",
                    matched_top=matched_top,
                    pathway_id=pathway_id,
                    pathway_name=pathway_name,
                )

    # Reverse fuzzy match: canonical name appears verbatim in claim text.
    # Catches naked pathway names that the phrase regex misses
    # (e.g. "Alkaptonuria", "Phenylketonuria") by trusting that the
    # ground-truth top_pathways entries are themselves a closed
    # vocabulary for this task.
    norm_text = _normalise(claim.claim_text)
    for i, p in enumerate(top_pathways[:_TOP_K_TOLERATED]):
        canon = _normalise(p.get("pathway_name") or "")
        if not canon or len(canon) < 5:
            # Skip very short canonical names — too risky for substring fuzz
            # (e.g. a 3-letter pathway name would match almost any claim).
            continue
        if canon in norm_text:
            return _verdict_for_rank(
                claim,
                matched=p,
                rank=i + 1,
                method="substring_either",
                matched_top=matched_top,
                pathway_id=pathway_id,
                pathway_name=pathway_name or p.get("pathway_name"),
            )

    if not pathway_id and not pathway_name:
        return _unverifiable(
            claim,
            evidence=(
                "Layer 6a found no pathway ID or name in the claim, and no "
                "top_pathways canonical name appears verbatim in the claim "
                "text. Cannot map to a verdict."
            ),
            ctx=EnrichmentContext(matched_top_pathways=matched_top),
        )

    # No match in top-10 → CONTRADICTED.
    canonical_top1 = top_pathways[0].get("pathway_name")
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=claim.claim_subtype if claim.claim_subtype != ClaimSubtype.UNKNOWN else ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.CONTRADICTED,
        evidence=(
            f"Claimed pathway {(pathway_name or pathway_id)!r} is not in "
            f"top_pathways[:{_TOP_K_TOLERATED}]; ground-truth top-1 is "
            f"{canonical_top1!r}."
        ),
        correction=canonical_top1,
        extracted_fields=claim.extracted_fields,
        verifier_layer="set_enrichment",
        tool_called="ramp_enrichment_result",
        trace_summary=(
            f"claim pathway {(pathway_name or pathway_id)!r} absent from top-{_TOP_K_TOLERATED}"
        ),
        enrichment_context=EnrichmentContext(
            claimed_pathway=pathway_name,
            claimed_pathway_id=pathway_id,
            matched_top_pathways=matched_top,
            best_match=None,
            pathway_match_method="none",
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_top_pathways(report: SubsixSourceReport) -> list[dict[str, Any]]:
    result = report.ramp_enrichment_result or {}
    top = result.get("top_pathways") or []
    return [p for p in top if isinstance(p, dict)]


def _extract_pathway_from_claim(
    claim: ClassifiedClaim,
) -> tuple[str | None, str | None]:
    """Return (pathway_id, pathway_name) lifted from typed fields or text.

    Typed fields win when populated by the extractor. Otherwise we regex
    over the claim text.
    """
    typed_id = claim.extracted_fields.pathway_id
    typed_name = claim.extracted_fields.pathway_name

    pathway_id = typed_id or None
    pathway_name = typed_name or None

    if not pathway_id:
        m = _PATHWAY_ID_RE.search(claim.claim_text)
        if m:
            pathway_id = m.group(1)

    if not pathway_name:
        m = _PATHWAY_PHRASE_RE.search(claim.claim_text)
        if m:
            pathway_name = m.group(0).strip()

    return pathway_id, pathway_name


def _normalise(s: str) -> str:
    return " ".join((s or "").lower().split())


def _id_match(claimed: str, p: dict[str, Any]) -> bool:
    cl = (claimed or "").strip().lower()
    if not cl:
        return False
    for key in ("pathway_id", "pathway_external_id"):
        v = (p.get(key) or "").strip().lower()
        if v and v == cl:
            return True
    return False


def _pathway_match_from_dict(p: dict[str, Any], rank: int) -> PathwayMatch:
    return PathwayMatch(
        pathway_id=p.get("pathway_id"),
        pathway_name=p.get("pathway_name"),
        pathway_source=p.get("pathway_source"),
        pathway_external_id=p.get("pathway_external_id"),
        rank=rank,
        fdr=p.get("fdr"),
        p_value=p.get("p_value"),
        fold_enrichment=p.get("fold_enrichment"),
        matched_compounds=list(p.get("matched_compounds") or []),
        total_pathway_compounds=p.get("total_pathway_compounds"),
    )


def _verdict_for_rank(
    claim: ClassifiedClaim,
    *,
    matched: dict[str, Any],
    rank: int,
    method: str,
    matched_top: list[PathwayMatch],
    pathway_id: str | None,
    pathway_name: str | None,
) -> VerifiedClaim:
    best = _pathway_match_from_dict(matched, rank=rank)
    ctx = EnrichmentContext(
        claimed_pathway=pathway_name,
        claimed_pathway_id=pathway_id,
        matched_top_pathways=matched_top,
        best_match=best,
        pathway_match_method=method,  # type: ignore[arg-type]
    )

    # SUPPORTED vs UNSUPPORTED based on rank.
    if rank <= _TOP_K_SUPPORTED:
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=ClaimType.SET_ENRICHMENT,
            claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.SUPPORTED,
            evidence=(
                f"Claimed pathway matches top_pathways[{rank - 1}] "
                f"({matched.get('pathway_name')!r}) by {method}; "
                f"FDR={matched.get('fdr')}."
            ),
            extracted_fields=claim.extracted_fields,
            verifier_layer="set_enrichment",
            tool_called="ramp_enrichment_result",
            trace_summary=f"top-{rank} match via {method}",
            enrichment_context=ctx,
        )

    # rank in 4..10 → UNSUPPORTED (weak evidence)
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNSUPPORTED,
        evidence=(
            f"Claimed pathway matches top_pathways[{rank - 1}] but rank "
            f"{rank} is outside the top-{_TOP_K_SUPPORTED} acceptance set "
            f"used by Sub-6 grading. Match method: {method}."
        ),
        extracted_fields=claim.extracted_fields,
        verifier_layer="set_enrichment",
        tool_called="ramp_enrichment_result",
        trace_summary=f"top-{rank} match (outside top-{_TOP_K_SUPPORTED})",
        enrichment_context=ctx,
    )


def _unverifiable(
    claim: ClassifiedClaim,
    *,
    evidence: str,
    ctx: EnrichmentContext,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence=evidence,
        extracted_fields=claim.extracted_fields,
        verifier_layer="set_enrichment",
        trace_summary="set_enrichment unverifiable",
        enrichment_context=ctx,
    )
