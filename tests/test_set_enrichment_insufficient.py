"""Task 6 (D2.2): verify_set_enrichment absent-pathway → INSUFFICIENT_EVIDENCE.

Decision boundary (authorized, option B):
- claim HAS pathway name/id BUT pathway is absent from multisource pool AND
  absent from RaMP top-10 → INSUFFICIENT_EVIDENCE + missing-evidence checklist.
- claim has NO pathway name/id → UNVERIFIABLE_V0 (unchanged).
- "absent" ≠ "refuted"; CONTRADICTED is reserved for rank/score-mismatch (Task 8).
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
# Helpers (mirror the pattern from test_layer_set_enrichment.py)
# ---------------------------------------------------------------------------


def _claim(
    text: str,
    *,
    pathway_name: str | None = None,
    pathway_id: str | None = None,
) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_text=text,
        claim_type=ClaimType.SET_ENRICHMENT,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(
            pathway_name=pathway_name,
            pathway_id=pathway_id,
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
# Core: absent-pathway-with-name → INSUFFICIENT_EVIDENCE
# ---------------------------------------------------------------------------


def test_absent_pathway_with_metabolites_is_insufficient():
    """Pool is non-empty but does NOT contain the claimed pathway.

    claim names "Tyrosine metabolism"; pool only has "Glycolysis".
    → INSUFFICIENT_EVIDENCE (not UV, not CONTRADICTED).
    """
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "KEGG:hsa00010",
                    "pathway_name": "Glycolysis",
                    "fdr": 1e-5,
                    "matched_compounds": [],
                }
            ]
        }
    )
    r = verify_set_enrichment(_claim("Tyrosine metabolism"), src)
    assert r.verdict == ClaimVerdict.INSUFFICIENT_EVIDENCE
    hint = r.feedback_hint or ""
    assert "缺" in hint or "missing" in hint.lower()


def test_absent_pathway_via_extracted_field_is_insufficient():
    """Same as above but pathway_name comes from extracted_fields (typed)."""
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_000000001",
                    "pathway_name": "Glycolysis",
                    "fdr": 1e-3,
                }
            ]
        }
    )
    r = verify_set_enrichment(
        _claim("These metabolites are enriched in Vitamin B12 metabolism.",
               pathway_name="Vitamin B12 metabolism"),
        src,
    )
    assert r.verdict == ClaimVerdict.INSUFFICIENT_EVIDENCE


def test_absent_pathway_checklist_mentions_paradigm():
    """feedback_hint checklist must mention paradigm or pathway evidence."""
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {"pathway_id": "RAMP_P_X", "pathway_name": "Glycolysis", "fdr": 1e-3}
            ]
        }
    )
    r = verify_set_enrichment(
        _claim("Arginine biosynthesis is enriched."),
        src,
    )
    assert r.verdict == ClaimVerdict.INSUFFICIENT_EVIDENCE
    hint = r.feedback_hint or ""
    # checklist should mention something about paradigm or evidence need
    assert any(kw in hint for kw in ["paradigm", "top_pathways", "缺", "未出现", "pathway"]), (
        f"Expected checklist content in feedback_hint, got: {hint!r}"
    )


# ---------------------------------------------------------------------------
# Boundary: no pathway name/id → UNVERIFIABLE_V0 (unchanged)
# ---------------------------------------------------------------------------


def test_no_pathway_name_or_id_still_unverifiable():
    """Claim with no pathway name/id must remain UNVERIFIABLE_V0, not INSUFFICIENT."""
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {"pathway_id": "RAMP_P_X", "pathway_name": "Glycolysis", "fdr": 1e-3}
            ]
        }
    )
    r = verify_set_enrichment(_claim("These metabolites are interesting."), src)
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


# ---------------------------------------------------------------------------
# Boundary: multisource pool hit → still SUPPORTED (no regression)
# ---------------------------------------------------------------------------


def test_pool_hit_in_mummichog_still_supported():
    """Pathway present in mummichog pool → SUPPORTED regardless of RaMP top-10."""
    src = _src(
        mummichog_enrichment_result={
            "pathways": [
                {
                    "pathway_id": "MUMM:tyrosine_met",
                    "pathway_name": "Tyrosine metabolism",
                }
            ]
        },
        ramp_enrichment_result={"top_pathways": []},
    )
    r = verify_set_enrichment(_claim("Tyrosine metabolism"), src)
    assert r.verdict == ClaimVerdict.SUPPORTED


# ---------------------------------------------------------------------------
# Boundary: absent from multisource pool + absent from RaMP → INSUFFICIENT
# (this covers the old CONTRADICTED branch that is now INSUFFICIENT per option B)
# ---------------------------------------------------------------------------


def test_old_contradicted_branch_now_insufficient():
    """The old 'outside top-10 → CONTRADICTED' path is now INSUFFICIENT_EVIDENCE.

    Authorized semantic change: user adjudication option B (2026-06-25).
    absent ≠ refuted; CONTRADICTED reserved for Task 8 rank/score-mismatch.
    """
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_000000106",
                    "pathway_name": "Tyrosine metabolism",
                    "fdr": 1e-10,
                    "matched_compounds": ["C00070"],
                    "total_pathway_compounds": 69,
                },
                {
                    "pathway_id": "RAMP_P_000000099",
                    "pathway_name": "Alkaptonuria",
                    "fdr": 5e-9,
                    "matched_compounds": [],
                },
            ]
        }
    )
    r = verify_set_enrichment(_claim("Vitamin B12 metabolism is enriched."), src)
    assert r.verdict == ClaimVerdict.INSUFFICIENT_EVIDENCE


def test_verifier_layer_label_set_enrichment_on_insufficient():
    """INSUFFICIENT_EVIDENCE result must still set verifier_layer='set_enrichment'."""
    src = _src(
        ramp_enrichment_result={
            "top_pathways": [
                {"pathway_id": "RAMP_P_X", "pathway_name": "Glycolysis", "fdr": 1e-3}
            ]
        }
    )
    r = verify_set_enrichment(_claim("Purine metabolism"), src)
    assert r.verdict == ClaimVerdict.INSUFFICIENT_EVIDENCE
    assert r.verifier_layer == "set_enrichment"
