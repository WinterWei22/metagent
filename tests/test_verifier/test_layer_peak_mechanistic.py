"""Unit tests for Layer F — peak mechanistic verification."""
from __future__ import annotations

from types import SimpleNamespace

from schemas.common import Candidate, Spectrum
from schemas.report import CandidateReport, IdentificationReport
from verifier.claim_classifier import classify_claims
from verifier.layers.peak_mechanistic import verify_peak_mechanistic
from verifier.schemas import (
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    ExtractedClaim,
)


class SiriusNoFormulaError(Exception):
    pass


class SiriusNotInstalledError(Exception):
    pass


def _pc(text: str, peak_mz: float, neutral_loss: str | None = None):
    return ClassifiedClaim(
        claim_text=text,
        subject="Glucose",
        claim_type=ClaimType.PEAK_MECHANISTIC,
        classifier_source="rule",
        peak_mz=peak_mz,
        neutral_loss=neutral_loss,
    )


def _report(mz_values: list[float]) -> IdentificationReport:
    candidate = Candidate(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        name="Glucose",
        source="library",
        score=0.95,
        source_id="X:glucose",
        explain="fixture",
    )
    return IdentificationReport(
        experimental_spectrum=Spectrum(
            mz=mz_values,
            intensity=[1.0 for _ in mz_values],
            precursor_mz=181.0707,
            adduct="[M+H]+",
            ionization_mode="positive",
            collision_energy=20.0,
        ),
        preprocess_quality_flag="good",
        neutral_mass_computed=180.0634,
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


def _sirius_response(*, fragment_mz: float = 163.0601, neutral_loss: str = "H2O"):
    fragment = SimpleNamespace(
        mz_observed=fragment_mz,
        formula="C6H10O5",
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
        fragments=[
            fragment
        ],
        tree_node_count=1,
        lookup_fragment=lookup_fragment,
    )


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
