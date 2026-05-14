"""Unit tests for Layer F — peak mechanistic verification with cross-validation."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from schemas.common import Candidate, Spectrum
from schemas.report import CandidateReport, IdentificationReport
from verifier.claim_classifier import classify_claims
from verifier.layers import peak_mechanistic
from verifier.layers.peak_mechanistic import (
    ToolResult,
    reset_cfmid_cache,
    verify_peak_mechanistic,
)
from verifier.schemas import (
    CandidateRef,
    ClaimExtractedFields,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    ExtractedClaim,
)


class SiriusNoFormulaError(Exception):
    pass


class SiriusNotInstalledError(Exception):
    pass


@pytest.fixture(autouse=True)
def _isolate_cfmid(monkeypatch):
    """Isolate every test from the live CFM-ID Docker shim.

    1. Clear the process-wide CFM-ID cache so cached results never leak
       across tests.
    2. Replace the auto-load CFM-ID entry point with a raise — tests
       that omit ``cfmid_fn`` get ``NO_DATA`` instead of an accidental
       live call.
    """
    reset_cfmid_cache()

    def _no_live_cfmid(_req):
        raise RuntimeError(
            "CFM-ID auto-load disabled in unit tests; pass cfmid_fn explicitly."
        )

    monkeypatch.setattr(peak_mechanistic, "_default_cfmid_fn", _no_live_cfmid)
    yield
    reset_cfmid_cache()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _pc(text: str, peak_mz: float, neutral_loss: str | None = None):
    return ClassifiedClaim(
        claim_text=text,
        subject="Glucose",
        claim_type=ClaimType.PEAK_MECHANISTIC,
        classifier_source="rule",
        peak_mz=peak_mz,
        neutral_loss=neutral_loss,
    )


def _report(
    mz_values: list[float],
    *,
    smiles: str = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
    name: str = "Glucose",
    precursor_mz: float = 181.0707,
    adduct: str = "[M+H]+",
    ionization_mode: str = "positive",
):
    candidate = Candidate(
        smiles=smiles,
        name=name,
        source="library",
        score=0.95,
        source_id=f"X:{name.lower()}",
        explain="fixture",
    )
    return IdentificationReport(
        experimental_spectrum=Spectrum(
            mz=mz_values,
            intensity=[1.0 for _ in mz_values],
            precursor_mz=precursor_mz,
            adduct=adduct,
            ionization_mode=ionization_mode,  # type: ignore[arg-type]
            collision_energy=20.0,
        ),
        preprocess_quality_flag="good",
        neutral_mass_computed=precursor_mz - 1.00728,
        n_prefilter_candidates=1,
        n_library_candidates=1,
        n_generated_candidates=0,
        candidates=[
            CandidateReport(
                candidate=candidate,
                prefilter_match=None,
                metabolite_info=None,
                pathway_context=None,
                predicted_spectrum_cosine=None,
                predicted_model_version=None,
                mass_match_indicator=1.0,
                pathway_presence_indicator=0.0,
                evidence_score=0.9,
                notes=[],
            )
        ],
        pipeline_version="test",
        tool_versions={},
        warnings=[],
    )


def _sirius_response(
    *,
    predicted_formula: str = "C6H12O6",
    fragment_mz: float = 163.0601,
    neutral_loss: str = "H2O",
    fragment_formula: str = "C6H10O5",
):
    """Construct a SimpleNamespace shaped like ``SiriusAnnotateResponse``.

    ``predicted_formula`` defaults to ``C6H12O6`` so the SIRIUS sanity
    check passes against the glucose fixture by default. Override it to
    exercise the NM-001 mitigation.
    """
    fragment = SimpleNamespace(
        mz_observed=fragment_mz,
        formula=fragment_formula,
        formula_score=0.88,
        neutral_loss=neutral_loss,
        neutral_loss_formula=neutral_loss,
        intensity=100.0,
        depth=1,
    )

    def lookup_fragment(mz: float, tolerance_ppm: float = 5.0):
        ppm = abs(fragment.mz_observed - mz) / mz * 1e6
        if ppm <= tolerance_ppm:
            return fragment
        return None

    return SimpleNamespace(
        predicted_formula=predicted_formula,
        formula_score=0.92,
        fragments=[fragment],
        tree_node_count=1,
        lookup_fragment=lookup_fragment,
    )


def _cfmid_response(
    *,
    predicted_mzs: list[float],
    precursor_mz: float = 181.0707,
    adduct: str = "[M+H]+",
    ionization_mode: str = "positive",
):
    """Construct a SimpleNamespace shaped like ``PredictSpectrumResponse``."""
    intensities = [1.0 for _ in predicted_mzs] or [1.0]
    return SimpleNamespace(
        predicted=SimpleNamespace(
            mz=list(predicted_mzs),
            intensity=intensities,
            precursor_mz=precursor_mz,
            adduct=adduct,
            ionization_mode=ionization_mode,
            collision_energy=None,
        ),
        per_energy={},
        model_version="cfm-id-mock",
        explain="mock",
    )


# ---------------------------------------------------------------------------
# Pre-cross-validation tests (still must pass — semantics preserved when
# CFM-ID returns NO_DATA, which is the default for these tests)
# ---------------------------------------------------------------------------


def test_peak_exists_in_spectrum_supported():
    r = verify_peak_mechanistic(
        _pc("The peak at m/z 163.06 corresponds to a water-loss fragment", 163.06),
        _report([181.0707, 163.0601, 145.0495]),
        sirius_fn=lambda _req: _sirius_response(),
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_peak_not_in_spectrum_contradicted():
    def fail_if_called(_req):  # pragma: no cover
        raise AssertionError("SIRIUS should not be called")

    r = verify_peak_mechanistic(
        _pc("The peak at m/z 999.99 is a fragment ion", 999.99),
        _report([181.0707, 163.0601]),
        sirius_fn=fail_if_called,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED


def test_sirius_no_fragment_at_mz_unsupported():
    r = verify_peak_mechanistic(
        _pc("The peak at m/z 163.06 is a fragment ion", 163.06),
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(fragment_mz=145.0495),
    )
    assert r.verdict == ClaimVerdict.UNSUPPORTED


def test_neutral_loss_mismatch_contradicted():
    r = verify_peak_mechanistic(
        _pc("The peak at m/z 163.06 reflects neutral loss of NH3", 163.06, "NH3"),
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(neutral_loss="H2O"),
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED
    assert r.correction == "H2O"


def test_neutral_loss_alias_match():
    r = verify_peak_mechanistic(
        _pc("The peak at m/z 163.06 is a water loss fragment", 163.06, "water"),
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(neutral_loss="H2O"),
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_peak_claim_uses_typed_mz_and_neutral_loss():
    claim = ClassifiedClaim(
        claim_text="This typed peak claim has no legacy peak_mz",
        subject="Glucose",
        claim_type=ClaimType.PEAK_MECHANISTIC,
        classifier_source="rule",
        candidate_ref=CandidateRef(
            index=0,
            path="candidates[0]",
            name="Glucose",
            smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        ),
        extracted_fields=ClaimExtractedFields(mz=163.06, neutral_loss="water"),
    )
    r = verify_peak_mechanistic(
        claim,
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(neutral_loss="H2O"),
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert r.tool_called == "sirius"
    assert r.candidate_ref.smiles


def test_sirius_not_installed_unverifiable():
    def missing(_req):
        raise SiriusNotInstalledError("missing")

    r = verify_peak_mechanistic(
        _pc("The peak at m/z 163.06 is a fragment ion", 163.06),
        _report([181.0707, 163.0601]),
        sirius_fn=missing,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_too_few_peaks_unverifiable():
    def no_formula(_req):
        raise SiriusNoFormulaError("too few peaks")

    r = verify_peak_mechanistic(
        _pc("The peak at m/z 163.06 is a fragment ion", 163.06),
        _report([181.0707, 163.0601, 145.0495]),
        sirius_fn=no_formula,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_classifier_routes_mz_fragment_claim_to_peak_mechanistic():
    classified, llm_calls = classify_claims(
        [
            ExtractedClaim(
                claim_text="m/z 138.07 is the imidazole ring fragment of caffeine",
                subject="caffeine",
            )
        ],
        trace_id="test",
    )
    assert llm_calls == 0
    assert classified[0].claim_type == ClaimType.PEAK_MECHANISTIC
    assert classified[0].peak_mz == 138.07


def test_classifier_keeps_precursor_neutral_mass_claim_grounded():
    classified, llm_calls = classify_claims(
        [
            ExtractedClaim(
                claim_text=(
                    "The precursor m/z 195.0877 [M+H]+ corresponds to a "
                    "neutral mass of 194.08 Da"
                ),
                subject="caffeine",
            )
        ],
        trace_id="test",
    )
    assert llm_calls == 0
    assert classified[0].claim_type == ClaimType.GROUNDED


# ---------------------------------------------------------------------------
# New cross-validation tests
# ---------------------------------------------------------------------------


def test_both_tools_agree_supported():
    """SIRIUS MATCHES + CFM-ID MATCHES → SUPPORTED."""
    r = verify_peak_mechanistic(
        _pc("Peak at m/z 163.06 is a water-loss fragment", 163.06, "H2O"),
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(),
        cfmid_fn=lambda _req: _cfmid_response(predicted_mzs=[181.0707, 163.0601]),
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert r.tool_called == "sirius+cfmid"
    assert r.tool_evidence["consensus"] == "agree_supported"


def test_both_tools_agree_contradicted():
    """SIRIUS MISMATCHES (NL wrong) + CFM-ID MISMATCHES (precursor delta wrong) → CONTRADICTED."""
    # CFM-ID has a peak at 163.06 (so MATCHES on m/z), but the precursor−fragment
    # delta is 18.0106 (H2O), not the claimed 17.0265 (NH3) → MISMATCHES on NL.
    r = verify_peak_mechanistic(
        _pc("Peak at m/z 163.06 reflects loss of NH3", 163.06, "NH3"),
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(neutral_loss="H2O"),
        cfmid_fn=lambda _req: _cfmid_response(predicted_mzs=[181.0707, 163.0601]),
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED
    assert r.tool_evidence["consensus"] == "agree_contradicted"
    assert r.correction == "H2O"


def test_tools_disagree_sirius_yes_cfmid_no():
    """SIRIUS MATCHES + CFM-ID NOT_FOUND → NEEDS_HUMAN_REVIEW."""
    r = verify_peak_mechanistic(
        _pc("Peak at m/z 163.06 is a water-loss fragment", 163.06, "H2O"),
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(),
        # CFM-ID predicts a different peak — no match at 163.06.
        cfmid_fn=lambda _req: _cfmid_response(predicted_mzs=[181.0707, 145.0495]),
    )
    assert r.verdict == ClaimVerdict.NEEDS_HUMAN_REVIEW
    assert r.tool_evidence["consensus"] == "tools_disagree"
    assert r.correction is None


def test_tools_disagree_sirius_no_cfmid_yes():
    """SIRIUS NOT_FOUND + CFM-ID MATCHES → NEEDS_HUMAN_REVIEW."""
    # SIRIUS' tree has fragment at 145.0495, claim is at 163.06 → NOT_FOUND.
    # CFM-ID predicts 163.06.
    r = verify_peak_mechanistic(
        _pc("Peak at m/z 163.06 is a water-loss fragment", 163.06),
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(fragment_mz=145.0495),
        cfmid_fn=lambda _req: _cfmid_response(predicted_mzs=[181.0707, 163.0601]),
    )
    assert r.verdict == ClaimVerdict.NEEDS_HUMAN_REVIEW
    assert r.tool_evidence["consensus"] == "tools_disagree"


def test_only_sirius_available():
    """SIRIUS MATCHES + CFM-ID NO_DATA → SUPPORTED with caveat."""
    def cfmid_fails(_req):
        raise RuntimeError("CFM-ID Docker shim down")

    r = verify_peak_mechanistic(
        _pc("Peak at m/z 163.06 is a water-loss fragment", 163.06, "H2O"),
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(),
        cfmid_fn=cfmid_fails,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert r.tool_evidence["consensus"] == "sirius_only_supported"
    assert r.tool_called == "sirius"


def test_only_cfmid_available():
    """SIRIUS NO_DATA + CFM-ID MATCHES → SUPPORTED with caveat."""
    def sirius_no_formula(_req):
        raise SiriusNoFormulaError("spectrum too sparse")

    r = verify_peak_mechanistic(
        _pc("Peak at m/z 163.06 is a fragment ion", 163.06),
        _report([181.0707, 163.0601]),
        sirius_fn=sirius_no_formula,
        cfmid_fn=lambda _req: _cfmid_response(predicted_mzs=[181.0707, 163.0601]),
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert r.tool_evidence["consensus"] == "cfmid_only_supported"
    assert r.tool_called == "cfmid"


def test_neither_tool_available():
    """SIRIUS NO_DATA + CFM-ID NO_DATA → UNVERIFIABLE_V0."""
    def sirius_missing(_req):
        raise SiriusNotInstalledError("not installed")

    def cfmid_missing(_req):
        raise RuntimeError("Docker down")

    r = verify_peak_mechanistic(
        _pc("Peak at m/z 163.06 is a fragment ion", 163.06),
        _report([181.0707, 163.0601]),
        sirius_fn=sirius_missing,
        cfmid_fn=cfmid_missing,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert r.tool_evidence["consensus"] == "neither_available"


def test_sirius_sanity_check_catches_wrong_formula():
    """NM-001 mitigation: SIRIUS predicts wrong formula for citric acid.

    SIRIUS says ``C4H6N3O6`` for citric acid (truth ``C6H8O7``); element
    diff is C: −2, H: −2, N: +3, O: −1, exceeding the threshold of 2.
    SIRIUS is downgraded to LOW_CONFIDENCE and CFM-ID drives the
    consensus.
    """
    citric_report = _report(
        [191.0190, 111.0085, 87.0086],
        smiles="OC(=O)CC(O)(C(=O)O)CC(=O)O",
        name="CitricAcid",
        precursor_mz=191.0190,
        adduct="[M-H]-",
        ionization_mode="negative",
    )
    r = verify_peak_mechanistic(
        _pc("Peak at m/z 191.0190 is the precursor", 191.0190),
        citric_report,
        sirius_fn=lambda _req: _sirius_response(
            predicted_formula="C4H6N3O6",  # NM-001 wrong call
            fragment_mz=191.0190,
        ),
        cfmid_fn=lambda _req: _cfmid_response(
            predicted_mzs=[191.0190, 87.0086],
            precursor_mz=191.0190,
            adduct="[M-H]-",
            ionization_mode="negative",
        ),
    )
    # SIRIUS LOW_CONFIDENCE + CFM-ID MATCHES → SUPPORTED, but driven by CFM-ID.
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert r.tool_evidence["consensus"] == "cfmid_drives_low_confidence_sirius"
    assert r.tool_evidence["sirius"]["sanity_check_passed"] is False
    assert r.tool_evidence["sirius"]["result"] == ToolResult.LOW_CONFIDENCE.value


def test_sirius_sanity_check_passes_close_formula():
    """SIRIUS' formula differs by ≤ 2 atoms in every element → sane."""
    # Candidate is glucose (C6H12O6); SIRIUS predicts C6H10O6 (H diff 2,
    # well within threshold). Sanity check passes.
    r = verify_peak_mechanistic(
        _pc("Peak at m/z 163.06 is a water-loss fragment", 163.06, "H2O"),
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(
            predicted_formula="C6H10O6",
        ),
        cfmid_fn=lambda _req: _cfmid_response(predicted_mzs=[181.0707, 163.0601]),
    )
    assert r.tool_evidence["sirius"]["sanity_check_passed"] is True
    assert r.tool_evidence["sirius"]["result"] == ToolResult.MATCHES.value
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_tool_evidence_populated():
    """Verify ``tool_evidence`` is fully populated for cross-validated claims."""
    r = verify_peak_mechanistic(
        _pc("Peak at m/z 163.06 is a water-loss fragment", 163.06, "H2O"),
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(),
        cfmid_fn=lambda _req: _cfmid_response(predicted_mzs=[181.0707, 163.0601]),
    )
    te = r.tool_evidence
    assert te is not None
    assert "sirius" in te and "cfmid" in te
    assert "consensus" in te and "rationale" in te
    assert te["sirius"]["result"] == ToolResult.MATCHES.value
    assert te["sirius"]["predicted_formula"] == "C6H12O6"
    assert te["sirius"]["fragment_found"] is True
    assert te["cfmid"]["result"] == ToolResult.MATCHES.value
    assert te["cfmid"]["predicted_peak_count"] == 2
    assert te["cfmid"]["model_version"] == "cfm-id-mock"


def test_backward_compat_no_cfmid():
    """When ``cfmid_fn`` is None and auto-load fails, behaves like SIRIUS-only.

    The autouse fixture monkey-patches ``_default_cfmid_fn`` to raise,
    which reproduces the production scenario where the CFM-ID Docker
    shim is unreachable. The verifier should still produce a verdict
    from SIRIUS alone, just with the ``sirius_only_*`` consensus label.
    """
    r = verify_peak_mechanistic(
        _pc("Peak at m/z 163.06 is a water-loss fragment", 163.06, "H2O"),
        _report([181.0707, 163.0601]),
        sirius_fn=lambda _req: _sirius_response(),
        # cfmid_fn omitted → defaults to None → auto-load → raises → NO_DATA
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert r.tool_evidence["consensus"] == "sirius_only_supported"
    assert r.tool_called == "sirius"
    assert r.tool_evidence["cfmid"]["result"] == ToolResult.NO_DATA.value
