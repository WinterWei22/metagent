"""Task 8 (D3): rank/score-mismatch → CONTRADICTED + top-1 alternative.

Decision boundary:
- A claim that HITS a pathway in the RaMP pool BUT asserts a rank or score that
  CONTRADICTS the matched row → CONTRADICTED with correction/feedback_hint = top-1
  pathway name.
- A claim that hits the pathway with NO rank/score assertion → SUPPORTED (no regression).
- "Absent from pool" → INSUFFICIENT_EVIDENCE (Task 6, unchanged).

These tests drive the implementation in verifier/layers/set_enrichment.py (_verdict_for_rank).
"""
from __future__ import annotations

import pytest

from schemas.sub6_report import SubsixSourceReport
from verifier.layers.set_enrichment import verify_set_enrichment
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _claim(
    text: str,
    *,
    pathway_name: str | None = None,
    pathway_id: str | None = None,
    rank: int | None = None,
    score_value: float | None = None,
) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_text=text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(
            pathway_name=pathway_name,
            pathway_id=pathway_id,
            rank=rank,
            score_value=score_value,
        ),
    )


def _src(**kwargs) -> SubsixSourceReport:
    base = dict(
        task_id="t",
        task_type="compound_only_enrichment",
        ground_truth_pathway={},
        ground_truth_signal_compounds=[],
        ground_truth_noise_compounds=[],
        ramp_enrichment_result={"top_pathways": []},
    )
    base.update(kwargs)
    return SubsixSourceReport(**base)


# ---------------------------------------------------------------------------
# Core: rank mismatch → CONTRADICTED with top-1 in correction + feedback_hint
# ---------------------------------------------------------------------------


def test_contradicted_rank_mismatch_carries_top1_alternative():
    """Claim asserts rank=5 but pathway is actually rank=1 → CONTRADICTED.

    correction and feedback_hint must both reference the top-1 pathway name
    from RaMP top_pathways[0] ("Glycolysis").
    """
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "KEGG:hsa00010",
                    "pathway_name": "Glycolysis",
                    "fdr": 1e-9,
                    "matched_compounds": ["C00022"],
                    "total_pathway_compounds": 10,
                },
                {
                    "pathway_id": "KEGG:hsa00350",
                    "pathway_name": "Tyrosine metabolism",
                    "fdr": 1e-5,
                },
            ]
        }
    )
    # Glycolysis is rank=1 in pool, but claim says it's rank=5
    claim = _claim(
        "Glycolysis is ranked 5th in enrichment.",
        pathway_name="Glycolysis",
        rank=5,
    )
    r = verify_set_enrichment(claim, src)

    assert r.verdict == ClaimVerdict.CONTRADICTED, f"Expected CONTRADICTED, got {r.verdict}"
    # correction and/or feedback_hint must name the top-1 pathway
    top1 = "Glycolysis"
    correction = r.correction or ""
    hint = r.feedback_hint or ""
    assert top1 in correction or top1 in hint, (
        f"Expected top-1 pathway {top1!r} in correction or feedback_hint, "
        f"got correction={correction!r}, hint={hint!r}"
    )


def test_contradicted_score_mismatch_carries_top1_alternative():
    """Claim asserts FDR=0.5 but actual FDR=1e-9 → CONTRADICTED.

    Top-1 pathway name must appear in correction or feedback_hint.
    """
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_000000106",
                    "pathway_name": "Tyrosine metabolism",
                    "fdr": 1e-9,
                },
            ]
        }
    )
    claim = _claim(
        "Tyrosine metabolism has FDR=0.5.",
        pathway_name="Tyrosine metabolism",
        score_value=0.5,  # dramatically wrong
    )
    r = verify_set_enrichment(claim, src)

    assert r.verdict == ClaimVerdict.CONTRADICTED, f"Expected CONTRADICTED, got {r.verdict}"
    top1 = "Tyrosine metabolism"
    correction = r.correction or ""
    hint = r.feedback_hint or ""
    assert top1 in correction or top1 in hint, (
        f"Expected top-1 in correction/hint, got correction={correction!r}, hint={hint!r}"
    )


def test_contradicted_rank_different_top1_pathway():
    """Pathway at rank=2 but claim asserts rank=1 → CONTRADICTED.

    Top-1 (rank=1) is a DIFFERENT pathway; correction must name that pathway.
    """
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "KEGG:hsa00010",
                    "pathway_name": "Glycolysis",
                    "fdr": 1e-12,
                },
                {
                    "pathway_id": "KEGG:hsa00350",
                    "pathway_name": "Tyrosine metabolism",
                    "fdr": 1e-5,
                },
            ]
        }
    )
    # Tyrosine metabolism is rank=2, claim says rank=1 → mismatch
    claim = _claim(
        "Tyrosine metabolism is the top-ranked enriched pathway.",
        pathway_name="Tyrosine metabolism",
        rank=1,
    )
    r = verify_set_enrichment(claim, src)

    assert r.verdict == ClaimVerdict.CONTRADICTED, f"Expected CONTRADICTED, got {r.verdict}"
    # Top-1 is "Glycolysis" — correction should name it
    correction = r.correction or ""
    hint = r.feedback_hint or ""
    assert "Glycolysis" in correction or "Glycolysis" in hint, (
        f"Expected 'Glycolysis' (top-1) in correction/hint, "
        f"got correction={correction!r}, hint={hint!r}"
    )


# ---------------------------------------------------------------------------
# Regression guard: NO rank/score assertion → SUPPORTED (not CONTRADICTED)
# ---------------------------------------------------------------------------


def test_no_rank_score_assertion_stays_supported():
    """A claim that hits a pathway but asserts NO rank/score must stay SUPPORTED.

    This is the critical regression guard — the rank/score check must only
    trigger when the claim actually makes a rank/score assertion.
    """
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "KEGG:hsa00010",
                    "pathway_name": "Glycolysis",
                    "fdr": 1e-9,
                },
            ]
        }
    )
    # claim mentions pathway but asserts nothing about rank or score
    claim = _claim(
        "Glycolysis is enriched in this dataset.",
        pathway_name="Glycolysis",
        # rank=None, score_value=None — no assertion
    )
    r = verify_set_enrichment(claim, src)

    assert r.verdict == ClaimVerdict.SUPPORTED, (
        f"Expected SUPPORTED (no rank/score assertion), got {r.verdict}"
    )


def test_no_rank_score_assertion_via_text_stays_supported():
    """Claim text without rank/score patterns → SUPPORTED (no false positive)."""
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_000000106",
                    "pathway_name": "Tyrosine metabolism",
                    "fdr": 5e-8,
                },
            ]
        }
    )
    # neutral claim text, no "rank X", no "FDR=Y"
    claim = _claim(
        "These metabolites are enriched in Tyrosine metabolism pathway.",
        pathway_name="Tyrosine metabolism",
    )
    r = verify_set_enrichment(claim, src)

    assert r.verdict == ClaimVerdict.SUPPORTED, (
        f"Expected SUPPORTED (claim text has no rank/score assertion), got {r.verdict}"
    )


# ---------------------------------------------------------------------------
# Boundary: rank matches → SUPPORTED (not CONTRADICTED)
# ---------------------------------------------------------------------------


def test_rank_matches_stays_supported():
    """Claim asserts rank=1 and pathway IS rank=1 → SUPPORTED (rank matches)."""
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "KEGG:hsa00010",
                    "pathway_name": "Glycolysis",
                    "fdr": 1e-9,
                },
            ]
        }
    )
    claim = _claim(
        "Glycolysis is the top-ranked enriched pathway (rank 1).",
        pathway_name="Glycolysis",
        rank=1,
    )
    r = verify_set_enrichment(claim, src)

    assert r.verdict == ClaimVerdict.SUPPORTED, (
        f"Expected SUPPORTED (rank=1 matches observed rank=1), got {r.verdict}"
    )


def test_score_matches_stays_supported():
    """Claim asserts FDR≈1e-9 and actual FDR=1e-9 → SUPPORTED."""
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_X",
                    "pathway_name": "Glycolysis",
                    "fdr": 1e-9,
                },
            ]
        }
    )
    claim = _claim(
        "Glycolysis has FDR=1e-9.",
        pathway_name="Glycolysis",
        score_value=1e-9,
    )
    r = verify_set_enrichment(claim, src)

    assert r.verdict == ClaimVerdict.SUPPORTED, (
        f"Expected SUPPORTED (score matches within tolerance), got {r.verdict}"
    )


# ---------------------------------------------------------------------------
# Boundary: pool hit (non-RaMP) with rank assertion — pool hit wins, no check
# ---------------------------------------------------------------------------


def test_pool_hit_with_rank_assertion_still_supported():
    """Non-RaMP pool hit: rank/score check should NOT apply to non-RaMP paradigms.

    Non-RaMP paradigms don't expose a rank contract, so a pool hit is SUPPORTED
    regardless of rank/score assertions in the claim.
    """
    src = _src(
        mummichog_enrichment_result={
            "pathways": [
                {
                    "pathway_id": "MUMM:glycolysis",
                    "pathway_name": "Glycolysis",
                }
            ]
        },
        ramp_enrichment_result={"top_pathways": []},
    )
    claim = _claim(
        "Glycolysis is ranked 99th.",
        pathway_name="Glycolysis",
        rank=99,  # absurd rank — but non-RaMP pool doesn't expose rank
    )
    r = verify_set_enrichment(claim, src)

    assert r.verdict == ClaimVerdict.SUPPORTED, (
        f"Expected SUPPORTED (non-RaMP pool hit, rank check doesn't apply), got {r.verdict}"
    )
