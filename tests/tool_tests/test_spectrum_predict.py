"""Unit tests for Track E — ``predict_spectrum``.

Covers every case listed in docs/TOOL_CONTRACTS.md → Tool 7 plus the bullet
list in prompts/track_E_predict_spectrum.md:

    1. Glucose prediction produces a non-empty spectrum with an expected peak.
    2. Invalid SMILES raises InvalidSmilesError *before* the HTTP call.
    3. Timeout on the HTTP call raises PredictionTimeoutError.
    4. Refused connection raises CfmUnavailableError.
    5. model_version is always non-empty in successful responses.
    6. Integration test against a live METAGENT_CFM_URL (skipped here).

No real network is used; every HTTP call is intercepted with ``requests_mock``.
No other tool is imported; no fixture file is modified.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Repo-root-on-sys.path hack used by every other track's unit tests.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest
import requests
import requests_mock as rm

from schemas.spectrum import PredictSpectrumRequest
from tools.spectrum_predict import (
    CfmUnavailableError,
    InvalidSmilesError,
    PredictionTimeoutError,
    predict_spectrum,
)
from tools.spectrum_predict.cfm_client import DEFAULT_URL
from tools.spectrum_predict.parser import parse_cfm_output

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "spectra"

# A realistic three-energy CFM-ID stdout for glucose under [M+H]+. The peak
# lists are lifted from the placeholder fixture (see tests/fixtures/spectra/
# glucose_pos.json) — every energy block shares the same peaks with different
# intensity scaling, which mirrors how CFM-ID actually behaves. The mass
# 163.0601 is [M+H-H2O]+, the canonical glucose fragment the test asserts on.
_GLUCOSE_CFM_STDOUT = """\
energy0
61.0284 5.0 12
73.0284 8.0 11
85.0284 15.0 9
109.0284 22.0 7
127.0390 38.0 5
145.0495 55.0 3
163.0601 100.0 1 2

energy1
61.0284 9.0
73.0284 12.0
85.0284 18.0
109.0284 25.0
127.0390 42.0
145.0495 68.0
163.0601 100.0

energy2
61.0284 30.0
73.0284 40.0
85.0284 55.0
109.0284 70.0
127.0390 82.0
145.0495 90.0
163.0601 100.0
"""

# Negative-mode counterpart. Same shape, but peaks reflect glucose [M-H]-
# fragmentation: the canonical 161.0455 is [M-H-H2O]-, plus the standard
# water-loss / ring-cleavage series documented in glucose_neg.json. Used
# by the negative-mode path tests so they don't have to fake [M+H]+ peaks.
_GLUCOSE_NEG_CFM_STDOUT = """\
energy0
59.0138 4.0
71.0138 6.0
89.0244 12.0
101.0244 18.0
119.0349 30.0
143.0349 50.0
161.0455 100.0

energy1
59.0138 8.0
71.0138 11.0
89.0244 16.0
101.0244 22.0
119.0349 35.0
143.0349 60.0
161.0455 100.0

energy2
59.0138 28.0
71.0138 36.0
89.0244 50.0
101.0244 65.0
119.0349 78.0
143.0349 88.0
161.0455 100.0
"""

_GLUCOSE_MODEL_VERSION = "cfm-id-4.0.0"


def _mock_success_body(stdout: str = _GLUCOSE_CFM_STDOUT,
                       version: str = _GLUCOSE_MODEL_VERSION) -> dict:
    return {"model_version": version, "cfm_stdout": stdout}


@pytest.fixture(autouse=True)
def _reset_cfm_url(monkeypatch):
    """Every test starts with a clean, deterministic METAGENT_CFM_URL."""
    monkeypatch.setenv("METAGENT_CFM_URL", DEFAULT_URL)


@pytest.fixture
def glucose_fixture() -> dict:
    with open(FIXTURES / "glucose_pos.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def glucose_neg_fixture() -> dict:
    """Negative-mode glucose fixture introduced 2026-04-28 alongside the
    Tracks A/B/C negative-mode acceptance.
    """
    with open(FIXTURES / "glucose_neg.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# 1. Glucose happy path
# ---------------------------------------------------------------------------


def test_glucose_prediction_contains_expected_fragment(glucose_fixture):
    """The [M+H-H2O]+ peak at 163.06 must survive preprocessing into the
    union spectrum. This is the canonical sanity check for CFM-ID glucose
    output; if it fails the parser or normaliser is wrong.
    """
    req = PredictSpectrumRequest(
        smiles=glucose_fixture["smiles"],
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    with rm.Mocker() as m:
        m.post(f"{DEFAULT_URL}/predict", json=_mock_success_body())
        resp = predict_spectrum(req)

    assert resp.predicted.mz, "union spectrum must have peaks"
    assert resp.predicted.ionization_mode == "positive"
    assert resp.predicted.adduct == "[M+H]+"
    # Allow a wide mass tolerance — CFM-ID is not perfect and the parser is
    # not responsible for exact-mass accuracy.
    assert any(
        abs(mz - 163.0601) < 0.01 for mz in resp.predicted.mz
    ), f"expected [M+H-H2O]+ peak near 163.06, got mz={resp.predicted.mz[:5]}..."

    # Base peak invariant: exactly one intensity equals 1.0 and all others
    # are in [0, 1].
    assert max(resp.predicted.intensity) == 1.0
    assert all(0.0 <= i <= 1.0 for i in resp.predicted.intensity)

    # per_energy populated for all three default CFM-ID energies.
    assert set(resp.per_energy.keys()) == {10.0, 20.0, 40.0}
    for ev, spec in resp.per_energy.items():
        assert spec.collision_energy == ev
        assert max(spec.intensity) == 1.0


def test_top_n_peaks_honoured():
    """top_n_peaks caps the peak count both per-energy and in the union."""
    req = PredictSpectrumRequest(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        adduct="[M+H]+",
        ionization_mode="positive",
        top_n_peaks=3,
    )
    with rm.Mocker() as m:
        m.post(f"{DEFAULT_URL}/predict", json=_mock_success_body())
        resp = predict_spectrum(req)

    assert len(resp.predicted.mz) <= 3
    for spec in resp.per_energy.values():
        assert len(spec.mz) <= 3


# ---------------------------------------------------------------------------
# 2. Invalid SMILES — must fail before hitting the container
# ---------------------------------------------------------------------------


def test_invalid_smiles_raises_before_http():
    """An unparseable SMILES should raise InvalidSmilesError and NEVER
    trigger an HTTP call — verified by leaving the adapter unmocked so any
    request would raise NoMockAddress first.
    """
    req = PredictSpectrumRequest(
        smiles="XYZ_not_a_molecule",
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    with rm.Mocker() as m:
        # Intentionally NO `m.post(...)` — the adapter raises NoMockAddress on
        # any real HTTP call, so this test also proves we did not touch the
        # container.
        with pytest.raises(InvalidSmilesError) as excinfo:
            predict_spectrum(req)
        assert m.call_count == 0
    assert excinfo.value.code == "PREDICT_INVALID_SMILES"


# ---------------------------------------------------------------------------
# 3. Timeout — mock the HTTP client to hang via a Timeout exception.
# ---------------------------------------------------------------------------


def test_timeout_raises_prediction_timeout_error():
    """requests.Timeout from the adapter must be translated to our typed
    PredictionTimeoutError. Using a real 5s timeout here is cheap — we raise
    synchronously from the mock, not after waiting.
    """
    req = PredictSpectrumRequest(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    with rm.Mocker() as m:
        m.post(f"{DEFAULT_URL}/predict", exc=requests.exceptions.Timeout)
        with pytest.raises(PredictionTimeoutError) as excinfo:
            predict_spectrum(req)
    assert excinfo.value.code == "PREDICT_TIMEOUT"
    assert excinfo.value.recoverable is True


# ---------------------------------------------------------------------------
# 4. Container down — refused connection
# ---------------------------------------------------------------------------


def test_connection_error_raises_cfm_unavailable_error():
    req = PredictSpectrumRequest(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    with rm.Mocker() as m:
        m.post(f"{DEFAULT_URL}/predict",
               exc=requests.exceptions.ConnectionError)
        with pytest.raises(CfmUnavailableError) as excinfo:
            predict_spectrum(req)
    assert excinfo.value.code == "PREDICT_CFM_UNAVAILABLE"
    assert excinfo.value.recoverable is False


def test_http_500_also_raises_cfm_unavailable():
    """A running but misbehaving shim (backend crashed, returning 500) maps
    to the same error as a refused connection — operator intervention needed
    either way.
    """
    req = PredictSpectrumRequest(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    with rm.Mocker() as m:
        m.post(f"{DEFAULT_URL}/predict", status_code=500, text="boom")
        with pytest.raises(CfmUnavailableError):
            predict_spectrum(req)


# ---------------------------------------------------------------------------
# 5. model_version always non-empty
# ---------------------------------------------------------------------------


def test_model_version_populated():
    req = PredictSpectrumRequest(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    with rm.Mocker() as m:
        m.post(f"{DEFAULT_URL}/predict", json=_mock_success_body())
        resp = predict_spectrum(req)
    assert isinstance(resp.model_version, str)
    assert resp.model_version.startswith("cfm-id-")
    assert len(resp.model_version) > 0


def test_missing_model_version_raises_cfm_unavailable():
    """A shim that forgets to set model_version is broken — the verifier
    agent relies on this field being populated in every report.
    """
    req = PredictSpectrumRequest(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    with rm.Mocker() as m:
        m.post(f"{DEFAULT_URL}/predict",
               json={"cfm_stdout": _GLUCOSE_CFM_STDOUT})
        with pytest.raises(CfmUnavailableError):
            predict_spectrum(req)


# ---------------------------------------------------------------------------
# Parser-focused unit tests (no HTTP)
# ---------------------------------------------------------------------------


def test_parser_handles_three_energy_blocks():
    blocks = parse_cfm_output(_GLUCOSE_CFM_STDOUT)
    assert set(blocks.keys()) == {0, 1, 2}
    for idx in (0, 1, 2):
        assert len(blocks[idx]) == 7
        # Fragment IDs on energy0 must be stripped; first peak m/z survives.
        assert blocks[idx][0][0] == pytest.approx(61.0284)


def test_parser_ignores_preamble_and_trailer():
    text = """\
Generated by cfm-predict 4.0.0
reading molecule
energy0
50.0 100.0
energy1
50.0 50.0
energy2
50.0 25.0

Fragment annotations:
1 C6H11O5+ OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O
"""
    blocks = parse_cfm_output(text)
    assert blocks == {
        0: [(50.0, 100.0)],
        1: [(50.0, 50.0)],
        2: [(50.0, 25.0)],
    }


def test_parser_deduplicates_within_block():
    """CFM-ID sometimes emits the same m/z twice within one energy block.
    The parser keeps both rows; sort_and_dedup (exercised via tool.py) is
    what collapses them — here we just confirm the parser does not crash.
    """
    text = "energy0\n50.0 10.0\n50.0 20.0\nenergy1\nenergy2\n"
    blocks = parse_cfm_output(text)
    assert blocks[0] == [(50.0, 10.0), (50.0, 20.0)]


# ---------------------------------------------------------------------------
# Extra scope gates
# ---------------------------------------------------------------------------


def test_negative_mode_synthetic_passes_through(glucose_neg_fixture):
    """[M-H]- is the second polarity the upstream CFM-ID image ships
    pre-trained models for; the tool must propagate it unchanged into the
    output Spectrum and call the shim with the same mode (the shim picks
    the [M-H]- model directory based on the request body).

    Mocks the HTTP call with a hand-built CFM-ID stdout containing the
    canonical glucose [M-H]- water-loss series (161, 143, 119, 101, ...)
    so the assertion is meaningful without needing a live container.
    """
    req = PredictSpectrumRequest(
        smiles=glucose_neg_fixture["smiles"],
        adduct="[M-H]-",
        ionization_mode="negative",
    )
    with rm.Mocker() as m:
        m.post(
            f"{DEFAULT_URL}/predict",
            json=_mock_success_body(stdout=_GLUCOSE_NEG_CFM_STDOUT),
        )
        resp = predict_spectrum(req)

    assert resp.predicted.ionization_mode == "negative"
    assert resp.predicted.adduct == "[M-H]-"
    # [M-H-H2O]- canonical glucose negative-mode fragment.
    assert any(
        abs(mz - 161.0455) < 0.01 for mz in resp.predicted.mz
    ), f"expected [M-H-H2O]- peak near 161.045, got {resp.predicted.mz[:5]}..."
    # Precursor was computed via _compute_precursor_mz (mw - proton); for
    # glucose's exact mass 180.0634 that lands near 179.0561.
    assert abs(resp.predicted.precursor_mz - 179.0561) < 0.01
    assert max(resp.predicted.intensity) == 1.0
    # per_energy populated for all three default CFM-ID energies in negative
    # mode just like positive — the model directory differs but the energy
    # ramp structure is identical.
    assert set(resp.per_energy.keys()) == {10.0, 20.0, 40.0}
    for spec in resp.per_energy.values():
        assert spec.ionization_mode == "negative"


def test_negative_mode_request_reaches_shim_with_correct_mode():
    """Sanity: the JSON body sent to the shim carries ionization_mode=
    'negative'. The shim uses this to pick the [M-H]- model directory; if
    the tool rewrote the mode by mistake (e.g. dropped through a positive-
    only branch), the shim would silently predict the wrong polarity.
    """
    req = PredictSpectrumRequest(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        adduct="[M-H]-",
        ionization_mode="negative",
    )
    with rm.Mocker() as m:
        m.post(
            f"{DEFAULT_URL}/predict",
            json=_mock_success_body(stdout=_GLUCOSE_NEG_CFM_STDOUT),
        )
        predict_spectrum(req)
        sent = m.last_request.json()
    assert sent["ionization_mode"] == "negative"
    assert sent["adduct"] == "[M-H]-"


def test_custom_collision_energies_used_as_labels():
    req = PredictSpectrumRequest(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        adduct="[M+H]+",
        ionization_mode="positive",
        collision_energies=[15.0, 30.0, 45.0],
    )
    with rm.Mocker() as m:
        m.post(f"{DEFAULT_URL}/predict", json=_mock_success_body())
        resp = predict_spectrum(req)
    assert set(resp.per_energy.keys()) == {15.0, 30.0, 45.0}


def test_non_three_energies_fall_back_to_defaults_and_note_in_explain():
    req = PredictSpectrumRequest(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        adduct="[M+H]+",
        ionization_mode="positive",
        collision_energies=[20.0, 40.0],
    )
    with rm.Mocker() as m:
        m.post(f"{DEFAULT_URL}/predict", json=_mock_success_body())
        resp = predict_spectrum(req)
    assert set(resp.per_energy.keys()) == {10.0, 20.0, 40.0}
    assert "overridden" in resp.explain


# ---------------------------------------------------------------------------
# 6. Integration test — requires a real, reachable CFM-ID shim.
# ---------------------------------------------------------------------------


def _cfm_url_reachable() -> bool:
    url = os.environ.get("METAGENT_CFM_URL")
    if not url:
        return False
    try:
        r = requests.get(url.rstrip("/") + "/healthz", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.skipif(
    not _cfm_url_reachable(),
    reason="METAGENT_CFM_URL is unset or /healthz unreachable",
)
def test_integration_glucose_against_live_cfm():
    req = PredictSpectrumRequest(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    resp = predict_spectrum(req)
    assert len(resp.predicted.mz) >= 1
    assert resp.model_version.startswith("cfm-id-")


@pytest.mark.integration
@pytest.mark.skipif(
    not _cfm_url_reachable(),
    reason="METAGENT_CFM_URL is unset or /healthz unreachable",
)
def test_integration_glucose_negative_mode_against_live_cfm():
    """End-to-end against the [M-H]- pre-trained CFM-ID model bundled in
    the upstream image. The shim selects the model directory based on
    ``ionization_mode``, so this exercises the negative-mode model path
    that was previously gated off in v0.
    """
    req = PredictSpectrumRequest(
        smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        adduct="[M-H]-",
        ionization_mode="negative",
    )
    resp = predict_spectrum(req)
    assert resp.predicted.ionization_mode == "negative"
    assert resp.predicted.adduct == "[M-H]-"
    assert len(resp.predicted.mz) >= 1
    assert resp.model_version.startswith("cfm-id-")
