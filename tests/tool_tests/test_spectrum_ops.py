"""Unit tests for Track A1 — `spectrum_preprocess`.

Covers every case listed in docs/TOOL_CONTRACTS.md → Tool 1 plus the extras
from prompts/track_A1_spectrum_preprocess.md. No other tool is imported; no
fixture files are modified.

Per agreed design (方案 2), Pydantic-layer violations (length mismatch,
non-positive precursor, out-of-range min_relative_intensity) surface as
`pydantic.ValidationError` at REQUEST CONSTRUCTION time. `InvalidSpectrumError`
is reserved for post-schema conditions (e.g. < 3 peaks after filtering).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow running `pytest tests/tool_tests/test_spectrum_ops.py` from the repo
# root without a shared conftest.py. Adds the repo root to sys.path once.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import numpy as np
import pytest
from pydantic import ValidationError

from schemas.spectrum import PreprocessRequest
from tools.spectrum_ops import preprocess
from tools.spectrum_ops.errors import InvalidSpectrumError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "spectra"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _request_from_fixture(fixture: dict, **overrides) -> PreprocessRequest:
    peaks = fixture["peaks"]
    kwargs = dict(
        raw_mz=[p[0] for p in peaks],
        raw_intensity=[p[1] for p in peaks],
        precursor_mz=fixture["precursor_mz"],
        adduct=fixture["adduct"],
        ionization_mode=fixture["ionization_mode"],
        collision_energy=fixture.get("collision_energy"),
    )
    kwargs.update(overrides)
    return PreprocessRequest(**kwargs)


# ---------------------------------------------------------------------------
# 1. Round-trip on the glucose fixture
# ---------------------------------------------------------------------------


def test_glucose_fixture_roundtrip():
    fx = _load_fixture("glucose_pos.json")
    req = _request_from_fixture(fx)
    resp = preprocess(req)

    assert resp.n_peaks_in == len(fx["peaks"])
    assert resp.n_peaks_out >= 3
    # Base peak must be exactly 1.0 after normalisation
    assert max(resp.spectrum.intensity) == pytest.approx(1.0)
    # Original-scale base peak reported as-is
    assert resp.base_peak_intensity == pytest.approx(1000.0)
    assert resp.base_peak_mz == pytest.approx(163.0601)
    # mz ascending
    assert resp.spectrum.mz == sorted(resp.spectrum.mz)
    # All intensities in [0, 1]
    assert all(0.0 <= v <= 1.0 for v in resp.spectrum.intensity)
    # explain is populated
    assert resp.explain
    assert "base peak" in resp.explain.lower()


def test_caffeine_and_lcarnitine_also_roundtrip():
    for name in ("caffeine_pos.json", "lcarnitine_pos.json"):
        fx = _load_fixture(name)
        resp = preprocess(_request_from_fixture(fx))
        assert resp.n_peaks_out >= 3
        assert max(resp.spectrum.intensity) == pytest.approx(1.0)
        assert resp.spectrum.adduct == fx["adduct"]
        assert resp.spectrum.ionization_mode == fx["ionization_mode"]


# ---------------------------------------------------------------------------
# 2. Mismatched arrays — caught at Pydantic layer per 方案 2
# ---------------------------------------------------------------------------


def test_mismatched_array_lengths_raise_validation_error():
    with pytest.raises(ValidationError):
        PreprocessRequest(
            raw_mz=[100.0, 200.0, 300.0, 400.0, 500.0],
            raw_intensity=[1.0, 2.0, 3.0, 4.0],
            precursor_mz=500.0,
            adduct="[M+H]+",
            ionization_mode="positive",
        )


# ---------------------------------------------------------------------------
# 3. Non-positive precursor — caught at Pydantic layer per 方案 2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_precursor", [0.0, -1.0, -180.5])
def test_non_positive_precursor_raises_validation_error(bad_precursor):
    with pytest.raises(ValidationError):
        PreprocessRequest(
            raw_mz=[100.0, 200.0, 300.0],
            raw_intensity=[1.0, 2.0, 3.0],
            precursor_mz=bad_precursor,
            adduct="[M+H]+",
            ionization_mode="positive",
        )


# ---------------------------------------------------------------------------
# 4. Fewer than 3 peaks after filter → InvalidSpectrumError
# ---------------------------------------------------------------------------


def test_two_peaks_after_filter_raises_invalid_spectrum_error():
    # 10 peaks; 8 are well below 1% of base, leaving only 2 after the default
    # min_relative_intensity=0.01 filter.
    base = 1000.0
    noise = 5.0  # 0.5% of base — below default 1% threshold
    raw_mz = [100.0, 120.0, 140.0, 160.0, 180.0, 200.0, 220.0, 240.0, 260.0, 280.0]
    raw_intensity = [base, 500.0] + [noise] * 8  # 2 survivors

    req = PreprocessRequest(
        raw_mz=raw_mz,
        raw_intensity=raw_intensity,
        precursor_mz=300.0,
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    with pytest.raises(InvalidSpectrumError) as excinfo:
        preprocess(req)
    assert "invalid" in str(excinfo.value).lower()
    assert excinfo.value.code == "INVALID_SPECTRUM"


def test_literally_two_input_peaks_also_invalid():
    # Pydantic allows len=2 at the request level (min_length=1); the filter
    # layer catches the <3 condition and raises.
    req = PreprocessRequest(
        raw_mz=[100.0, 200.0],
        raw_intensity=[1.0, 0.5],
        precursor_mz=300.0,
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    with pytest.raises(InvalidSpectrumError):
        preprocess(req)


# ---------------------------------------------------------------------------
# 5. Relative-intensity filter actually drops low peaks
# ---------------------------------------------------------------------------


def test_low_intensity_filter_drops_peaks():
    # 10 peaks; 7 are well below 1% of base → should drop to 3 survivors.
    base = 1000.0
    mid = 500.0
    low = 300.0
    noise = 2.0  # 0.2% of base, under default 1% threshold
    raw_mz = [
        100.0, 120.0, 140.0, 160.0, 180.0, 200.0, 220.0, 240.0, 260.0, 280.0,
    ]
    raw_intensity = [base, mid, low] + [noise] * 7

    req = PreprocessRequest(
        raw_mz=raw_mz,
        raw_intensity=raw_intensity,
        precursor_mz=300.0,
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    resp = preprocess(req)
    assert resp.n_peaks_in == 10
    assert resp.n_peaks_out == 3
    # surviving m/z are the three high-intensity ones
    assert set(round(v, 4) for v in resp.spectrum.mz) == {100.0, 120.0, 140.0}
    # base peak comes from the original scale
    assert resp.base_peak_intensity == pytest.approx(base)
    assert resp.base_peak_mz == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 6. Sort invariance — scrambled input → sorted output
# ---------------------------------------------------------------------------


def test_scrambled_mz_is_sorted_on_output():
    mz_unsorted = [280.0, 120.0, 200.0, 100.0, 260.0, 140.0, 220.0, 160.0, 240.0, 180.0]
    intensities = [100.0, 900.0, 200.0, 1000.0, 150.0, 800.0, 300.0, 700.0, 250.0, 600.0]
    req = PreprocessRequest(
        raw_mz=mz_unsorted,
        raw_intensity=intensities,
        precursor_mz=500.0,
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    resp = preprocess(req)

    assert resp.spectrum.mz == sorted(resp.spectrum.mz)
    # Base peak in ORIGINAL scale identifies the right m/z regardless of input order.
    assert resp.base_peak_mz == pytest.approx(100.0)
    assert resp.base_peak_intensity == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# 7. ppm merge: two peaks 4 ppm apart → one peak at default 5 ppm tolerance
# ---------------------------------------------------------------------------


def test_peaks_within_ppm_tolerance_are_merged():
    # 100.0000 and 100.0004 are 4 ppm apart. Add three well-separated peaks so
    # the output survives the ≥3-peaks check.
    req = PreprocessRequest(
        raw_mz=[100.0000, 100.0004, 150.0000, 200.0000, 250.0000],
        raw_intensity=[500.0, 500.0, 1000.0, 800.0, 600.0],
        precursor_mz=300.0,
        adduct="[M+H]+",
        ionization_mode="positive",
        mz_tolerance_ppm=5.0,
    )
    resp = preprocess(req)

    assert resp.n_peaks_in == 5
    assert resp.n_peaks_out == 4  # the 100.00xx pair collapsed to one
    # The merged peak's m/z is the intensity-weighted centroid of the pair:
    # equal weights → 100.0002
    merged_mz = resp.spectrum.mz[0]  # smallest after sort
    assert merged_mz == pytest.approx(100.0002, abs=1e-4)


def test_peaks_outside_ppm_tolerance_are_not_merged():
    # Same inputs, but tolerance lowered to 3 ppm — the 4-ppm pair should stay apart.
    req = PreprocessRequest(
        raw_mz=[100.0000, 100.0004, 150.0000, 200.0000, 250.0000],
        raw_intensity=[500.0, 500.0, 1000.0, 800.0, 600.0],
        precursor_mz=300.0,
        adduct="[M+H]+",
        ionization_mode="positive",
        mz_tolerance_ppm=3.0,
    )
    resp = preprocess(req)
    assert resp.n_peaks_out == 5


# ---------------------------------------------------------------------------
# Negative ion mode — signal processing is polarity-independent, so a
# negative-mode spectrum should preprocess cleanly and propagate both
# `ionization_mode="negative"` and the negative adduct unchanged.
# ---------------------------------------------------------------------------


def test_negative_mode_fixture_roundtrip():
    fx = _load_fixture("glucose_neg.json")
    req = _request_from_fixture(fx)
    resp = preprocess(req)

    assert resp.spectrum.ionization_mode == "negative"
    assert resp.spectrum.adduct == "[M-H]-"
    assert resp.n_peaks_in == len(fx["peaks"])
    assert resp.n_peaks_out >= 3
    # Base peak normalised to exactly 1.0
    assert max(resp.spectrum.intensity) == pytest.approx(1.0)
    # Original-scale base peak (m/z 161.0455 has intensity 1000.0 in the fixture)
    assert resp.base_peak_intensity == pytest.approx(1000.0)
    assert resp.base_peak_mz == pytest.approx(161.0455)
    # mz ascending
    assert resp.spectrum.mz == sorted(resp.spectrum.mz)
    # All intensities in [0, 1]
    assert all(0.0 <= v <= 1.0 for v in resp.spectrum.intensity)


def test_negative_mode_synthetic_passes_through():
    # Lightweight in-test sanity: minimal hand-built negative-mode peak list
    # (without leaning on the fixture) still preprocesses cleanly.
    req = PreprocessRequest(
        raw_mz=[100.0, 120.0, 140.0],
        raw_intensity=[1000.0, 500.0, 250.0],
        precursor_mz=200.0,
        adduct="[M-H]-",
        ionization_mode="negative",
    )
    resp = preprocess(req)
    assert resp.spectrum.ionization_mode == "negative"
    assert resp.spectrum.adduct == "[M-H]-"
    assert resp.n_peaks_out == 3
    assert max(resp.spectrum.intensity) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Quality-flag assignment
# ---------------------------------------------------------------------------


def test_quality_flag_sparse_for_small_peak_count():
    # 5 peaks, well-distributed → sparse (3 ≤ n ≤ 9).
    req = PreprocessRequest(
        raw_mz=[100.0, 120.0, 140.0, 160.0, 180.0],
        raw_intensity=[1000.0, 800.0, 600.0, 400.0, 200.0],
        precursor_mz=200.0,
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    assert preprocess(req).quality_flag == "sparse"


def test_quality_flag_good_for_well_distributed_many_peaks():
    # 12 peaks, base peak carries only ~10% of total → "good".
    mzs = list(np.linspace(100.0, 300.0, 12))
    intens = [1000.0] * 12  # all equal → base carries 1/12 of total
    req = PreprocessRequest(
        raw_mz=mzs,
        raw_intensity=intens,
        precursor_mz=400.0,
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    assert preprocess(req).quality_flag == "good"


def test_quality_flag_noisy_when_base_peak_dominates():
    # 12 peaks but base is ~99% of total signal → noisy.
    mzs = list(np.linspace(100.0, 300.0, 12))
    intens = [1000.0] + [1.0] * 11  # base peak 1000, others just above 0.1% of base
    # Need min_relative_intensity low enough to keep the trace peaks.
    req = PreprocessRequest(
        raw_mz=mzs,
        raw_intensity=intens,
        precursor_mz=400.0,
        adduct="[M+H]+",
        ionization_mode="positive",
        min_relative_intensity=0.0005,
    )
    assert preprocess(req).quality_flag == "noisy"


# ---------------------------------------------------------------------------
# Response shape sanity
# ---------------------------------------------------------------------------


def test_response_spectrum_respects_schema_invariants():
    fx = _load_fixture("glucose_pos.json")
    resp = preprocess(_request_from_fixture(fx))

    # Spectrum validator enforces intensity ∈ [0, 1]; reaching here means it held.
    assert len(resp.spectrum.mz) == len(resp.spectrum.intensity) == resp.n_peaks_out
    # Precursor + adduct + mode propagate unchanged.
    assert resp.spectrum.precursor_mz == pytest.approx(fx["precursor_mz"])
    assert resp.spectrum.adduct == fx["adduct"]
    assert resp.spectrum.ionization_mode == fx["ionization_mode"]
