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
# Neighbour-membership verification — re-enabled after Track D
# P-2 (afd044f), P-3 (8432cbe), P-4 (4e968fa), P-6 (90257f2/9bebd3a) fixes
# ---------------------------------------------------------------------------


def _build_glucose_with_neighbours():
    """A glucose-shaped report with non-empty neighbour lists. Mirrors
    the production RaMP shape: ``hmdb:HMDB######`` / ``kegg:C#####``
    prefix-tagged IDs, post-P-3 fix."""
    from schemas.common import Candidate, PathwayEntry, Spectrum
    from schemas.molecule import MetaboliteInfoResponse
    from schemas.pathway import PathwayContextResponse
    from schemas.report import CandidateReport, IdentificationReport

    pathways = PathwayContextResponse(
        pathways=[
            PathwayEntry(id="hsa00010", name="Glycolysis / Gluconeogenesis",
                         source="kegg", hit_count=1, url="X"),
        ],
        # post-P-2: up != down; post-P-3: hmdb:/kegg: only; post-P-4:
        # no cofactors. Pyruvate is downstream of glucose in glycolysis.
        upstream_neighbours=["hmdb:HMDB0000538", "kegg:C00111"],
        downstream_neighbours=["hmdb:HMDB0000243", "kegg:C00022"],  # pyruvate
        cooccurrence_score=0.0, plausibility_summary="X", explain="X",
    )
    cand = CandidateReport(
        candidate=Candidate(smiles="X", name="Glucose", source="library",
                            score=0.83, source_id="X", explain="hit"),
        prefilter_match=None,
        metabolite_info=MetaboliteInfoResponse(
            found=True, primary_name="Glucose",
            molecular_formula="C6H12O6", explain="hit"),
        pathway_context=pathways,
        predicted_spectrum_cosine=0.5, predicted_model_version="X",
        mass_match_indicator=1.0, pathway_presence_indicator=1.0,
        evidence_score=0.7, notes=[],
    )
    spectrum = Spectrum(mz=[181.07], intensity=[1.0], precursor_mz=181.07,
                       adduct="[M+H]+", ionization_mode="positive",
                       collision_energy=20.0)
    return IdentificationReport(
        experimental_spectrum=spectrum, preprocess_quality_flag="sparse",
        neutral_mass_computed=180.06, n_prefilter_candidates=1,
        n_library_candidates=1, n_generated_candidates=0,
        candidates=[cand], pipeline_version="X",
        tool_versions={}, warnings=[],
    )


def test_downstream_neighbour_membership_supported():
    """Pyruvate (HMDB0000243) IS downstream of glucose in our fixture.
    Direction-aware match: 'downstream' + ID present in
    downstream_neighbours → SUPPORTED."""
    report = _build_glucose_with_neighbours()
    r = verify_biological(
        _bc("Glucose has HMDB0000243 as a downstream neighbour", "Glucose"),
        report,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert "downstream_neighbours" in r.source_field


def test_upstream_neighbour_membership_supported():
    """HMDB0000538 IS upstream of glucose. Direction-aware match
    succeeds."""
    report = _build_glucose_with_neighbours()
    r = verify_biological(
        _bc("Glucose has HMDB0000538 as an upstream neighbour", "Glucose"),
        report,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert "upstream_neighbours" in r.source_field


def test_direction_mismatch_is_contradicted():
    """Pyruvate is downstream; if the LLM claims it's upstream, that's a
    real CONTRADICTED — the source actively disagrees."""
    report = _build_glucose_with_neighbours()
    r = verify_biological(
        _bc("Glucose has HMDB0000243 as an upstream neighbour", "Glucose"),
        report,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED
    assert "downstream" in r.evidence  # actual position


def test_either_direction_match_via_neighbour_keyword():
    """A direction-agnostic 'X is in Y's neighbours' claim resolves
    when the ID appears in either upstream OR downstream."""
    report = _build_glucose_with_neighbours()
    r = verify_biological(
        _bc("Glucose has HMDB0000243 in its neighbours", "Glucose"),
        report,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_neighbour_id_not_in_any_list_is_unsupported():
    """An ID that the LLM hallucinated as a neighbour but isn't in
    either list → UNSUPPORTED (not UNVERIFIABLE)."""
    report = _build_glucose_with_neighbours()
    r = verify_biological(
        _bc("Glucose has HMDB9999999 as a downstream neighbour", "Glucose"),
        report,
    )
    assert r.verdict == ClaimVerdict.UNSUPPORTED


def test_name_only_neighbour_claim_is_unverifiable():
    """No HMDB / KEGG ID in the claim → no v0 name-to-ID resolver in
    Layer C → UNVERIFIABLE_V0."""
    report = _build_glucose_with_neighbours()
    r = verify_biological(
        _bc("Glucose is upstream of pyruvate", "Glucose"),
        report,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_cooccurrence_claims_remain_unverifiable():
    """P-6 fixed the score, but v0 still has no qualifier-to-threshold
    mapping for 'high cooccurrence' / 'moderate cooccurrence'."""
    report = _build_glucose_with_neighbours()
    for text in [
        "Glucose has high cooccurrence with caffeine",
        "Co-occurrence with citrate is observed",
    ]:
        r = verify_biological(_bc(text, "Glucose"), report)
        assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0, (
            f"Cooccurrence text {text!r} should still be UNVERIFIABLE_V0; "
            f"got {r.verdict}"
        )


def test_neighbour_claim_with_pathway_context_none_is_unverifiable(glucose_report):
    """If the subject's pathway_context is None (degraded), neighbour
    membership cannot be checked at all → UNVERIFIABLE_V0."""
    # glucose_report fixture's index-1 candidate has pathway_context=None
    r = verify_biological(
        _bc("Glucose has HMDB0000243 as a downstream neighbour", "Glucose"),
        glucose_report,
    )
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
