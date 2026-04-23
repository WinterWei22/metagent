"""Verifier-readiness tests for Track E — predict_spectrum.

Each check ships with a mock path (canned CFM-ID stdout via requests_mock)
and a real path (calls the live container at METAGENT_CFM_URL, gated on
the `requires_cfm_id` marker). Mock path runs always; real path skips if
the shim is not reachable.

The invariants under test mirror the audit brief:
  - Glucose and caffeine roundtrips produce expected peaks.
  - Back-to-back identical requests return byte-identical responses
    (determinism — critical for the verifier to re-hash reports).
  - RDKit-invalid SMILES raise `InvalidSmilesError` BEFORE any HTTP call
    — verified with a tripwire on cfm_client.predict.
  - `model_version` is pinned in every response.
  - Timeouts bound the call regardless of what the container does.
  - The cross-tool chain fetch_metabolite_info → predict_spectrum accepts
    the stored SMILES without modification.
"""
from __future__ import annotations

import os
import sys
import time
import unittest.mock as mock
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest
import requests
import requests_mock as rm

from schemas.molecule import MetaboliteInfoRequest
from schemas.spectrum import PredictSpectrumRequest
from tools.metabolite_info import fetch_metabolite_info
from tools.spectrum_predict import (
    CfmUnavailableError,
    InvalidSmilesError,
    PredictionTimeoutError,
    predict_spectrum,
)
from tools.spectrum_predict import cfm_client
from tools.spectrum_predict.cfm_client import DEFAULT_URL

from tests.integration.conftest import cfm_mock_body


_GLUCOSE = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"
_CAFFEINE = "CN1C=NC2=C1C(=O)N(C)C(=O)N2C"


@pytest.fixture(autouse=True)
def _isolate_cfm_url(monkeypatch, request):
    """Mock-path tests point the client at DEFAULT_URL; real-path tests
    keep whatever the operator has configured in METAGENT_CFM_URL.

    We key on the `requires_cfm_id` marker — if present, leave the env
    var alone; otherwise pin to the default URL so requests_mock can
    intercept.
    """
    if request.node.get_closest_marker("requires_cfm_id"):
        return
    monkeypatch.setenv("METAGENT_CFM_URL", DEFAULT_URL)


# ---------------------------------------------------------------------------
# Test 1 & 2: roundtrip glucose + caffeine.
# ---------------------------------------------------------------------------


class TestPredictRoundtripMock:
    def test_glucose(self):
        req = PredictSpectrumRequest(
            smiles=_GLUCOSE, adduct="[M+H]+", ionization_mode="positive",
        )
        with rm.Mocker() as m:
            m.post(f"{DEFAULT_URL}/predict", json=cfm_mock_body(_GLUCOSE))
            resp = predict_spectrum(req)

        assert resp.predicted.mz, "glucose union spectrum must be non-empty"
        # [M+H-H2O]+ at 163.06 should survive the union.
        assert any(abs(mz - 163.0601) < 0.01 for mz in resp.predicted.mz), (
            f"expected [M+H-H2O]+ near 163.06, got {resp.predicted.mz[:5]}"
        )
        assert set(resp.per_energy.keys()) == {10.0, 20.0, 40.0}
        assert max(resp.predicted.intensity) == 1.0
        assert resp.model_version.startswith("cfm-id-")

    def test_caffeine(self):
        req = PredictSpectrumRequest(
            smiles=_CAFFEINE, adduct="[M+H]+", ionization_mode="positive",
        )
        with rm.Mocker() as m:
            m.post(f"{DEFAULT_URL}/predict", json=cfm_mock_body(_CAFFEINE))
            resp = predict_spectrum(req)

        # Parent [M+H]+ at 195.09 and CH3N=C=O loss at 138.07.
        assert any(abs(mz - 195.0876) < 0.01 for mz in resp.predicted.mz)
        assert any(abs(mz - 138.0662) < 0.01 for mz in resp.predicted.mz)


@pytest.mark.requires_cfm_id
class TestPredictRoundtripReal:
    @pytest.fixture(autouse=True)
    def _require(self, has_cfm_id):
        if not has_cfm_id:
            pytest.skip(
                "CFM-ID shim unreachable at METAGENT_CFM_URL; "
                "start the container via docker/README_CFM.md."
            )

    def test_glucose(self):
        req = PredictSpectrumRequest(
            smiles=_GLUCOSE, adduct="[M+H]+", ionization_mode="positive",
        )
        resp = predict_spectrum(req)

        assert resp.model_version.startswith("cfm-id-")
        assert len(resp.predicted.mz) >= 5, "real CFM-ID should emit ≥5 peaks for glucose"
        # Precursor [M+H]+ near 181.07. Wide tolerance — CFM is not a
        # mass-accurate predictor.
        assert any(abs(mz - 181.07) < 2.0 for mz in resp.predicted.mz)
        # [M+H-H2O]+ in the 160-170 range is reliably present for glucose.
        assert any(160 <= mz <= 170 for mz in resp.predicted.mz)

    def test_caffeine(self):
        req = PredictSpectrumRequest(
            smiles=_CAFFEINE, adduct="[M+H]+", ionization_mode="positive",
        )
        resp = predict_spectrum(req)
        assert any(abs(mz - 195.09) < 2.0 for mz in resp.predicted.mz)
        # CH3N=C=O loss fragment — a canonical caffeine diagnostic.
        assert any(137 <= mz <= 139 for mz in resp.predicted.mz)


# ---------------------------------------------------------------------------
# Test 3: determinism.
# ---------------------------------------------------------------------------


class TestPredictDeterminismMock:
    def test_identical_requests_return_identical_spectra(self):
        req = PredictSpectrumRequest(
            smiles=_GLUCOSE, adduct="[M+H]+", ionization_mode="positive",
        )
        with rm.Mocker() as m:
            m.post(f"{DEFAULT_URL}/predict", json=cfm_mock_body(_GLUCOSE))
            r1 = predict_spectrum(req)
            r2 = predict_spectrum(req)

        assert r1.predicted.mz == r2.predicted.mz
        assert r1.predicted.intensity == r2.predicted.intensity
        assert r1.per_energy.keys() == r2.per_energy.keys()
        for ev in r1.per_energy:
            assert r1.per_energy[ev].mz == r2.per_energy[ev].mz
            assert r1.per_energy[ev].intensity == r2.per_energy[ev].intensity
        assert r1.model_version == r2.model_version


@pytest.mark.requires_cfm_id
class TestPredictDeterminismReal:
    @pytest.fixture(autouse=True)
    def _require(self, has_cfm_id):
        if not has_cfm_id:
            pytest.skip("CFM-ID shim unreachable at METAGENT_CFM_URL")

    def test_identical_requests_return_identical_spectra(self):
        req = PredictSpectrumRequest(
            smiles=_GLUCOSE, adduct="[M+H]+", ionization_mode="positive",
        )
        r1 = predict_spectrum(req)
        r2 = predict_spectrum(req)
        assert r1.predicted.mz == r2.predicted.mz, (
            "real CFM-ID determinism broken — the verifier will not be able "
            "to re-hash predicted spectra for audit."
        )
        assert r1.predicted.intensity == r2.predicted.intensity


# ---------------------------------------------------------------------------
# Test 4: invalid SMILES rejected BEFORE network.
# ---------------------------------------------------------------------------


class TestPredictRejectsInvalidSmilesBeforeNetwork:
    """No mock-vs-real split: the whole point is that the network is never
    touched. We install a tripwire on the client regardless of backend."""

    @pytest.mark.parametrize(
        "bad_smiles",
        [
            "banana",
            "C1CC",             # unclosed ring
            "[X]",              # nonsense atom
            "SELECT * FROM t",  # sqli-shaped
        ],
    )
    def test_invalid_smiles_skips_http(self, bad_smiles, monkeypatch):
        calls: list[tuple] = []

        def _tripwire(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError(
                "cfm_client.predict was called for an RDKit-invalid SMILES "
                f"({bad_smiles!r}). The guard in tools/spectrum_predict/"
                "tool.py must reject before the HTTP layer."
            )

        monkeypatch.setattr(cfm_client, "predict", _tripwire)

        with pytest.raises(InvalidSmilesError) as excinfo:
            predict_spectrum(PredictSpectrumRequest(
                smiles=bad_smiles, adduct="[M+H]+", ionization_mode="positive",
            ))
        assert excinfo.value.code == "PREDICT_INVALID_SMILES"
        assert calls == []


# ---------------------------------------------------------------------------
# Test 5: model_version always populated.
# ---------------------------------------------------------------------------


class TestModelVersionPresentMock:
    def test_model_version_is_non_empty(self):
        req = PredictSpectrumRequest(
            smiles=_GLUCOSE, adduct="[M+H]+", ionization_mode="positive",
        )
        with rm.Mocker() as m:
            m.post(f"{DEFAULT_URL}/predict", json=cfm_mock_body(_GLUCOSE))
            resp = predict_spectrum(req)
        assert isinstance(resp.model_version, str)
        assert resp.model_version  # non-empty
        assert len(resp.model_version) > 3, (
            "model_version must be specific enough to appear in audit reports"
        )

    def test_missing_model_version_raises(self):
        """A shim that forgets model_version is broken — the verifier relies
        on it to detect predictor upgrades."""
        req = PredictSpectrumRequest(
            smiles=_GLUCOSE, adduct="[M+H]+", ionization_mode="positive",
        )
        with rm.Mocker() as m:
            m.post(
                f"{DEFAULT_URL}/predict",
                json={"cfm_stdout": cfm_mock_body(_GLUCOSE)["cfm_stdout"]},
            )
            with pytest.raises(CfmUnavailableError):
                predict_spectrum(req)


@pytest.mark.requires_cfm_id
class TestModelVersionPresentReal:
    @pytest.fixture(autouse=True)
    def _require(self, has_cfm_id):
        if not has_cfm_id:
            pytest.skip("CFM-ID shim unreachable at METAGENT_CFM_URL")

    def test_model_version_is_non_empty(self):
        req = PredictSpectrumRequest(
            smiles=_GLUCOSE, adduct="[M+H]+", ionization_mode="positive",
        )
        resp = predict_spectrum(req)
        assert resp.model_version.startswith("cfm-id-")


# ---------------------------------------------------------------------------
# Test 6: timeout bounded.
# ---------------------------------------------------------------------------


class TestTimeoutBounded:
    """`requests.exceptions.Timeout` must translate to PredictionTimeoutError
    without the tool waiting longer than the configured timeout. We mock the
    timeout exception synchronously so the test stays fast."""

    def test_timeout_surface_as_typed_error(self):
        with rm.Mocker() as m:
            m.post(
                f"{DEFAULT_URL}/predict",
                exc=requests.exceptions.Timeout,
            )
            with pytest.raises(PredictionTimeoutError) as excinfo:
                predict_spectrum(PredictSpectrumRequest(
                    smiles=_GLUCOSE, adduct="[M+H]+", ionization_mode="positive",
                ))
        assert excinfo.value.recoverable is True
        assert excinfo.value.code == "PREDICT_TIMEOUT"

    def test_tool_does_not_wait_longer_than_expected(self):
        """Sanity: with a raising mock, total wall time must be sub-second."""
        req = PredictSpectrumRequest(
            smiles=_GLUCOSE, adduct="[M+H]+", ionization_mode="positive",
        )
        with rm.Mocker() as m:
            m.post(
                f"{DEFAULT_URL}/predict",
                exc=requests.exceptions.Timeout,
            )
            t0 = time.monotonic()
            with pytest.raises(PredictionTimeoutError):
                predict_spectrum(req)
            elapsed = time.monotonic() - t0
        assert elapsed < 2.0, (
            f"tool took {elapsed:.2f}s to surface a mocked Timeout — the "
            "synchronous translation in cfm_client.predict may be broken."
        )


# ---------------------------------------------------------------------------
# Test 7: cross-tool chain — fetch_metabolite_info → predict_spectrum.
# ---------------------------------------------------------------------------


class TestSmilesFromFetchMock:
    """Chain against the mock HMDB — verifies structural plumbing only."""

    def test_fetch_smiles_goes_into_predict_spectrum_unmodified(
        self, mock_hmdb_db, monkeypatch
    ):
        r = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier="HMDB0000122", id_type="hmdb")
        )
        assert r.found and r.smiles, "mock HMDB must seed glucose with SMILES"
        with rm.Mocker() as m:
            m.post(f"{DEFAULT_URL}/predict", json=cfm_mock_body(r.smiles))
            resp = predict_spectrum(PredictSpectrumRequest(
                smiles=r.smiles, adduct="[M+H]+", ionization_mode="positive",
            ))
        assert len(resp.predicted.mz) > 0


@pytest.mark.requires_hmdb_db
@pytest.mark.requires_cfm_id
class TestSmilesFromFetchReal:
    """Chain against the real backends: if the real HMDB returns a SMILES
    that CFM-ID cannot accept, the verifier pipeline is broken end-to-end.
    """

    @pytest.fixture(autouse=True)
    def _require(self, has_hmdb_db, has_cfm_id):
        if not has_hmdb_db:
            pytest.skip("HMDB SQLite not found at METAGENT_HMDB_PATH")
        if not has_cfm_id:
            pytest.skip("CFM-ID shim unreachable at METAGENT_CFM_URL")

    def test_fetch_smiles_goes_into_predict_spectrum_unmodified(self):
        r = fetch_metabolite_info(
            MetaboliteInfoRequest(identifier="HMDB0000122", id_type="hmdb")
        )
        assert r.found and r.smiles, "real HMDB must have a SMILES for glucose"
        resp = predict_spectrum(PredictSpectrumRequest(
            smiles=r.smiles, adduct="[M+H]+", ionization_mode="positive",
        ))
        assert len(resp.predicted.mz) >= 5
