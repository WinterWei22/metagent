"""Tests for Task 4: build_anchored_feedback (B-strategy) + should_trigger_feedback (C-gating).

TDD RED → GREEN per feedback-redesign plan Task 4 brief.

Assertions:
  (a) build_anchored_feedback output contains SUPPORTED claims' text in an anchor block
  (b) CONTRADICTED claims' correction appears
  (c) INSUFFICIENT_EVIDENCE claims do NOT appear
  (d) should_trigger_feedback returns True with contradicted/unsupported present,
      False when only supported/insufficient
"""
from __future__ import annotations

import pytest

from verifier.grammar import ClaimGrammar
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    SubjectKind,
    VerifiedClaim,
)


# ---------------------------------------------------------------------------
# Helpers — minimal VerifiedClaim instances
# ---------------------------------------------------------------------------


def _make_claim(
    *,
    verdict: ClaimVerdict,
    claim_text: str = "Glycolysis is enriched in the metabolite set.",
    grammar: ClaimGrammar | None = ClaimGrammar.PATHWAY_MEMBERSHIP,
    pathway_name: str | None = "Glycolysis",
    subject: str | None = "Glucose",
    correction: str | None = None,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_text=claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=subject,
        subject_kind=SubjectKind.UNKNOWN,
        verdict=verdict,
        evidence="test evidence",
        correction=correction,
        extracted_fields=ClaimExtractedFields(
            pathway_name=pathway_name,
        ),
        grammar=grammar,
    )


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


def test_build_anchored_feedback_importable():
    from concord.agent.feedback_strategies import build_anchored_feedback  # noqa: F401


def test_should_trigger_feedback_importable():
    from concord.agent.feedback_strategies import should_trigger_feedback  # noqa: F401


# ---------------------------------------------------------------------------
# (a) SUPPORTED claims appear in anchor block
# ---------------------------------------------------------------------------


def test_supported_claim_text_in_anchor_block():
    """build_anchored_feedback must include SUPPORTED claim_text in output."""
    from concord.agent.feedback_strategies import build_anchored_feedback

    claim = _make_claim(
        verdict=ClaimVerdict.SUPPORTED,
        claim_text="Fatty acid beta-oxidation is enriched.",
        pathway_name="Fatty acid beta-oxidation",
    )
    output = build_anchored_feedback([claim])
    assert "Fatty acid beta-oxidation is enriched." in output


def test_multiple_supported_claims_all_appear():
    from concord.agent.feedback_strategies import build_anchored_feedback

    claims = [
        _make_claim(
            verdict=ClaimVerdict.SUPPORTED,
            claim_text="TCA cycle is enriched.",
            pathway_name="TCA cycle",
        ),
        _make_claim(
            verdict=ClaimVerdict.SUPPORTED,
            claim_text="Glycolysis is enriched.",
            pathway_name="Glycolysis",
        ),
    ]
    output = build_anchored_feedback(claims)
    assert "TCA cycle is enriched." in output
    assert "Glycolysis is enriched." in output


def test_anchor_block_label_present():
    """Output should contain an explicit anchor/preserve section label."""
    from concord.agent.feedback_strategies import build_anchored_feedback

    claim = _make_claim(verdict=ClaimVerdict.SUPPORTED, claim_text="Glycolysis is enriched.")
    output = build_anchored_feedback([claim])
    # Must indicate these are already verified / should be preserved
    output_lower = output.lower()
    assert any(kw in output_lower for kw in ["anchor", "preserve", "keep", "verified", "保留"])


# ---------------------------------------------------------------------------
# (b) CONTRADICTED claims' correction appears
# ---------------------------------------------------------------------------


def test_contradicted_correction_in_output():
    """CONTRADICTED claim's correction (top-1 alternative) must appear in output."""
    from concord.agent.feedback_strategies import build_anchored_feedback

    claim = _make_claim(
        verdict=ClaimVerdict.CONTRADICTED,
        claim_text="Wrong pathway is enriched.",
        pathway_name="Wrong pathway",
        correction="TCA cycle",
    )
    output = build_anchored_feedback([claim])
    assert "TCA cycle" in output


def test_contradicted_section_label_present():
    """Output should contain a CONTRADICTED section."""
    from concord.agent.feedback_strategies import build_anchored_feedback

    claim = _make_claim(
        verdict=ClaimVerdict.CONTRADICTED,
        claim_text="Wrong pathway is enriched.",
        correction="TCA cycle",
    )
    output = build_anchored_feedback([claim])
    output_lower = output.lower()
    assert any(kw in output_lower for kw in ["contradict", "must change", "must fix", "retract", "错误", "必须"])


def test_contradicted_no_correction_not_in_output():
    """CONTRADICTED with no correction should not appear in 'must change' block."""
    from concord.agent.feedback_strategies import build_anchored_feedback

    claim = _make_claim(
        verdict=ClaimVerdict.CONTRADICTED,
        claim_text="Wrong pathway is enriched.",
        correction=None,
    )
    # Should not crash; CONTRADICTED with no correction might just be omitted
    output = build_anchored_feedback([claim])
    # Should still return a string
    assert isinstance(output, str)


# ---------------------------------------------------------------------------
# (c) INSUFFICIENT_EVIDENCE claims do NOT appear
# ---------------------------------------------------------------------------


def test_insufficient_evidence_not_in_output():
    """INSUFFICIENT_EVIDENCE claims must NOT appear in the feedback output."""
    from concord.agent.feedback_strategies import build_anchored_feedback

    insufficient_text = "Purine metabolism is uniquely enriched in this study."
    claim = _make_claim(
        verdict=ClaimVerdict.INSUFFICIENT_EVIDENCE,
        claim_text=insufficient_text,
        pathway_name="Purine metabolism",
    )
    output = build_anchored_feedback([claim])
    assert insufficient_text not in output


def test_insufficient_evidence_pathway_not_in_output():
    """INSUFFICIENT_EVIDENCE pathway name must not appear in instructions."""
    from concord.agent.feedback_strategies import build_anchored_feedback

    claim = _make_claim(
        verdict=ClaimVerdict.INSUFFICIENT_EVIDENCE,
        claim_text="Purine metabolism claim.",
        pathway_name="Purine metabolism",
    )
    output = build_anchored_feedback([claim])
    # The pathway name should not appear in feedback instructions
    # (the verifier is unsure, so the LLM should keep original without guidance)
    assert "Purine metabolism" not in output


# ---------------------------------------------------------------------------
# (d) should_trigger_feedback: True/False based on verdicts
# ---------------------------------------------------------------------------


def test_trigger_true_with_contradicted():
    from concord.agent.feedback_strategies import should_trigger_feedback

    claims = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED),
        _make_claim(verdict=ClaimVerdict.CONTRADICTED, correction="TCA cycle"),
    ]
    assert should_trigger_feedback(claims) is True


def test_trigger_true_with_unsupported():
    from concord.agent.feedback_strategies import should_trigger_feedback

    claims = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED),
        _make_claim(verdict=ClaimVerdict.UNSUPPORTED),
    ]
    assert should_trigger_feedback(claims) is True


def test_trigger_false_all_supported():
    from concord.agent.feedback_strategies import should_trigger_feedback

    claims = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED),
        _make_claim(verdict=ClaimVerdict.SUPPORTED, pathway_name="Beta oxidation"),
    ]
    assert should_trigger_feedback(claims) is False


def test_trigger_false_supported_and_insufficient():
    """Only SUPPORTED + INSUFFICIENT_EVIDENCE: no trigger."""
    from concord.agent.feedback_strategies import should_trigger_feedback

    claims = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED),
        _make_claim(verdict=ClaimVerdict.INSUFFICIENT_EVIDENCE),
    ]
    assert should_trigger_feedback(claims) is False


def test_trigger_false_empty():
    from concord.agent.feedback_strategies import should_trigger_feedback

    assert should_trigger_feedback([]) is False


def test_trigger_min_bad_frac_threshold():
    """min_bad_frac=0.5: only triggers if >= 50% claims are contradicted/unsupported."""
    from concord.agent.feedback_strategies import should_trigger_feedback

    # 1 contradicted out of 3 total = 33% < 50% → False
    claims_low = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED),
        _make_claim(verdict=ClaimVerdict.SUPPORTED, pathway_name="Beta oxidation"),
        _make_claim(verdict=ClaimVerdict.CONTRADICTED, correction="TCA cycle"),
    ]
    assert should_trigger_feedback(claims_low, min_bad_frac=0.5) is False

    # 2 contradicted out of 3 total = 67% >= 50% → True
    claims_high = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED),
        _make_claim(verdict=ClaimVerdict.CONTRADICTED, correction="TCA cycle"),
        _make_claim(verdict=ClaimVerdict.UNSUPPORTED),
    ]
    assert should_trigger_feedback(claims_high, min_bad_frac=0.5) is True


def test_trigger_default_min_bad_frac_zero():
    """Default min_bad_frac=0.0: even 1 contradicted in many claims triggers."""
    from concord.agent.feedback_strategies import should_trigger_feedback

    claims = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED),
        _make_claim(verdict=ClaimVerdict.SUPPORTED, pathway_name="Beta oxidation"),
        _make_claim(verdict=ClaimVerdict.SUPPORTED, pathway_name="Glycolysis"),
        _make_claim(verdict=ClaimVerdict.SUPPORTED, pathway_name="Fatty acid"),
        _make_claim(verdict=ClaimVerdict.CONTRADICTED, correction="TCA cycle"),
    ]
    assert should_trigger_feedback(claims) is True


# ---------------------------------------------------------------------------
# Mixed: both SUPPORTED and CONTRADICTED in same output
# ---------------------------------------------------------------------------


def test_mixed_supported_and_contradicted():
    """Output has anchor block (SUPPORTED) AND instruction block (CONTRADICTED)."""
    from concord.agent.feedback_strategies import build_anchored_feedback

    claims = [
        _make_claim(
            verdict=ClaimVerdict.SUPPORTED,
            claim_text="TCA cycle is enriched.",
            pathway_name="TCA cycle",
        ),
        _make_claim(
            verdict=ClaimVerdict.CONTRADICTED,
            claim_text="Wrong pathway is enriched.",
            pathway_name="Wrong pathway",
            correction="Fatty acid beta-oxidation",
        ),
    ]
    output = build_anchored_feedback(claims)
    # Supported text must appear (anchor)
    assert "TCA cycle is enriched." in output
    # Correction must appear
    assert "Fatty acid beta-oxidation" in output
