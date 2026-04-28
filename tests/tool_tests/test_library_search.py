"""Unit tests for tools.library_search (Track B).

Covers the six cases listed in docs/TOOL_CONTRACTS.md § Tool 3 plus a
glucose-in-top-3 case with a hand-built candidate_pool. The in-house model is
always mocked via MockInHouseRetriever so the suite runs without torch /
ms-clip / GPU.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Allow running `pytest tests/tool_tests/test_library_search.py` from the repo
# root without a shared conftest.py. Adds the repo root to sys.path once.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from schemas import (
    LibrarySearchRequest,
    LibrarySearchResponse,
    PrefilteredCandidate,
    Spectrum,
)

from tools.library_search import clear_gnps_cache, library_search
from tools.library_search.errors import LibraryUnavailableError
from tools.library_search.model import InHouseScore, MockInHouseRetriever
from tools.library_search.scoring import (
    fuse_scores,
    modified_cosine_score,
    reload_calibration_for_tests,
    rescale_inhouse_score,
)


FIXTURE_DIR = Path(_REPO_ROOT) / "tests" / "fixtures" / "spectra"
GLUCOSE_SMILES = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"
CAFFEINE_SMILES = "CN1C=NC2=C1C(=O)N(C)C(=O)N2C"
THEOBROMINE_SMILES = "CN1C=NC2=C1C(=O)NC(=O)N2C"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture_spectrum(name: str) -> Spectrum:
    """Load one of the fixture spectra and build a preprocessed ``Spectrum``.

    The fixture files carry raw (unnormalised) intensities; Spectrum requires
    values in ``[0, 1]`` with base peak at 1.0.
    """
    with open(FIXTURE_DIR / name) as f:
        data = json.load(f)
    peaks = data["peaks"]
    mz = [p[0] for p in peaks]
    raw = [p[1] for p in peaks]
    mx = max(raw) if raw else 1.0
    inten = [x / mx for x in raw]
    return Spectrum(
        mz=mz,
        intensity=inten,
        precursor_mz=data["precursor_mz"],
        adduct=data["adduct"],
        ionization_mode=data["ionization_mode"],
        collision_energy=data.get("collision_energy"),
    )


def _prefiltered(
    smiles: str,
    *,
    name: str | None = None,
    source_pool: str = "pubchem_lite",
    source_id: str = "PUBCHEM:1",
    molecular_formula: str = "C6H12O6",
    exact_mass: float = 180.0634,
    mass_error_ppm: float = 0.5,
    has_reference_spectrum: bool = False,
) -> PrefilteredCandidate:
    return PrefilteredCandidate(
        smiles=smiles,
        name=name,
        source_pool=source_pool,
        source_id=source_id,
        molecular_formula=molecular_formula,
        exact_mass=exact_mass,
        mass_error_ppm=mass_error_ppm,
        has_reference_spectrum=has_reference_spectrum,
    )


@pytest.fixture(autouse=True)
def _fresh_module_state():
    """Each test starts with clean calibration cache and empty GNPS cache."""
    reload_calibration_for_tests()
    clear_gnps_cache()
    yield
    reload_calibration_for_tests()
    clear_gnps_cache()


# ---------------------------------------------------------------------------
# scoring module unit tests
# ---------------------------------------------------------------------------


class TestScoringPrimitives:
    def test_rescale_maps_full_range_into_unit_interval(self):
        assert rescale_inhouse_score(-1.0) == pytest.approx(0.0, abs=1e-6)
        assert rescale_inhouse_score(0.0) == pytest.approx(0.5, abs=1e-6)
        assert rescale_inhouse_score(1.0) == pytest.approx(1.0, abs=1e-6)

    def test_rescale_clamps_out_of_range_inputs(self):
        assert rescale_inhouse_score(-5.0) == 0.0
        assert rescale_inhouse_score(2.5) == 1.0

    def test_fuse_scores_returns_max(self):
        assert fuse_scores(0.4, 0.7) == pytest.approx(0.7)
        assert fuse_scores(0.9, 0.1) == pytest.approx(0.9)
        assert fuse_scores(0.3, None) == pytest.approx(0.3)
        assert fuse_scores(None, 0.55) == pytest.approx(0.55)
        assert fuse_scores(None, None) == 0.0

    def test_modified_cosine_identical_spectra_is_one(self):
        mz = [100.0, 150.0, 200.0]
        inten = [1.0, 0.5, 0.25]
        s = modified_cosine_score(
            query_mz=mz,
            query_intensity=inten,
            query_precursor_mz=250.0,
            ref_mz=mz,
            ref_intensity=inten,
            ref_precursor_mz=250.0,
        )
        assert 0.0 <= s <= 1.0
        assert s == pytest.approx(1.0, abs=1e-6)

    def test_modified_cosine_disjoint_spectra_is_zero(self):
        # Same precursor_mz so the "modified" shift adds no alignment; peak
        # sets at very different mz should score ~0.
        s = modified_cosine_score(
            query_mz=[100.0, 150.0, 200.0],
            query_intensity=[1.0, 0.5, 0.25],
            query_precursor_mz=250.0,
            ref_mz=[310.0, 330.0, 340.0],
            ref_intensity=[1.0, 0.5, 0.25],
            ref_precursor_mz=250.0,
        )
        assert s == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# library_search behavioural tests (mocked retriever)
# ---------------------------------------------------------------------------


class TestWithPrefilteredPool:
    def test_glucose_fixture_retrieves_glucose_in_top_three(self):
        """Contract case 1: glucose fixture, pool contains glucose + distractors."""
        spectrum = _load_fixture_spectrum("glucose_pos.json")

        pool = [
            _prefiltered(
                smiles=GLUCOSE_SMILES,
                name="glucose",
                source_id="PUBCHEM:5793",
            ),
            _prefiltered(
                smiles=CAFFEINE_SMILES,
                name="caffeine",
                source_id="PUBCHEM:2519",
                molecular_formula="C8H10N4O2",
                exact_mass=194.0804,
                mass_error_ppm=0.0,
            ),
            _prefiltered(
                smiles=THEOBROMINE_SMILES,
                name="theobromine",
                source_id="PUBCHEM:5429",
                molecular_formula="C7H8N4O2",
                exact_mass=180.0647,
                mass_error_ppm=2.0,
            ),
        ]

        # Pin the mock so glucose gets the highest in-house score and the
        # others get low ones. The fused score uses max(modcos, inhouse);
        # since none of these pool entries have a reference spectrum, only
        # inhouse contributes.
        retriever = MockInHouseRetriever(
            smiles_to_score={
                GLUCOSE_SMILES: 0.9,
                CAFFEINE_SMILES: -0.4,
                THEOBROMINE_SMILES: -0.2,
            }
        )

        req = LibrarySearchRequest(
            spectrum=spectrum,
            candidate_pool=pool,
            top_k=3,
            min_score=0.0,
        )
        resp = library_search(req, retriever=retriever)

        assert isinstance(resp, LibrarySearchResponse)
        assert resp.candidates, "expected at least one candidate"
        top3_smiles = [c.smiles for c in resp.candidates[:3]]
        assert GLUCOSE_SMILES in top3_smiles, f"glucose not in top 3: {top3_smiles}"
        # Additional assertion: the #1 candidate should be the one the mock
        # boosted.
        assert resp.candidates[0].smiles == GLUCOSE_SMILES
        assert resp.candidates[0].score == pytest.approx(0.95, abs=1e-6)

    def test_nonsensical_spectrum_returns_empty(self):
        """Contract case 2: a degenerate spectrum below min_score returns []."""
        spectrum = Spectrum(
            mz=[10.0, 11.0, 12.0],
            intensity=[1.0, 0.5, 0.2],
            precursor_mz=12.0,
            adduct="[M+H]+",
            ionization_mode="positive",
        )
        pool = [_prefiltered(smiles=GLUCOSE_SMILES)]
        # The mock reports a negative raw score that rescales below 0.3 and
        # is filtered out by min_score=0.3. Modified cosine against the
        # non-existent reference spectrum is also skipped.
        retriever = MockInHouseRetriever(smiles_to_score={GLUCOSE_SMILES: -0.5})

        req = LibrarySearchRequest(
            spectrum=spectrum, candidate_pool=pool, top_k=5, min_score=0.3
        )
        resp = library_search(req, retriever=retriever)
        assert resp.candidates == []
        assert resp.n_total_compared >= 1

    def test_top_k_one_returns_at_most_one(self):
        """Contract case 3: top_k=1 enforces the truncation."""
        spectrum = _load_fixture_spectrum("glucose_pos.json")
        pool = [
            _prefiltered(smiles=GLUCOSE_SMILES, source_id="A"),
            _prefiltered(smiles=CAFFEINE_SMILES, source_id="B"),
            _prefiltered(smiles=THEOBROMINE_SMILES, source_id="C"),
        ]
        retriever = MockInHouseRetriever(
            smiles_to_score={
                GLUCOSE_SMILES: 0.7,
                CAFFEINE_SMILES: 0.6,
                THEOBROMINE_SMILES: 0.5,
            }
        )
        req = LibrarySearchRequest(
            spectrum=spectrum, candidate_pool=pool, top_k=1, min_score=0.0
        )
        resp = library_search(req, retriever=retriever)
        assert len(resp.candidates) <= 1

    def test_top_k_zero_returns_empty(self):
        spectrum = _load_fixture_spectrum("glucose_pos.json")
        pool = [_prefiltered(smiles=GLUCOSE_SMILES)]
        retriever = MockInHouseRetriever(smiles_to_score={GLUCOSE_SMILES: 1.0})
        req = LibrarySearchRequest(
            spectrum=spectrum, candidate_pool=pool, top_k=0, min_score=0.0
        )
        resp = library_search(req, retriever=retriever)
        assert resp.candidates == []

    def test_sorted_descending_is_enforced(self):
        """Contract case 4: results are sorted by score descending."""
        spectrum = _load_fixture_spectrum("caffeine_pos.json")
        pool = [
            _prefiltered(smiles=CAFFEINE_SMILES, source_id="A"),
            _prefiltered(smiles=GLUCOSE_SMILES, source_id="B"),
            _prefiltered(smiles=THEOBROMINE_SMILES, source_id="C"),
        ]
        retriever = MockInHouseRetriever(
            smiles_to_score={
                CAFFEINE_SMILES: 0.3,
                GLUCOSE_SMILES: 0.9,
                THEOBROMINE_SMILES: 0.6,
            }
        )
        req = LibrarySearchRequest(
            spectrum=spectrum, candidate_pool=pool, top_k=5, min_score=0.0
        )
        resp = library_search(req, retriever=retriever)
        scores = [c.score for c in resp.candidates]
        assert scores == sorted(scores, reverse=True), f"not sorted: {scores}"

    def test_all_scores_in_unit_interval(self):
        """Contract case 5: every returned score is in [0, 1]."""
        spectrum = _load_fixture_spectrum("glucose_pos.json")
        pool = [
            _prefiltered(smiles=GLUCOSE_SMILES, source_id="A"),
            _prefiltered(smiles=CAFFEINE_SMILES, source_id="B"),
        ]
        # Feed the mock extreme values to make sure clamping works.
        retriever = MockInHouseRetriever(
            smiles_to_score={GLUCOSE_SMILES: 5.0, CAFFEINE_SMILES: -3.0}
        )
        req = LibrarySearchRequest(
            spectrum=spectrum, candidate_pool=pool, top_k=5, min_score=0.0
        )
        resp = library_search(req, retriever=retriever)
        for c in resp.candidates:
            assert 0.0 <= c.score <= 1.0, f"score {c.score} out of range"

    def test_deduplication_by_smiles(self):
        """Duplicate SMILES across multiple pool rows collapse to one Candidate."""
        spectrum = _load_fixture_spectrum("glucose_pos.json")
        pool = [
            _prefiltered(smiles=GLUCOSE_SMILES, source_id="HIT-1"),
            _prefiltered(smiles=GLUCOSE_SMILES, source_id="HIT-2"),
            _prefiltered(smiles=GLUCOSE_SMILES, source_id="HIT-3"),
        ]
        retriever = MockInHouseRetriever(smiles_to_score={GLUCOSE_SMILES: 0.8})
        req = LibrarySearchRequest(
            spectrum=spectrum, candidate_pool=pool, top_k=10, min_score=0.0
        )
        resp = library_search(req, retriever=retriever)
        assert len(resp.candidates) == 1
        assert resp.candidates[0].smiles == GLUCOSE_SMILES

    def test_empty_candidate_pool_returns_empty(self):
        spectrum = _load_fixture_spectrum("glucose_pos.json")
        retriever = MockInHouseRetriever()
        req = LibrarySearchRequest(
            spectrum=spectrum, candidate_pool=[], top_k=5, min_score=0.0
        )
        resp = library_search(req, retriever=retriever)
        assert resp.candidates == []
        assert "empty" in resp.explain.lower() or resp.n_total_compared == 0

    def test_candidate_source_is_library(self):
        spectrum = _load_fixture_spectrum("glucose_pos.json")
        pool = [_prefiltered(smiles=GLUCOSE_SMILES, source_id="ID-1")]
        retriever = MockInHouseRetriever(smiles_to_score={GLUCOSE_SMILES: 0.5})
        req = LibrarySearchRequest(
            spectrum=spectrum, candidate_pool=pool, top_k=5, min_score=0.0
        )
        resp = library_search(req, retriever=retriever)
        assert resp.candidates
        assert all(c.source == "library" for c in resp.candidates)
        assert resp.candidates[0].source_id == "ID-1"
        assert resp.candidates[0].explain


class TestLibrariesFlag:
    def test_gnps_only_disables_inhouse_scorer(self):
        """When libraries=['gnps'], the mock retriever must not be called."""
        spectrum = _load_fixture_spectrum("glucose_pos.json")
        pool = [_prefiltered(smiles=GLUCOSE_SMILES, source_id="A")]
        retriever = MockInHouseRetriever(smiles_to_score={GLUCOSE_SMILES: 1.0})
        req = LibrarySearchRequest(
            spectrum=spectrum,
            candidate_pool=pool,
            top_k=5,
            min_score=0.0,
            libraries=["gnps"],
        )
        resp = library_search(req, retriever=retriever)
        assert retriever.calls == [], "in-house retriever should not be called"
        # No ms-clip scoring and no reference spectrum → nothing to score →
        # empty candidates is the right outcome.
        assert resp.candidates == []

    def test_inhouse_only_disables_modified_cosine(self):
        """When libraries=['inhouse'], ms-clip scores are used regardless of GNPS refs."""
        spectrum = _load_fixture_spectrum("glucose_pos.json")
        pool = [_prefiltered(smiles=GLUCOSE_SMILES, source_id="A")]
        retriever = MockInHouseRetriever(smiles_to_score={GLUCOSE_SMILES: 0.6})
        req = LibrarySearchRequest(
            spectrum=spectrum,
            candidate_pool=pool,
            top_k=5,
            min_score=0.0,
            libraries=["inhouse"],
        )
        resp = library_search(req, retriever=retriever)
        assert len(retriever.calls) == 1
        assert resp.candidates
        assert resp.candidates[0].smiles == GLUCOSE_SMILES


class TestFallbackPath:
    def test_missing_gnps_env_raises_library_unavailable(self, monkeypatch):
        """Path B without METAGENT_GNPS_PATH must raise LibraryUnavailableError."""
        monkeypatch.delenv("METAGENT_GNPS_PATH", raising=False)
        spectrum = _load_fixture_spectrum("glucose_pos.json")
        retriever = MockInHouseRetriever()
        req = LibrarySearchRequest(
            spectrum=spectrum, candidate_pool=None, top_k=5, min_score=0.0
        )
        with pytest.raises(LibraryUnavailableError):
            library_search(req, retriever=retriever)


class TestGnpsIndexLookup:
    def test_pool_entry_sourced_from_gnps_resolves_reference(self):
        """A pool entry with source_pool='gnps' must pick up the cached GNPS spectrum."""
        from common.gnps_loader import GnpsRecord

        spectrum = _load_fixture_spectrum("glucose_pos.json")
        # Build a synthetic GNPS record whose peaks match the query exactly,
        # so modified cosine returns 1.0.
        glucose_peaks = [
            (163.0601, 1000.0),
            (145.0495, 420.0),
            (127.0390, 380.0),
            (109.0284, 250.0),
            (85.0284, 180.0),
        ]
        rec = GnpsRecord(
            spectrum_id="CCMSLIB00000TEST1",
            compound_name="glucose",
            smiles=GLUCOSE_SMILES,
            inchi=None,
            inchikey="WQZGKKKJIJFFOK-GASJEMHNSA-N",
            instrument="Orbitrap",
            ion_source="LC-ESI",
            ion_mode="positive",
            adduct="[M+H]+",
            precursor_mz=181.0707,
            ms_level=2,
            peaks=glucose_peaks,
            library_membership="GNPS-LIBRARY",
            library_quality=1,
        )
        pool = [
            _prefiltered(
                smiles=GLUCOSE_SMILES,
                source_pool="gnps",
                source_id="CCMSLIB00000TEST1",
            )
        ]
        retriever = MockInHouseRetriever(smiles_to_score={GLUCOSE_SMILES: 0.0})
        req = LibrarySearchRequest(
            spectrum=spectrum,
            candidate_pool=pool,
            top_k=3,
            min_score=0.0,
            libraries=["inhouse", "gnps"],
        )
        # Feed the GNPS records via injection, not the env var.
        resp = library_search(req, retriever=retriever, gnps_records=[rec])
        assert resp.candidates
        # Modified cosine should be ≥ 0.9 (5 of the 7 query peaks match the
        # 5 ref peaks exactly). rescaled_inhouse is 0.5 (raw 0.0 → 0.5). Max
        # fusion picks modified cosine.
        assert resp.candidates[0].score > 0.9


# ---------------------------------------------------------------------------
# Integration — guarded by env var
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    "METAGENT_GNPS_PATH" not in os.environ,
    reason="METAGENT_GNPS_PATH not set; skipping full-dump integration test.",
)
def test_integration_full_gnps_pool_finds_known_compound():
    """Contract case 6: smoke test on the full GNPS dump.

    Loads real GNPS data (requires a few GB RAM) and verifies that a query
    spectrum derived from a known GNPS record retrieves the same compound in
    the top candidates. In-house scoring is mocked out here because this test
    is about GNPS loading + modified cosine, not the real ms-clip checkpoint.
    """
    from common.gnps_loader import load_v0_usable

    path = os.environ["METAGENT_GNPS_PATH"]
    records = load_v0_usable(path)
    assert records, "GNPS loader returned no usable records"

    probe = records[0]
    mz = [float(p[0]) for p in probe.peaks]
    raw = [float(p[1]) for p in probe.peaks]
    mx = max(raw) if raw else 1.0
    spectrum = Spectrum(
        mz=mz,
        intensity=[x / mx for x in raw],
        precursor_mz=float(probe.precursor_mz),
        adduct=probe.adduct or "[M+H]+",
        ionization_mode="positive",
    )
    retriever = MockInHouseRetriever()
    req = LibrarySearchRequest(
        spectrum=spectrum,
        candidate_pool=None,
        top_k=10,
        min_score=0.0,
        libraries=["gnps"],
    )
    resp = library_search(req, retriever=retriever, gnps_records=records)
    assert resp.candidates
    assert any(c.source_id == probe.spectrum_id for c in resp.candidates[:10])


# ---------------------------------------------------------------------------
# Marker covering the real in-house model path (skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.requires_inhouse_model
@pytest.mark.skipif(
    "METAGENT_MSCLIP_CKPT" not in os.environ,
    reason="METAGENT_MSCLIP_CKPT not set; skipping real ms-clip test.",
)
def test_requires_inhouse_model_roundtrip():
    """Smoke test that real MSClipRetriever construction + one call does not crash.

    Gated on the checkpoint env var. Intentionally trivial: the goal is only
    to exercise the subprocess path in a real environment once the model is
    wired up end-to-end.
    """
    from tools.library_search.model import MSClipRetriever

    retriever = MSClipRetriever()
    result = retriever.score_candidates(
        query_mz=[163.0601, 145.0495, 127.0390, 109.0284, 85.0284],
        query_intensity=[1.0, 0.42, 0.38, 0.25, 0.18],
        query_precursor_mz=181.0707,
        adduct="[M+H]+",
        candidate_smiles=[GLUCOSE_SMILES],
        collision_energy=20.0,
    )
    assert len(result) == 1
    assert isinstance(result[0], InHouseScore)


# ---------------------------------------------------------------------------
# Regression guards for day-1 integration findings (F12, F13)
# ---------------------------------------------------------------------------


def test_canonicalise_adduct_for_msclip_works_without_torch():
    """Regression guard for F12.

    The helper must not depend on ``ms_clip`` being importable — that package
    transitively ``import torch`` in its ``common.chem`` module, so attempts to
    import it from the orchestrator env silently raise and the helper was
    returning ``None`` for every legitimate adduct. The fix was to hard-code
    the MSG vocabulary locally; this test asserts the helper returns the
    expected canonical string directly.
    """
    from tools.library_search.model import _canonicalise_adduct_for_msclip

    assert _canonicalise_adduct_for_msclip("[M+H]+") == "[M+H]+"
    assert _canonicalise_adduct_for_msclip("[M+NH4]+") == "[M+H3N+H]+"
    assert _canonicalise_adduct_for_msclip("[M+H-H2O]+") == "[M-H2O+H]+"
    assert _canonicalise_adduct_for_msclip("M+H") == "[M+H]+"
    assert _canonicalise_adduct_for_msclip(" [M+H]+ ") == "[M+H]+"
    assert _canonicalise_adduct_for_msclip("[M+WeirdAdduct]+") is None
    assert _canonicalise_adduct_for_msclip("") is None


def test_ms_clip_candidates_tsv_has_collision_energies_column(monkeypatch, tmp_path):
    """Regression guard for F13.

    ``CLIPSmiDataset.__init__`` does ``dict(df[["spec", "collision_energies"]].values)``
    when the checkpoint was trained with ``embed_ce=True`` (the production
    chemformer_v4 checkpoint is). If the column is missing pandas raises
    ``KeyError`` and the subprocess exits 1. This test monkey-patches
    ``subprocess.run`` so we can inspect the exact TSV bytes written without
    needing torch / the real ms-clip env.
    """
    import subprocess as _subprocess

    from tools.library_search import model as lsm

    captured: dict = {}

    def fake_run(cmd, *args, **kwargs):
        data_dir = None
        save_dir = None
        for token in cmd:
            if isinstance(token, str) and token.startswith("data.data_dir="):
                data_dir = Path(token.split("=", 1)[1])
            elif isinstance(token, str) and token.startswith("inference.save_dir="):
                save_dir = Path(token.split("=", 1)[1])
        assert data_dir is not None and save_dir is not None
        captured["tsv_text"] = (data_dir / "candidates.tsv").read_text()
        # Emit a minimal pickle so MSClipRetriever's downstream parsing succeeds.
        import pickle

        payload = {
            "spec_names": ["spec_x"],
            "flags": ["False"],
            "smiles": ["CCO"],
            "cosine_similarity": [[0.5]],
            "local_similarity": [[0.0]],
            "crossattn_similarity": [[0.0]],
        }
        out_pkl = save_dir / "candidates.tsv.pkl"
        with open(out_pkl, "wb") as f:
            pickle.dump(payload, f)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(_subprocess, "run", fake_run)
    monkeypatch.setattr(lsm.subprocess, "run", fake_run)

    # gpu_id="inherit" skips the nvidia-smi auto-pick subprocess so the
    # only subprocess.run call routes through our predict_smi fake.
    retriever = lsm.MSClipRetriever(
        checkpoint="/tmp/nonexistent.ckpt", gpu_id="inherit"
    )
    retriever.score_candidates(
        query_mz=[100.0, 150.0],
        query_intensity=[1.0, 0.5],
        query_precursor_mz=200.0,
        adduct="[M+H]+",
        candidate_smiles=["CCO"],
        collision_energy=20.0,
    )

    assert "tsv_text" in captured
    lines = captured["tsv_text"].strip().splitlines()
    header = lines[0].split("\t")
    assert "collision_energies" in header, f"missing column in {header}"

    ce_index = header.index("collision_energies")
    row = lines[1].split("\t")
    # Plain scalar float — matches ms-pred/tests/fixtures/tiny_labels.tsv.
    assert float(row[ce_index]) == pytest.approx(20.0)


def test_ms_clip_tsv_collision_energies_defaults_to_zero_when_none(
    monkeypatch, tmp_path
):
    """When ``Spectrum.collision_energy`` is None, the TSV carries 0.0 — the
    same value CLIPSmiDataset would use when ``emb_ce=False``.
    """
    import subprocess as _subprocess

    from tools.library_search import model as lsm

    captured: dict = {}

    def fake_run(cmd, *args, **kwargs):
        for token in cmd:
            if isinstance(token, str) and token.startswith("data.data_dir="):
                data_dir = Path(token.split("=", 1)[1])
                captured["tsv_text"] = (data_dir / "candidates.tsv").read_text()
            elif isinstance(token, str) and token.startswith("inference.save_dir="):
                save_dir = Path(token.split("=", 1)[1])
        import pickle

        payload = {
            "spec_names": ["spec_x"],
            "flags": ["False"],
            "smiles": ["CCO"],
            "cosine_similarity": [[0.1]],
            "local_similarity": [[0.0]],
            "crossattn_similarity": [[0.0]],
        }
        with open(save_dir / "candidates.tsv.pkl", "wb") as f:
            pickle.dump(payload, f)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(_subprocess, "run", fake_run)
    monkeypatch.setattr(lsm.subprocess, "run", fake_run)

    retriever = lsm.MSClipRetriever(
        checkpoint="/tmp/nonexistent.ckpt", gpu_id="inherit"
    )
    retriever.score_candidates(
        query_mz=[100.0],
        query_intensity=[1.0],
        query_precursor_mz=200.0,
        adduct="[M+H]+",
        candidate_smiles=["CCO"],
        collision_energy=None,
    )

    header = captured["tsv_text"].splitlines()[0].split("\t")
    ce_index = header.index("collision_energies")
    row = captured["tsv_text"].splitlines()[1].split("\t")
    assert float(row[ce_index]) == 0.0


def test_collision_energy_is_threaded_from_spectrum_through_library_search():
    """End-to-end: Spectrum.collision_energy must reach the retriever."""
    spectrum = _load_fixture_spectrum("glucose_pos.json")
    pool = [_prefiltered(smiles=GLUCOSE_SMILES, source_id="X")]
    retriever = MockInHouseRetriever(smiles_to_score={GLUCOSE_SMILES: 0.5})

    req = LibrarySearchRequest(
        spectrum=spectrum, candidate_pool=pool, top_k=5, min_score=0.0
    )
    library_search(req, retriever=retriever)

    assert retriever.calls, "retriever was not called"
    captured = retriever.calls[0]
    assert captured["collision_energy"] == spectrum.collision_energy
    # glucose fixture sets collision_energy=20.0
    assert captured["collision_energy"] == pytest.approx(20.0)


def test_gnps_load_failure_with_pool_degrades_gracefully(monkeypatch, tmp_path):
    """Regression guard for F15.

    When ``METAGENT_GNPS_SPECTRA_PATH`` points at a missing file and a
    ``source_pool='gnps'`` entry is in the candidate pool, library_search
    must not raise — ms-clip should still score the pool so the caller gets
    a non-empty result.
    """
    import tools.library_search as ls_pkg

    ls_pkg.clear_gnps_cache()

    monkeypatch.setenv(
        "METAGENT_GNPS_SPECTRA_PATH", str(tmp_path / "does_not_exist.mgf")
    )
    monkeypatch.delenv("METAGENT_GNPS_PATH", raising=False)

    spectrum = _load_fixture_spectrum("glucose_pos.json")
    pool = [
        _prefiltered(
            smiles="CCO",
            source_pool="gnps",
            source_id="CCMSLIB00000MISSING",
        )
    ]
    retriever = MockInHouseRetriever(smiles_to_score={"CCO": 0.8})

    req = LibrarySearchRequest(
        spectrum=spectrum,
        candidate_pool=pool,
        top_k=5,
        min_score=0.0,
        libraries=["inhouse", "gnps"],
    )
    resp = library_search(req, retriever=retriever)
    assert resp.candidates, "ms-clip pass-through should still yield a candidate"


# ---------------------------------------------------------------------------
# Negative-mode (spectraverse checkpoint, 2026-04-28)
# ---------------------------------------------------------------------------


class TestNegativeModeAdductVocab:
    """Regression guards for the spectraverse checkpoint's expanded ion vocab."""

    def test_canonical_negative_adducts_pass_through(self):
        from tools.library_search.model import _canonicalise_adduct_for_msclip

        assert _canonicalise_adduct_for_msclip("[M-H]-") == "[M-H]-"
        assert _canonicalise_adduct_for_msclip("[M+FA-H]-") == "[M+FA-H]-"
        assert _canonicalise_adduct_for_msclip("[M+CH3COO]-") == "[M+CH3COO]-"
        assert _canonicalise_adduct_for_msclip("[M+Cl]-") == "[M+Cl]-"

    def test_negative_aliases_canonicalise_to_msg_form(self):
        from tools.library_search.model import _canonicalise_adduct_for_msclip

        # Bare unbracketed alias
        assert _canonicalise_adduct_for_msclip("M-H") == "[M-H]-"
        # Formate (HCOO ≡ FA - H)
        assert _canonicalise_adduct_for_msclip("[M+HCOO]-") == "[M+FA-H]-"
        assert _canonicalise_adduct_for_msclip("[M+FA]-") == "[M+FA-H]-"
        # Acetate (OAc ≡ CH3COO)
        assert _canonicalise_adduct_for_msclip("[M+OAc]-") == "[M+CH3COO]-"
        # Whitespace tolerance — the helper strips spaces.
        assert _canonicalise_adduct_for_msclip(" [M-H]- ") == "[M-H]-"

    def test_unsupported_negative_adduct_returns_none(self):
        """Adducts not in spectraverse vocab (e.g. [M-2H]2-) must return None
        so the caller knows to skip the ms-clip pass."""
        from tools.library_search.model import _canonicalise_adduct_for_msclip

        assert _canonicalise_adduct_for_msclip("[M-2H]2-") is None
        assert _canonicalise_adduct_for_msclip("[M+TFA-H]-") is None


class TestNegativeModeEndToEnd:
    """library_search must accept a negative-mode Spectrum and route through
    the ms-clip pass without modcos-only degradation."""

    def test_negative_mode_spectrum_scores_via_inhouse(self):
        spectrum = Spectrum(
            mz=[59.0139, 71.0139, 89.0244, 101.0244, 179.0561],
            intensity=[1.0, 0.6, 0.4, 0.3, 0.2],
            precursor_mz=179.0561,
            adduct="[M-H]-",
            ionization_mode="negative",
            collision_energy=20.0,
        )
        pool = [
            _prefiltered(
                smiles=GLUCOSE_SMILES,
                name="glucose",
                source_id="HMDB0000122-neg",
            )
        ]
        retriever = MockInHouseRetriever(smiles_to_score={GLUCOSE_SMILES: 0.7})
        req = LibrarySearchRequest(
            spectrum=spectrum,
            candidate_pool=pool,
            top_k=3,
            min_score=0.0,
            libraries=["inhouse"],
        )
        resp = library_search(req, retriever=retriever)
        assert resp.candidates, "negative-mode query should still produce a candidate"
        assert resp.candidates[0].smiles == GLUCOSE_SMILES
        # Mock returns 0.7; rescaled (-1..1 → 0..1) gives 0.85.
        assert resp.candidates[0].score == pytest.approx(0.85, abs=1e-6)
        assert "ms-clip scoring failed" not in resp.explain

        # Verify the adduct made it through to the retriever in canonical form
        # (the mock receives the raw adduct string, not the canonicalised one —
        # canonicalisation happens inside MSClipRetriever, not the protocol —
        # but the call must have happened).
        assert retriever.calls
        assert retriever.calls[0]["adduct"] == "[M-H]-"

    def test_negative_mode_tsv_writes_canonical_adduct(self, monkeypatch):
        """End-to-end: a [M+HCOO]- alias must reach the subprocess TSV as
        the canonical [M+FA-H]- form, since CLIPSmiDataset only knows the
        canonical strings.
        """
        import subprocess as _subprocess

        from tools.library_search import model as lsm

        captured: dict = {}

        def fake_run(cmd, *args, **kwargs):
            for token in cmd:
                if isinstance(token, str) and token.startswith("data.data_dir="):
                    data_dir = Path(token.split("=", 1)[1])
                    captured["tsv_text"] = (data_dir / "candidates.tsv").read_text()
                elif isinstance(token, str) and token.startswith("inference.save_dir="):
                    save_dir = Path(token.split("=", 1)[1])
            import pickle

            payload = {
                "spec_names": ["q"],
                "flags": ["False"],
                "smiles": ["CCO"],
                "cosine_similarity": [[0.2]],
                "local_similarity": [[0.0]],
                "crossattn_similarity": [[0.0]],
            }
            with open(save_dir / "candidates.tsv.pkl", "wb") as f:
                pickle.dump(payload, f)

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Result()

        monkeypatch.setattr(_subprocess, "run", fake_run)
        monkeypatch.setattr(lsm.subprocess, "run", fake_run)

        retriever = lsm.MSClipRetriever(
            checkpoint="/tmp/nonexistent.ckpt", gpu_id="inherit"
        )
        retriever.score_candidates(
            query_mz=[100.0],
            query_intensity=[1.0],
            query_precursor_mz=200.0,
            adduct="[M+HCOO]-",  # alias for formate
            candidate_smiles=["CCO"],
            collision_energy=20.0,
        )

        header = captured["tsv_text"].splitlines()[0].split("\t")
        ion_idx = header.index("ionization")
        row = captured["tsv_text"].splitlines()[1].split("\t")
        assert row[ion_idx] == "[M+FA-H]-", (
            f"alias [M+HCOO]- should canonicalise to [M+FA-H]-, got {row[ion_idx]!r}"
        )


# ---------------------------------------------------------------------------
# GPU selection (CUDA_VISIBLE_DEVICES routing, 2026-04-28)
# ---------------------------------------------------------------------------


class TestGpuSelection:
    """Make sure ``MSClipRetriever(gpu_id=...)`` actually pins the subprocess
    to the requested device, and that the auto-pick path works.
    """

    def _capture_env(self, monkeypatch, gpu_id):
        """Spin up an MSClipRetriever, monkey-patch subprocess.run to capture
        the env passed to the subprocess, and return that env.
        """
        import subprocess as _subprocess

        from tools.library_search import model as lsm

        captured: dict = {}

        def fake_run(cmd, *args, **kwargs):
            for token in cmd:
                if isinstance(token, str) and token.startswith("inference.save_dir="):
                    save_dir = Path(token.split("=", 1)[1])
            captured["env"] = dict(kwargs.get("env") or {})
            import pickle

            payload = {
                "spec_names": ["q"],
                "flags": ["False"],
                "smiles": ["CCO"],
                "cosine_similarity": [[0.1]],
                "local_similarity": [[0.0]],
                "crossattn_similarity": [[0.0]],
            }
            with open(save_dir / "candidates.tsv.pkl", "wb") as f:
                pickle.dump(payload, f)

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Result()

        monkeypatch.setattr(_subprocess, "run", fake_run)
        monkeypatch.setattr(lsm.subprocess, "run", fake_run)

        retriever = lsm.MSClipRetriever(
            checkpoint="/tmp/nonexistent.ckpt", gpu_id=gpu_id
        )
        retriever.score_candidates(
            query_mz=[100.0],
            query_intensity=[1.0],
            query_precursor_mz=200.0,
            adduct="[M+H]+",
            candidate_smiles=["CCO"],
            collision_energy=20.0,
        )
        return captured["env"]

    def test_explicit_int_gpu_id_pins_device(self, monkeypatch):
        env = self._capture_env(monkeypatch, gpu_id=3)
        assert env.get("CUDA_VISIBLE_DEVICES") == "3"

    def test_explicit_string_gpu_id_pins_device(self, monkeypatch):
        env = self._capture_env(monkeypatch, gpu_id="2")
        assert env.get("CUDA_VISIBLE_DEVICES") == "2"

    def test_multi_gpu_string_passes_through(self, monkeypatch):
        env = self._capture_env(monkeypatch, gpu_id="0,1,2")
        assert env.get("CUDA_VISIBLE_DEVICES") == "0,1,2"

    def test_inherit_keyword_does_not_override(self, monkeypatch):
        """gpu_id='inherit' must leave CUDA_VISIBLE_DEVICES at whatever the
        parent process had (here we set the parent value to 'parent-default')."""
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "parent-default")
        env = self._capture_env(monkeypatch, gpu_id="inherit")
        assert env.get("CUDA_VISIBLE_DEVICES") == "parent-default"

    def test_auto_pick_calls_nvidia_smi_and_uses_freest(self, monkeypatch):
        """gpu_id='auto' shells out to nvidia-smi and picks the GPU with
        the largest free memory."""
        from tools.library_search import model as lsm

        def fake_nvidia_smi(cmd, *args, **kwargs):
            assert cmd[0] == "nvidia-smi"

            class _Res:
                returncode = 0
                stdout = "0, 1024\n1, 23000\n2, 5000\n"
                stderr = ""

            return _Res()

        # _auto_pick_gpu uses subprocess.run; patch only the auto-pick path.
        original_run = lsm.subprocess.run

        def routed_run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "nvidia-smi":
                return fake_nvidia_smi(cmd, *args, **kwargs)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(lsm.subprocess, "run", routed_run)
        chosen = lsm._auto_pick_gpu()
        assert chosen == "1", f"expected GPU 1 (most free), got {chosen!r}"

    def test_auto_pick_falls_back_to_zero_when_nvidia_smi_missing(
        self, monkeypatch
    ):
        from tools.library_search import model as lsm

        def fake_run(cmd, *args, **kwargs):
            raise FileNotFoundError("nvidia-smi not installed")

        monkeypatch.setattr(lsm.subprocess, "run", fake_run)
        assert lsm._auto_pick_gpu() == "0"

    def test_env_var_overrides_default(self, monkeypatch):
        """METAGENT_MSCLIP_GPU=4 with gpu_id=None should pin to 4."""
        monkeypatch.setenv("METAGENT_MSCLIP_GPU", "4")
        env = self._capture_env(monkeypatch, gpu_id=None)
        assert env.get("CUDA_VISIBLE_DEVICES") == "4"

    def test_env_var_inherit_disables_override(self, monkeypatch):
        """METAGENT_MSCLIP_GPU=inherit means don't touch CUDA_VISIBLE_DEVICES."""
        monkeypatch.setenv("METAGENT_MSCLIP_GPU", "inherit")
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "from-parent")
        env = self._capture_env(monkeypatch, gpu_id=None)
        assert env.get("CUDA_VISIBLE_DEVICES") == "from-parent"
