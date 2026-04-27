"""Unit tests for Track T1 — SIRIUS fragmentation-tree annotation."""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest
from dotenv import load_dotenv

from schemas.common import Spectrum
from tools.sirius import MockSiriusRunner, SiriusAnnotateRequest, sirius_annotate
from tools.sirius.errors import SiriusNotInstalledError, SiriusTimeoutError
from tools.sirius.ms_writer import read_ms_peaks, write_ms_file
from tools.sirius.tree_parser import parse_tree_json

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "spectra"


def _spectrum_from_fixture(name: str) -> Spectrum:
    with (FIXTURES / f"{name}_pos.json").open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    peaks = sorted(data["peaks"], key=lambda row: row[0])
    max_i = max(i for _mz, i in peaks)
    return Spectrum(
        mz=[float(mz) for mz, _i in peaks],
        intensity=[float(i) / max_i for _mz, i in peaks],
        precursor_mz=float(data["precursor_mz"]),
        adduct=data["adduct"],
        ionization_mode=data["ionization_mode"],
        collision_energy=float(data["collision_energy"]),
    )


def test_ms_writer_roundtrip(tmp_path):
    spectrum = _spectrum_from_fixture("glucose")
    path = write_ms_file(spectrum, tmp_path / "query.ms", compound_id="glucose_query")

    peaks = read_ms_peaks(path)
    assert len(peaks) == len(spectrum.mz)
    for (mz_out, intensity_out), mz_in, intensity_in in zip(
        peaks,
        spectrum.mz,
        spectrum.intensity,
        strict=True,
    ):
        assert abs(mz_out - mz_in) <= 1e-4
        assert abs(intensity_out - intensity_in * 100.0) <= 1e-4


def test_lookup_fragment_within_tolerance():
    req = SiriusAnnotateRequest(spectrum=_spectrum_from_fixture("glucose"))
    resp = sirius_annotate(req, runner=MockSiriusRunner())

    frag = resp.lookup_fragment(mz=163.0603, tolerance_ppm=5.0)
    assert frag is not None
    assert frag.neutral_loss in ("H2O", "H₂O")
    assert frag.formula == "C6H11O5"


def test_lookup_fragment_outside_tolerance():
    req = SiriusAnnotateRequest(spectrum=_spectrum_from_fixture("glucose"))
    resp = sirius_annotate(req, runner=MockSiriusRunner())

    assert resp.lookup_fragment(mz=163.0603, tolerance_ppm=0.5) is None


class SlowSiriusRunner:
    def run(self, *, input_ms, output_dir, req, sirius_bin, sirius_version):
        time.sleep(200)
        raise AssertionError("unreachable")


def test_timeout_raises():
    req = SiriusAnnotateRequest(
        spectrum=_spectrum_from_fixture("glucose"),
        timeout_seconds=5,
    )

    with pytest.raises(SiriusTimeoutError):
        sirius_annotate(req, runner=SlowSiriusRunner())


def test_tree_parser_handles_missing_neutral_loss():
    tree = {
        "fragments": [
            {"id": 0, "molecularFormula": "C6H13O6", "mz": 181.0707, "intensity": 100.0},
            {"id": 1, "molecularFormula": "C6H11O5", "mz": 163.0600, "intensity": 85.3},
        ],
        "losses": [
            {"source": 0, "target": 1, "molecularFormula": "H2O"},
        ],
    }

    fragments = parse_tree_json(tree, formula_score=0.95)
    root = next(frag for frag in fragments if frag.depth == 0)
    child = next(frag for frag in fragments if frag.depth == 1)
    assert root.neutral_loss == ""
    assert child.neutral_loss_formula == "H2O"


def test_sirius_not_installed_raises(monkeypatch):
    monkeypatch.setenv("METAGENT_SIRIUS_PATH", "/definitely/not/a/sirius")

    req = SiriusAnnotateRequest(spectrum=_spectrum_from_fixture("glucose"))
    with pytest.raises(SiriusNotInstalledError):
        sirius_annotate(req)


def test_explain_is_nonempty_template():
    req = SiriusAnnotateRequest(spectrum=_spectrum_from_fixture("glucose"))
    resp = sirius_annotate(req, runner=MockSiriusRunner())

    assert resp.explain
    assert str(resp.tree_node_count) in resp.explain
    assert "fragment tree nodes" in resp.explain


def test_glucose_has_water_loss_fragment():
    req = SiriusAnnotateRequest(spectrum=_spectrum_from_fixture("glucose"))
    resp = sirius_annotate(req, runner=MockSiriusRunner())

    frag = resp.lookup_fragment(mz=163.06, tolerance_ppm=5.0)
    assert frag is not None
    assert frag.neutral_loss in ("H2O", "H₂O")


@pytest.mark.requires_sirius
def test_real_glucose_formula():
    load_dotenv()
    sirius_path = os.environ.get("METAGENT_SIRIUS_PATH") or shutil.which("sirius")
    if not sirius_path or not Path(sirius_path).exists():
        pytest.skip("METAGENT_SIRIUS_PATH is not set and sirius is not on PATH.")

    req = SiriusAnnotateRequest(spectrum=_spectrum_from_fixture("glucose"))
    try:
        resp = sirius_annotate(req)
    except SiriusNotInstalledError as e:
        pytest.skip(f"SIRIUS real-path setup unavailable: {e}")

    assert resp.predicted_formula == "C6H12O6"
    assert resp.formula_score > 0.5
