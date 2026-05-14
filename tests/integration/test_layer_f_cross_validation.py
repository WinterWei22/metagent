"""End-to-end integration test for Layer F cross-validation.

These tests use the real SIRIUS CLI + the real CFM-ID Docker shim. They
are skipped by default — run with ``pytest --integration`` and the
``METAGENT_CFM_URL`` / ``SIRIUS_PATH`` environment variables set.

Two real fixtures:

* ``citric_acid_neg.json`` — exercises the NM-001 mitigation. Real
  SIRIUS predicts ``C4H6N3O6`` (wrong) for citric acid's sparse low-CE
  spectrum; the SIRIUS sanity check downgrades that to LOW_CONFIDENCE
  and the consensus defers to CFM-ID, which (running on the correct
  candidate SMILES) produces a sane match for the precursor m/z.

* ``glutamyltyrosine_neg.json`` — control: SIRIUS gets the formula
  right (C14H18N2O6 matches truth), so cross-validation produces an
  ordinary SUPPORTED verdict.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from schemas.common import Candidate, Spectrum
from schemas.report import CandidateReport, IdentificationReport
from verifier.layers.peak_mechanistic import (
    ToolResult,
    reset_cfmid_cache,
    verify_peak_mechanistic,
)
from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim


_NEG_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "spectra" / "negative_mode"


def _has_sirius() -> bool:
    """Return True iff SIRIUS CLI is on PATH or METAGENT_SIRIUS_PATH points at it."""
    import os

    configured = os.environ.get("METAGENT_SIRIUS_PATH") or os.environ.get("SIRIUS_PATH")
    if configured and Path(configured).exists():
        return True
    return shutil.which("sirius") is not None


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_cfmid_cache()
    yield
    reset_cfmid_cache()


def _build_report(fixture_path: Path) -> IdentificationReport:
    data = json.loads(fixture_path.read_text())
    raw_mzs = [float(p[0]) for p in data["peaks"]]
    raw_intensities = [float(p[1]) for p in data["peaks"]]
    max_intensity = max(raw_intensities) or 1.0
    mzs = sorted(raw_mzs)
    intensities = [raw_intensities[raw_mzs.index(mz)] / max_intensity for mz in mzs]
    spectrum = Spectrum(
        mz=mzs,
        intensity=intensities,
        precursor_mz=float(data["precursor_mz"]),
        adduct=data["adduct"],
        ionization_mode=data["ionization_mode"],
        collision_energy=(
            float(data["collision_energy"])
            if data.get("collision_energy") is not None
            else None
        ),
    )
    candidate = Candidate(
        smiles=data["smiles"],
        name=data["compound_name"],
        source="library",
        score=0.95,
        source_id=f"fixture:{data['compound_name']}",
        explain="negative-mode spike fixture",
    )
    return IdentificationReport(
        experimental_spectrum=spectrum,
        preprocess_quality_flag="sparse",
        neutral_mass_computed=float(data["precursor_mz"]) + 1.00728,
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
                evidence_score=0.85,
                notes=[],
            )
        ],
        pipeline_version="integration-test",
        tool_versions={},
        warnings=[],
    )


def _peak_claim(mz: float, text: str = None) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_text=text or f"The peak at m/z {mz:.4f} is a fragment ion of the precursor.",
        subject="precursor",
        claim_type=ClaimType.PEAK_MECHANISTIC,
        classifier_source="rule",
        peak_mz=mz,
    )


@pytest.mark.requires_cfm_id
class TestLayerFCrossValidationReal:
    """Real-backend integration. Skips unless SIRIUS + CFM-ID are both up."""

    @pytest.fixture(autouse=True)
    def _require(self, has_cfm_id):
        if not has_cfm_id:
            pytest.skip("CFM-ID shim unreachable at METAGENT_CFM_URL")
        if not _has_sirius():
            pytest.skip(
                "SIRIUS CLI not on PATH; set METAGENT_SIRIUS_PATH or install sirius."
            )

    def test_citric_acid_nm001_mitigation(self):
        """Real SIRIUS predicts wrong formula for citric acid; layer F downgrades.

        Documented in ``reports/spike/negative_mode_spike_2026-04-28.md`` §2.8:
        SIRIUS confidently predicts ``C4H6N3O6`` (wrong) for citric acid's
        21-peak / CE 6V spectrum. Pre-fix: layer F returned SUPPORTED
        because SIRIUS' tree found a fragment at the precursor m/z. Post-fix:
        the SIRIUS sanity check fails (C diff 2, N diff 3, O diff 1) so
        SIRIUS is LOW_CONFIDENCE; CFM-ID drives the consensus.
        """
        report = _build_report(_NEG_FIXTURE_DIR / "citric_acid_neg.json")
        # The precursor itself — m/z 191.0194 in the fixture.
        result = verify_peak_mechanistic(
            _peak_claim(191.0194),
            report,
        )
        # The headline assertion: SIRIUS' formula is unreliable, so it
        # MUST be downgraded to LOW_CONFIDENCE rather than driving the
        # verdict. This is the NM-001 fix.
        assert result.tool_evidence is not None
        sirius_evidence = result.tool_evidence["sirius"]
        assert sirius_evidence["sanity_check_passed"] is False, (
            f"Expected SIRIUS sanity check to fail on citric_acid_neg "
            f"(C4H6N3O6 vs C6H8O7), got predicted_formula="
            f"{sirius_evidence.get('predicted_formula')!r}"
        )
        assert sirius_evidence["result"] == ToolResult.LOW_CONFIDENCE.value
        # Either CFM-ID drove the verdict (SUPPORTED / CONTRADICTED /
        # UNSUPPORTED) or both tools were unreliable (NEEDS_HUMAN_REVIEW).
        # All four are acceptable post-fix outcomes; the unacceptable
        # outcome would be SUPPORTED *with* SIRIUS driving it (which is
        # what the pre-fix code did).
        assert result.verdict in {
            ClaimVerdict.SUPPORTED,
            ClaimVerdict.CONTRADICTED,
            ClaimVerdict.UNSUPPORTED,
            ClaimVerdict.NEEDS_HUMAN_REVIEW,
        }
        # The consensus label must reflect that SIRIUS was downgraded.
        assert result.tool_evidence["consensus"] in {
            "cfmid_drives_low_confidence_sirius",
            "sirius_low_confidence_no_cfmid",
            "both_low_confidence",
        }

    def test_glutamyltyrosine_supported_unchanged(self):
        """Control: SIRIUS gets the formula right, both tools agree → SUPPORTED.

        On the 39-peak glutamyltyrosine spectrum SIRIUS correctly predicts
        ``C14H18N2O6`` (matches truth). The sanity check passes and both
        tools are expected to support a precursor-m/z claim.
        """
        report = _build_report(_NEG_FIXTURE_DIR / "glutamyltyrosine_neg.json")
        result = verify_peak_mechanistic(
            _peak_claim(309.1092),
            report,
        )
        assert result.tool_evidence is not None
        sirius_evidence = result.tool_evidence["sirius"]
        # SIRIUS sanity check should pass — predicted formula equals
        # candidate formula.
        assert sirius_evidence["sanity_check_passed"] is True, (
            f"Expected SIRIUS to pass sanity check on glutamyltyrosine, "
            f"got predicted_formula={sirius_evidence.get('predicted_formula')!r}"
        )
        # Verdict should be SUPPORTED (either by both tools agreeing or
        # by SIRIUS alone if CFM-ID happens not to predict 309.1092).
        assert result.verdict == ClaimVerdict.SUPPORTED
