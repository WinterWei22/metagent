"""Unit tests for Layer C — biological (Type 3) claim verification."""
from __future__ import annotations

import pytest

from verifier.layers.biological import verify_biological
from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim


def _bc(text, subj=None):
    return ClassifiedClaim(
        claim_text=text, subject=subj,
        claim_type=ClaimType.BIOLOGICAL, classifier_source="rule",
    )


# ---------------------------------------------------------------------------
# H3 — the pathway-names-supported case
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "D-Gulose appears in galactose metabolism",
        "D-Gulose appears in galactosemia",
        "D-Gulose appears in Fabry disease pathway",
    ],
)
def test_H3_supported_pathway_phrases(glucose_report, text):
    r = verify_biological(_bc(text, "D-Gulose"), glucose_report)
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_H4_supported_via_pathway_id(caffeine_report):
    r = verify_biological(
        _bc("Caffeine maps to KEGG pathway map00232", "Caffeine"),
        caffeine_report,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


# ---------------------------------------------------------------------------
# Hallucinated pathway names → UNSUPPORTED
# ---------------------------------------------------------------------------


def test_unsupported_hallucinated_pathway(glucose_report):
    r = verify_biological(
        _bc("D-Gulose appears in serotonin pathway", "D-Gulose"),
        glucose_report,
    )
    assert r.verdict == ClaimVerdict.UNSUPPORTED


# ---------------------------------------------------------------------------
# Neighbour / cooccurrence claims — ALWAYS UNVERIFIABLE_V0 (P-2/3/4/6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "D-Gulose is upstream of glucose-1-phosphate",
        "D-Gulose has cooccurrence with caffeine",
        "The downstream neighbours include fructose",
    ],
)
def test_neighbour_and_cooccurrence_are_unverifiable(glucose_report, text):
    r = verify_biological(_bc(text, "D-Gulose"), glucose_report)
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


# ---------------------------------------------------------------------------
# Subject-resolution edge cases
# ---------------------------------------------------------------------------


def test_subject_not_in_report_is_unverifiable(glucose_report):
    r = verify_biological(
        _bc("Histamine appears in galactose metabolism", "Histamine"),
        glucose_report,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_pathway_context_none_is_unverifiable(lcarnitine_report):
    # Every candidate in lcarnitine_report has pathway_context=None
    r = verify_biological(
        _bc("2-[2-hydroxyethyl(methyl)amino]ethyl acetate appears in acetyl metabolism",
            "2-[2-hydroxyethyl(methyl)amino]ethyl acetate"),
        lcarnitine_report,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_no_pathway_id_or_phrase_is_unverifiable(glucose_report):
    r = verify_biological(
        _bc("Some biological context applies", "D-Gulose"),
        glucose_report,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_subject_none_scans_all_candidates(glucose_report):
    # "Galactose Metabolism" is in D-Gulose's pathways; subject=None falls
    # back to scanning every candidate — should still find it.
    r = verify_biological(_bc("Galactose metabolism is referenced", None),
                          glucose_report)
    assert r.verdict == ClaimVerdict.SUPPORTED
