"""Tests for concord.agent.feedback_strategies.apply_cascade.

RED → GREEN TDD for Task 1 (feedback-redesign plan).

Grammar-v2 dict keys confirmed from verifier/claim_extractor.py::_to_extracted_claim:
  Required by _to_extracted_claim:
    - "grammar"      (str, must be a ClaimGrammar value)
    - "claim_text"   (str, the verbatim sentence)
  Optional but consumed:
    - "pathway_name" OR "term_name" (str, feeds ClaimExtractedFields.pathway_name)
    - "subject"      (str | None)
  Grammar-specific required fields (consumed by verifier.grammar.validate):
    - pathway_membership:    subject, pathway_name
    - metabolite_pathway_link: subject, pathway_name, enzyme_or_reaction
    - pathway_enrichment:    term_id, term_name, term_type
    - driver_metabolite:     subject, pathway_name, signal_compound_ids

NEEDS_HUMAN_REVIEW: not in the spec table → treated as drop (same as UV).
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
# Helpers — construct minimal VerifiedClaim instances
# ---------------------------------------------------------------------------


def _make_claim(
    *,
    verdict: ClaimVerdict,
    claim_text: str = "Glycolysis is enriched in the metabolite set.",
    grammar: ClaimGrammar | None = ClaimGrammar.PATHWAY_MEMBERSHIP,
    pathway_name: str | None = "Glycolysis",
    pathway_id: str | None = "map00010",
    subject: str | None = "Glucose",
    correction: str | None = None,
) -> VerifiedClaim:
    """Build a minimal VerifiedClaim for testing cascade routing."""
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
            pathway_id=pathway_id,
        ),
        grammar=grammar,
    )


# ---------------------------------------------------------------------------
# Import guard — confirms RED before implementation exists
# ---------------------------------------------------------------------------


def test_apply_cascade_import():
    """apply_cascade must be importable from concord.agent.feedback_strategies."""
    from concord.agent.feedback_strategies import apply_cascade  # noqa: F401


# ---------------------------------------------------------------------------
# SUPPORTED → keep, rebuild as grammar-v2 dict
# ---------------------------------------------------------------------------


def test_supported_claim_is_kept():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(verdict=ClaimVerdict.SUPPORTED)
    result = apply_cascade([claim])
    assert len(result) == 1


def test_supported_claim_has_required_grammar_v2_keys():
    """Each kept dict must have the 4 keys _to_extracted_claim consumes."""
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(verdict=ClaimVerdict.SUPPORTED)
    result = apply_cascade([claim])
    d = result[0]
    assert "grammar" in d
    assert "claim_text" in d
    # pathway_name feeds ClaimExtractedFields.pathway_name in _to_extracted_claim
    assert "pathway_name" in d or "term_name" in d
    assert "subject" in d


def test_supported_claim_grammar_value():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(verdict=ClaimVerdict.SUPPORTED, grammar=ClaimGrammar.PATHWAY_MEMBERSHIP)
    result = apply_cascade([claim])
    assert result[0]["grammar"] == ClaimGrammar.PATHWAY_MEMBERSHIP.value


def test_supported_claim_pathway_name_preserved():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(verdict=ClaimVerdict.SUPPORTED, pathway_name="TCA cycle")
    result = apply_cascade([claim])
    assert result[0]["pathway_name"] == "TCA cycle"


# ---------------------------------------------------------------------------
# INSUFFICIENT_EVIDENCE → keep
# ---------------------------------------------------------------------------


def test_insufficient_evidence_is_kept():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(verdict=ClaimVerdict.INSUFFICIENT_EVIDENCE)
    result = apply_cascade([claim])
    assert len(result) == 1


def test_insufficient_evidence_has_required_keys():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(verdict=ClaimVerdict.INSUFFICIENT_EVIDENCE)
    result = apply_cascade([claim])
    d = result[0]
    assert "grammar" in d
    assert "claim_text" in d
    assert "subject" in d


# ---------------------------------------------------------------------------
# UNSUPPORTED → drop
# ---------------------------------------------------------------------------


def test_unsupported_is_dropped():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(verdict=ClaimVerdict.UNSUPPORTED)
    result = apply_cascade([claim])
    assert result == []


# ---------------------------------------------------------------------------
# UNVERIFIABLE_V0 → drop
# ---------------------------------------------------------------------------


def test_unverifiable_v0_is_dropped():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(verdict=ClaimVerdict.UNVERIFIABLE_V0)
    result = apply_cascade([claim])
    assert result == []


# ---------------------------------------------------------------------------
# CONTRADICTED → keep with pathway_name replaced by correction
# ---------------------------------------------------------------------------


def test_contradicted_with_correction_is_kept():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(
        verdict=ClaimVerdict.CONTRADICTED,
        pathway_name="Wrong Pathway",
        correction="Correct Pathway",
    )
    result = apply_cascade([claim])
    assert len(result) == 1


def test_contradicted_pathway_name_replaced_by_correction():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(
        verdict=ClaimVerdict.CONTRADICTED,
        pathway_name="Wrong Pathway",
        correction="Correct Pathway",
    )
    result = apply_cascade([claim])
    assert result[0]["pathway_name"] == "Correct Pathway"


def test_contradicted_empty_correction_is_dropped():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(
        verdict=ClaimVerdict.CONTRADICTED,
        correction=None,
    )
    result = apply_cascade([claim])
    assert result == []


def test_contradicted_whitespace_correction_is_dropped():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(
        verdict=ClaimVerdict.CONTRADICTED,
        correction="   ",
    )
    result = apply_cascade([claim])
    assert result == []


# ---------------------------------------------------------------------------
# NEEDS_HUMAN_REVIEW → drop (spec gap, treat like UV)
# ---------------------------------------------------------------------------


def test_needs_human_review_is_dropped():
    from concord.agent.feedback_strategies import apply_cascade

    claim = _make_claim(verdict=ClaimVerdict.NEEDS_HUMAN_REVIEW)
    result = apply_cascade([claim])
    assert result == []


# ---------------------------------------------------------------------------
# Mixed list — all 5 verdict types together
# ---------------------------------------------------------------------------


def test_mixed_list_correct_counts():
    """All 5 verdict types: supported + insufficient kept, rest dropped."""
    from concord.agent.feedback_strategies import apply_cascade

    claims = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED, pathway_name="Glycolysis"),
        _make_claim(verdict=ClaimVerdict.INSUFFICIENT_EVIDENCE, pathway_name="Beta oxidation"),
        _make_claim(verdict=ClaimVerdict.UNSUPPORTED),
        _make_claim(verdict=ClaimVerdict.UNVERIFIABLE_V0),
        _make_claim(
            verdict=ClaimVerdict.CONTRADICTED,
            pathway_name="Wrong",
            correction="TCA cycle",
        ),
        _make_claim(verdict=ClaimVerdict.NEEDS_HUMAN_REVIEW),
    ]
    result = apply_cascade(claims)
    # kept: SUPPORTED, INSUFFICIENT_EVIDENCE, CONTRADICTED(with correction) = 3
    assert len(result) == 3


def test_mixed_list_pathway_names():
    """Pathway names in kept dicts match expected values."""
    from concord.agent.feedback_strategies import apply_cascade

    claims = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED, pathway_name="Glycolysis"),
        _make_claim(verdict=ClaimVerdict.INSUFFICIENT_EVIDENCE, pathway_name="Beta oxidation"),
        _make_claim(
            verdict=ClaimVerdict.CONTRADICTED,
            pathway_name="Wrong",
            correction="TCA cycle",
        ),
        _make_claim(verdict=ClaimVerdict.UNSUPPORTED),
    ]
    result = apply_cascade(claims)
    kept_names = [d["pathway_name"] for d in result]
    assert "Glycolysis" in kept_names
    assert "Beta oxidation" in kept_names
    assert "TCA cycle" in kept_names


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_empty_input():
    from concord.agent.feedback_strategies import apply_cascade

    assert apply_cascade([]) == []


# ---------------------------------------------------------------------------
# claim_text is preserved verbatim
# ---------------------------------------------------------------------------


def test_claim_text_preserved():
    from concord.agent.feedback_strategies import apply_cascade

    text = "L-Methionine is a member of Cysteine and methionine metabolism."
    claim = _make_claim(verdict=ClaimVerdict.SUPPORTED, claim_text=text)
    result = apply_cascade([claim])
    assert result[0]["claim_text"] == text


# ---------------------------------------------------------------------------
# Fix 1: PATHWAY_ENRICHMENT + CONTRADICTED — term_name must NOT be the
# correction string. It should remain the original term name so the eval
# can read a sensible pathway name from the claim.
# ---------------------------------------------------------------------------


def _make_enrichment_claim(
    *,
    verdict: ClaimVerdict,
    term_name: str = "Galactose Metabolism",
    term_id: str = "SMPDB:SMP00043",
    correction: str | None = None,
) -> VerifiedClaim:
    """Build a PATHWAY_ENRICHMENT VerifiedClaim for cascade fix-1 testing."""
    from verifier.schemas import EnrichmentContext
    return VerifiedClaim(
        claim_text=f"run_ramp_enrichment ranks {term_id} ({term_name}) at rank 1.",
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=None,
        subject_kind=SubjectKind.UNKNOWN,
        verdict=verdict,
        evidence="test evidence",
        correction=correction,
        extracted_fields=ClaimExtractedFields(
            pathway_name=term_name,
            pathway_id=term_id,
        ),
        grammar=ClaimGrammar.PATHWAY_ENRICHMENT,
        enrichment_context=EnrichmentContext(
            claimed_pathway=term_name,
            claimed_pathway_id=term_id,
        ),
    )


def test_fix1_contradicted_enrichment_term_name_not_correction():
    """Fix 1 RED: cascade PATHWAY_ENRICHMENT + CONTRADICTED must NOT put
    the correction string in term_name. The term_name should be the
    original term name (from enrichment_context or extracted_fields), not
    the verifier's correction text (which is a human-readable explanation).
    """
    from concord.agent.feedback_strategies import apply_cascade

    correction_text = "The actual top-1 enriched pathway is 'Galactosemia'."
    claim = _make_enrichment_claim(
        verdict=ClaimVerdict.CONTRADICTED,
        term_name="Galactose Metabolism",
        term_id="SMPDB:SMP00043",
        correction=correction_text,
    )
    result = apply_cascade([claim])
    # Claim is CONTRADICTED with a non-empty correction -> kept
    assert len(result) == 1
    d = result[0]
    # term_name must NOT be the correction text
    assert d.get("term_name") != correction_text, (
        f"term_name should not be the correction string; got {d.get('term_name')!r}"
    )
    # term_name should be a sensible pathway name (original or from context), not empty
    assert d.get("term_name"), "term_name must not be empty after cascade"


def test_fix1_contradicted_enrichment_term_name_is_original():
    """Fix 1 RED: cascade PATHWAY_ENRICHMENT + CONTRADICTED -- term_name
    should come from enrichment_context.claimed_pathway (the original term
    name recorded by the verifier layer), not from pathway_name_override.
    """
    from concord.agent.feedback_strategies import apply_cascade

    correction_text = "The actual top-1 enriched pathway is 'Galactosemia'."
    claim = _make_enrichment_claim(
        verdict=ClaimVerdict.CONTRADICTED,
        term_name="Galactose Metabolism",
        term_id="SMPDB:SMP00043",
        correction=correction_text,
    )
    result = apply_cascade([claim])
    assert len(result) == 1
    d = result[0]
    # term_name should be the original term from enrichment_context / extracted_fields
    assert d.get("term_name") == "Galactose Metabolism", (
        f"Expected 'Galactose Metabolism' in term_name, got {d.get('term_name')!r}"
    )
