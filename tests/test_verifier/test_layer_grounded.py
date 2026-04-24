"""Unit tests for Layer A — grounded (Type 1) claim verification."""
from __future__ import annotations

import pytest

from verifier.layers.grounded import verify_grounded
from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim


def _gc(text, subj):
    return ClassifiedClaim(
        claim_text=text, subject=subj,
        claim_type=ClaimType.GROUNDED, classifier_source="rule",
    )


# ---------------------------------------------------------------------------
# H1 — the canonical formula-contradiction case
# ---------------------------------------------------------------------------


def test_H1_ascii_formula_contradiction(glucose_report):
    r = verify_grounded(
        _gc("D-Gulose has molecular formula C7H14O7", "D-Gulose"),
        glucose_report,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED
    assert r.correction == "C6H12O6"
    assert r.source_field == "candidates[0].metabolite_info.molecular_formula"


def test_H1_unicode_subscript_variant_is_normalised(glucose_report):
    # The REAL LLM output writes 'D-Gulose (C₇H₁₄O₇)' with unicode subscripts
    r = verify_grounded(
        _gc("D-Gulose has molecular formula C₇H₁₄O₇", "D-Gulose"),
        glucose_report,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED
    assert r.correction == "C6H12O6"


def test_supported_formula_matches_source(glucose_report):
    r = verify_grounded(
        _gc("Glucose has molecular formula C6H12O6", "Glucose"),
        glucose_report,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


# ---------------------------------------------------------------------------
# H2 — ppm scalar hallucination
# ---------------------------------------------------------------------------


def test_H2_ppm_scalar_is_unsupported(glucose_report):
    r = verify_grounded(
        _gc("The mass accuracy is below 1 ppm vs HMDB reference", None),
        glucose_report,
    )
    assert r.verdict == ClaimVerdict.UNSUPPORTED
    assert "mass_match_indicator" in r.evidence


# ---------------------------------------------------------------------------
# Numeric fields — evidence_score / cosine / B/C
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,subj,expected",
    [
        ("D-Gulose evidence_score is 0.771", "D-Gulose", ClaimVerdict.SUPPORTED),
        ("D-Gulose evidence_score is 0.800", "D-Gulose", ClaimVerdict.CONTRADICTED),
        ("Predicted-spectrum cosine 0.423", "D-Gulose", ClaimVerdict.SUPPORTED),
        ("Predicted-spectrum cosine 0.500", "D-Gulose", ClaimVerdict.CONTRADICTED),
        ("B/C 0.860", "D-Gulose", ClaimVerdict.SUPPORTED),
        ("B/C 0.999", "D-Gulose", ClaimVerdict.CONTRADICTED),
    ],
)
def test_numeric_field_verdict(glucose_report, text, subj, expected):
    r = verify_grounded(_gc(text, subj), glucose_report)
    assert r.verdict == expected


# ---------------------------------------------------------------------------
# Subject / field resolution misses
# ---------------------------------------------------------------------------


def test_subject_not_in_report_returns_unsupported(glucose_report):
    r = verify_grounded(
        _gc("L-carnitine has molecular formula C7H15NO3", "L-carnitine"),
        glucose_report,
    )
    assert r.verdict == ClaimVerdict.UNSUPPORTED


def test_no_mappable_field_returns_unsupported(glucose_report):
    r = verify_grounded(
        _gc("D-Gulose is a central metabolic hub", "D-Gulose"),
        glucose_report,
    )
    assert r.verdict == ClaimVerdict.UNSUPPORTED
