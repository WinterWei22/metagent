"""Unit tests for evaluation.sub6.identification."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from evaluation.sub6.identification import (
    identify_spectrum,
    task_exclusion_set,
    task_spectrum_to_schema,
)


def _make_spectrum(spectrum_id: str = "sp1", source_id: str = "GNPS-A",
                   ik: str = "OUYCCCASQSFEME") -> dict:
    return {
        "spectrum_id": spectrum_id,
        "source_id": source_id,
        "inchikey_first_block": ik,
        "ion_mode": "positive",
        "adduct": "[M+H]1+",
        "precursor_mz": 182.08,
        "collision_energy": None,
        "n_peaks": 3,
        "peaks": [[100.0, 50.0], [120.0, 100.0], [150.0, 25.0]],
    }


@dataclass
class _MockCandidate:
    smiles: str
    name: str
    score: float
    source: str = "library"
    source_id: str | None = None


@dataclass
class _MockResponse:
    candidates: list[_MockCandidate]
    libraries_searched: list[str] | None = None
    n_total_compared: int = 0
    explain: str = "mock"


# ---- conversion ------------------------------------------------------------


def test_spectrum_to_schema_normalises_intensity_and_sorts_mz():
    sp = {
        "spectrum_id": "sp",
        "precursor_mz": 100.0,
        "adduct": "[M+H]1+",
        "ion_mode": "positive",
        "peaks": [[150.0, 25.0], [100.0, 50.0], [120.0, 100.0]],
    }
    out = task_spectrum_to_schema(sp)
    assert out.mz == [100.0, 120.0, 150.0]
    assert out.intensity == [0.5, 1.0, 0.25]
    assert out.adduct == "[M+H]+"  # 1+ collapsed to +
    assert out.ionization_mode == "positive"


def test_spectrum_to_schema_rejects_empty_peaks():
    with pytest.raises(ValueError, match="no peaks"):
        task_spectrum_to_schema({"spectrum_id": "x", "precursor_mz": 100.0,
                                 "adduct": "[M+H]+", "ion_mode": "positive", "peaks": []})


# ---- exclusion set ---------------------------------------------------------


def test_task_exclusion_set_collects_all_source_ids():
    task = {"differential_spectra": [
        {"source_id": "GNPS-1"},
        {"source_id": "GNPS-2"},
        {"source_id": None},
        {"source_id": "GNPS-3"},
    ]}
    assert task_exclusion_set(task) == {"GNPS-1", "GNPS-2", "GNPS-3"}


# ---- top-1 identification with exclusion ----------------------------------


def test_excludes_self_match_and_returns_next_best():
    """Spectrum's own GNPS source_id MUST be filtered out (eval guide §3)."""
    sp = _make_spectrum(source_id="GNPS-SELF")
    # Library returns the self-match first, then a real hit.
    mock_resp = _MockResponse(candidates=[
        _MockCandidate(smiles="CCO", name="self-match",
                       score=0.99, source_id="GNPS-SELF"),
        _MockCandidate(smiles="CC(=O)O", name="acetic acid",
                       score=0.85, source_id="GNPS-OTHER"),
    ])
    ident = identify_spectrum(
        sp,
        exclusion_source_ids={"GNPS-SELF"},
        library_search_fn=lambda req: mock_resp,
    )
    assert ident.predicted_name == "acetic acid"
    assert ident.predicted_source_id == "GNPS-OTHER"
    assert ident.excluded_source_ids_hit == ["GNPS-SELF"]
    assert ident.n_candidates_returned == 2
    assert ident.n_after_exclusion == 1


def test_no_survivor_returns_none_predicted():
    sp = _make_spectrum(source_id="GNPS-SELF")
    mock_resp = _MockResponse(candidates=[
        _MockCandidate(smiles="CCO", name="self", score=0.99, source_id="GNPS-SELF"),
    ])
    ident = identify_spectrum(
        sp,
        exclusion_source_ids={"GNPS-SELF"},
        library_search_fn=lambda req: mock_resp,
    )
    assert ident.predicted_inchikey_first_block is None
    assert ident.correct_top1 is None
    assert ident.n_after_exclusion == 0


def test_library_search_exception_captured():
    sp = _make_spectrum()

    def boom(req):
        raise RuntimeError("ms-clip dead")

    ident = identify_spectrum(
        sp,
        exclusion_source_ids=set(),
        library_search_fn=boom,
    )
    assert ident.error is not None
    assert "ms-clip dead" in ident.error
    assert ident.predicted_inchikey_first_block is None


def test_correct_top1_reports_inchikey_match():
    """When predicted_inchikey == GT inchikey first-block, correct_top1 is True."""
    sp = _make_spectrum(ik="LFQSCWFLJHTTHZ")  # ethanol
    mock_resp = _MockResponse(candidates=[
        _MockCandidate(smiles="CCO", name="ethanol", score=0.91, source_id="GNPS-X"),
    ])
    ident = identify_spectrum(
        sp,
        exclusion_source_ids=set(),
        library_search_fn=lambda req: mock_resp,
    )
    # CCO → InChIKey for ethanol = LFQSCWFLJHTTHZ-UHFFFAOYSA-N
    if ident.predicted_inchikey_first_block is None:
        pytest.skip("RDKit not available")
    assert ident.predicted_inchikey_first_block == "LFQSCWFLJHTTHZ"
    assert ident.correct_top1 is True


def test_no_candidates_returned_at_all():
    sp = _make_spectrum()
    mock_resp = _MockResponse(candidates=[])
    ident = identify_spectrum(
        sp,
        exclusion_source_ids=set(),
        library_search_fn=lambda req: mock_resp,
    )
    assert ident.predicted_inchikey_first_block is None
    assert ident.n_candidates_returned == 0


# ---- perfect-id strategy --------------------------------------------------


def test_perfect_id_uses_gt_inchikey_directly():
    """Strategy 'perfect_id' bypasses library_search entirely and emits
    the spectrum's GT InChIKey as the prediction."""
    sp = _make_spectrum(ik="OUYCCCASQSFEME")
    ident = identify_spectrum(
        sp,
        exclusion_source_ids=set(),
        strategy="perfect_id",
    )
    assert ident.strategy == "perfect_id"
    assert ident.predicted_inchikey_first_block == "OUYCCCASQSFEME"
    assert ident.correct_top1 is True
    assert ident.predicted_score == 1.0


def test_perfect_id_recovers_name_from_lookup():
    """When a CompoundLookup is provided, perfect_id should set
    predicted_name from it instead of the placeholder."""
    import json
    import tempfile
    from pathlib import Path

    from evaluation.sub6.compound_lookup import CompoundLookup

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "curated.jsonl"
        with p.open("w") as f:
            f.write(json.dumps({
                "name": "L-Tyrosine",
                "kegg_id": "C00082",
                "inchikey_first_block": "OUYCCCASQSFEME",
            }) + "\n")
        lookup = CompoundLookup.from_curated(p)

    sp = _make_spectrum(ik="OUYCCCASQSFEME")
    ident = identify_spectrum(
        sp,
        exclusion_source_ids=set(),
        strategy="perfect_id",
        lookup=lookup,
    )
    assert ident.predicted_name == "L-Tyrosine"


def test_perfect_id_falls_back_to_placeholder_name_without_lookup():
    sp = _make_spectrum(ik="ABCDEFGHIJKLMN")
    ident = identify_spectrum(
        sp,
        exclusion_source_ids=set(),
        strategy="perfect_id",
        lookup=None,
    )
    assert "ABCDEFGHIJKLMN" in (ident.predicted_name or "")


def test_perfect_id_handles_missing_gt_inchikey():
    sp = _make_spectrum()
    sp["inchikey_first_block"] = None
    ident = identify_spectrum(
        sp,
        exclusion_source_ids=set(),
        strategy="perfect_id",
    )
    assert ident.predicted_inchikey_first_block is None
    assert ident.error is not None
    assert "no inchikey" in ident.error
