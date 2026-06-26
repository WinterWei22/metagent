"""RED/GREEN tests for Fix 2: _eval_pathway_accuracy must prefer SUPPORTED
claims when extracting the primary predicted pathway name, NOT the first
claim regardless of verdict.

Problem: cascade rebuilt CONTRADICTED PATHWAY_ENRICHMENT claims whose
term_name was corrupted to the verifier correction string. When those
claims appear first in the list, _eval_pathway_accuracy returns the
correction text as primary_name -> top1_hit = False even though
SUPPORTED PATHWAY_MEMBERSHIP claims correctly name the pathway.

Fix 2: prefer non-CONTRADICTED claims (SUPPORTED / INSUFFICIENT_EVIDENCE)
for primary_name selection; fall back to any claim only if no preferred
claims have a pathway name.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helper: build a minimal VerifiedClaim for eval testing
# ---------------------------------------------------------------------------


def _make_vc(
    *,
    verdict_str: str,  # lowercase enum value e.g. "supported"
    grammar_str: str,  # ClaimGrammar value e.g. "pathway_membership"
    pathway_name: str | None,
    claim_text: str = "test claim",
):
    """Build a VerifiedClaim that _eval_pathway_accuracy can inspect."""
    from verifier.schemas import (
        ClaimExtractedFields,
        ClaimSubtype,
        ClaimType,
        ClaimVerdict,
        SubjectKind,
        VerifiedClaim,
    )
    from verifier.grammar import ClaimGrammar

    verdict = ClaimVerdict(verdict_str)
    grammar = ClaimGrammar(grammar_str) if grammar_str not in ("None", None) else None

    return VerifiedClaim(
        claim_text=claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=None,
        subject_kind=SubjectKind.UNKNOWN,
        verdict=verdict,
        evidence="test evidence",
        extracted_fields=ClaimExtractedFields(
            pathway_name=pathway_name,
        ),
        grammar=grammar,
    )


def _dummy_match(gt: str, pred: str) -> bool:
    """Case-insensitive exact match for testing."""
    return gt.strip().lower() == pred.strip().lower()


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


def test_eval_pathway_accuracy_importable():
    from scripts.metagent.feedback_ab_eval import _eval_pathway_accuracy  # noqa


# ---------------------------------------------------------------------------
# Fix 2 RED tests
# ---------------------------------------------------------------------------


def test_fix2_primary_name_from_supported_not_contradicted():
    """Fix 2 RED: when first claim is CONTRADICTED with garbage pathway_name
    and later claims are SUPPORTED with correct pathway_name, primary_name
    should come from a SUPPORTED claim, not the CONTRADICTED one.

    Before fix: primary_name = garbage (first claim regardless of verdict).
    After fix:  primary_name = "Galactose Metabolism" (first SUPPORTED claim).
    """
    from scripts.metagent.feedback_ab_eval import _eval_pathway_accuracy

    # Simulate the A_cascade Galactose task: CONTRADICTED enrichment first,
    # then SUPPORTED membership claims with correct pathway name.
    claims = [
        _make_vc(
            verdict_str="contradicted",
            grammar_str="pathway_enrichment",
            pathway_name="The actual top-1 enriched pathway is 'Galactosemia'.",
            claim_text="run_ramp_enrichment ranks SMPDB:SMP00043 (Galactose Metabolism) at rank 1.",
        ),
        _make_vc(
            verdict_str="contradicted",
            grammar_str="pathway_enrichment",
            pathway_name="The actual top-1 enriched pathway is 'Galactosemia'.",
            claim_text="run_ramp_enrichment ranks WP:WP2533 at rank 4.",
        ),
        _make_vc(
            verdict_str="supported",
            grammar_str="pathway_membership",
            pathway_name="Galactose Metabolism",
            claim_text="galactitol is a member of Galactose Metabolism.",
        ),
        _make_vc(
            verdict_str="supported",
            grammar_str="pathway_membership",
            pathway_name="Galactose Metabolism",
            claim_text="myo-inositol is a member of Galactose Metabolism.",
        ),
    ]

    result = _eval_pathway_accuracy(
        narrative=None,
        claims=claims,
        gt_pathway_name="Galactose Metabolism",
        pathway_semantic_match_fn=_dummy_match,
    )

    assert result["primary_name"] == "Galactose Metabolism", (
        f"primary_name should be 'Galactose Metabolism' from SUPPORTED claims, "
        f"got {result['primary_name']!r}"
    )
    assert result["top1_hit"] is True, (
        f"top1_hit should be True, got {result['top1_hit']!r}"
    )


def test_fix2_topk_still_works_with_mixed_claims():
    """Fix 2: topk should still scan all claims (including CONTRADICTED)
    for any pathway match, while primary_name comes from SUPPORTED claims.
    """
    from scripts.metagent.feedback_ab_eval import _eval_pathway_accuracy

    # CONTRADICTED first with correct pathway, SUPPORTED second with different
    claims = [
        _make_vc(
            verdict_str="contradicted",
            grammar_str="pathway_membership",
            pathway_name="Galactose Metabolism",
            claim_text="galactitol is a member of Galactose Metabolism.",
        ),
        _make_vc(
            verdict_str="supported",
            grammar_str="pathway_membership",
            pathway_name="Other Pathway",
            claim_text="something is a member of Other Pathway.",
        ),
    ]

    result = _eval_pathway_accuracy(
        narrative=None,
        claims=claims,
        gt_pathway_name="Galactose Metabolism",
        pathway_semantic_match_fn=_dummy_match,
    )

    # primary_name from SUPPORTED = "Other Pathway" -> top1_hit False
    assert result["primary_name"] == "Other Pathway", (
        f"primary_name should be from SUPPORTED claim 'Other Pathway', "
        f"got {result['primary_name']!r}"
    )
    assert result["top1_hit"] is False
    # topk scans all claims -> True (CONTRADICTED claim has correct pathway)
    assert result["topk_hit"] is True


def test_fix2_falls_back_to_all_claims_if_no_preferred():
    """Fix 2: when no SUPPORTED/INSUFFICIENT_EVIDENCE claims have pathway_name,
    fall back to scanning all claims (existing behavior preserved).
    """
    from scripts.metagent.feedback_ab_eval import _eval_pathway_accuracy

    claims = [
        _make_vc(
            verdict_str="contradicted",
            grammar_str="pathway_membership",
            pathway_name="Galactose Metabolism",
            claim_text="galactitol is a member of Galactose Metabolism.",
        ),
    ]

    result = _eval_pathway_accuracy(
        narrative=None,
        claims=claims,
        gt_pathway_name="Galactose Metabolism",
        pathway_semantic_match_fn=_dummy_match,
    )
    # Falls back to CONTRADICTED claim since no preferred claims exist
    assert result["primary_name"] == "Galactose Metabolism"
    assert result["top1_hit"] is True
