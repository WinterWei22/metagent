"""Unit tests for tools.molecule_gen (Track C).

Covers every case listed in docs/TOOL_CONTRACTS.md § Tool 4 and every test
listed in prompts/track_C_molecule_generate.md. Uses MockGenerator +
MockFingerprinter so the suite runs without MS-BART or SIRIUS installed.
"""
from __future__ import annotations

import os
import sys

# Allow running `pytest tests/tool_tests/test_molecule_gen.py` from the repo
# root without a shared conftest.py. Adds the repo root to sys.path once.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from schemas import Candidate, GenerateRequest, Spectrum
from tools.molecule_gen import generate
from tools.molecule_gen.errors import FingerprinterError, NoValidCandidatesError
from tools.molecule_gen.fingerprint import (
    CandidateFusionFingerprinter,
    GroundTruthFingerprinter,
    MockFingerprinter,
)
from tools.molecule_gen.model import MockGenerator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


CAFFEINE_SMILES = "CN1C=NC2=C1C(=O)N(C)C(=O)N2C"
THEOBROMINE_SMILES = "CN1C=NC2=C1C(=O)NC(=O)N2C"  # C7H8N4O2, different formula
ADENOSINE_SMILES = "Nc1ncnc2c1ncn2[C@@H]1O[C@H](CO)[C@@H](O)[C@H]1O"  # heavy MW
L_ALANINE_SMILES = "C[C@H](N)C(=O)O"  # light, C3H7NO2


@pytest.fixture
def caffeine_spectrum() -> Spectrum:
    """Small but valid positive-mode spectrum, adapted from the caffeine fixture."""
    return Spectrum(
        mz=[138.0662, 110.0713, 83.0604, 69.0447, 55.0291],
        intensity=[1.0, 0.52, 0.31, 0.18, 0.11],
        precursor_mz=195.0877,
        adduct="[M+H]+",
        ionization_mode="positive",
        collision_energy=25.0,
    )


@pytest.fixture
def fingerprinter() -> MockFingerprinter:
    return MockFingerprinter()


def _req(spectrum: Spectrum, **kw) -> GenerateRequest:
    return GenerateRequest(spectrum=spectrum, **kw)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


def test_all_returned_smiles_parse_in_rdkit(caffeine_spectrum, fingerprinter):
    """Contract case 1: every returned SMILES is RDKit-valid."""
    gen = MockGenerator(
        [
            (CAFFEINE_SMILES, -2.0),
            (THEOBROMINE_SMILES, -2.5),
            (L_ALANINE_SMILES, -3.0),
        ]
    )
    resp = generate(
        _req(caffeine_spectrum, n_candidates=3),
        generator=gen,
        fingerprinter=fingerprinter,
    )
    assert resp.candidates, "expected non-empty candidate list"
    for c in resp.candidates:
        assert Chem.MolFromSmiles(c.smiles) is not None, f"unparseable: {c.smiles}"


def test_source_is_generated(caffeine_spectrum, fingerprinter):
    """Contract case 2: source field is always 'generated'."""
    gen = MockGenerator([(CAFFEINE_SMILES, -2.0), (L_ALANINE_SMILES, -3.0)])
    resp = generate(
        _req(caffeine_spectrum, n_candidates=2),
        generator=gen,
        fingerprinter=fingerprinter,
    )
    assert all(c.source == "generated" for c in resp.candidates)


def test_score_in_unit_interval(caffeine_spectrum, fingerprinter):
    """Contract case 3: every score is in [0, 1]."""
    gen = MockGenerator(
        [
            (CAFFEINE_SMILES, -2.0),
            (THEOBROMINE_SMILES, -5.0),
            (L_ALANINE_SMILES, -10.0),
        ]
    )
    resp = generate(
        _req(caffeine_spectrum, n_candidates=3),
        generator=gen,
        fingerprinter=fingerprinter,
    )
    for c in resp.candidates:
        assert 0.0 <= c.score <= 1.0, f"score out of range: {c.score}"


def test_formula_hard_filter(caffeine_spectrum, fingerprinter):
    """Contract case 4: when molecular_formula is given, ≥90% of outputs match.

    We implement the formula constraint as a hard filter (100% conformance),
    which trivially satisfies the contract.
    """
    gen = MockGenerator(
        [
            (CAFFEINE_SMILES, -2.0),       # C8H10N4O2 — matches
            (THEOBROMINE_SMILES, -2.5),    # C7H8N4O2 — mismatch
            (L_ALANINE_SMILES, -3.0),      # C3H7NO2 — mismatch
            (CAFFEINE_SMILES, -2.2),       # matches (duplicate)
        ]
    )
    resp = generate(
        _req(caffeine_spectrum, molecular_formula="C8H10N4O2", n_candidates=4),
        generator=gen,
        fingerprinter=fingerprinter,
    )
    assert len(resp.candidates) >= 1
    match_rate = sum(
        1 for c in resp.candidates
        if _hill_formula(c.smiles) == "C8H10N4O2"
    ) / len(resp.candidates)
    assert match_rate >= 0.90, f"match rate {match_rate} < 0.90"


def test_mw_filter_drops_heavy_candidates(caffeine_spectrum, fingerprinter):
    """Contract case 5: max_molecular_weight=200 excludes heavier outputs."""
    gen = MockGenerator(
        [
            (L_ALANINE_SMILES, -2.0),     # MW ~89, should survive
            (CAFFEINE_SMILES, -2.5),      # MW ~194, should survive
            (ADENOSINE_SMILES, -3.0),     # MW ~267, should be dropped
        ]
    )
    resp = generate(
        _req(caffeine_spectrum, n_candidates=3, max_molecular_weight=200.0),
        generator=gen,
        fingerprinter=fingerprinter,
    )
    assert resp.candidates, "expected at least the light candidates"
    for c in resp.candidates:
        mw = _mw(c.smiles)
        assert mw <= 200.0, f"heavy SMILES slipped through: {c.smiles} MW={mw}"
    # And adenosine specifically must not appear.
    canons = {c.smiles for c in resp.candidates}
    assert Chem.MolToSmiles(Chem.MolFromSmiles(ADENOSINE_SMILES)) not in canons


def test_n_candidates_zero_returns_empty(caffeine_spectrum, fingerprinter):
    """Contract case 6: n_candidates=0 returns empty list without error."""
    # The generator should never even be called; give it no emissions so
    # this would blow up if invoked.
    gen = MockGenerator([])
    resp = generate(
        _req(caffeine_spectrum, n_candidates=0),
        generator=gen,
        fingerprinter=fingerprinter,
    )
    assert resp.candidates == []
    assert resp.n_generated_raw == 0
    assert resp.n_valid == 0


def test_invalid_smiles_filtered(caffeine_spectrum, fingerprinter):
    """Contract case 7: an unparseable string never appears in the response."""
    gen = MockGenerator(
        [
            (CAFFEINE_SMILES, -2.0),
            ("not a molecule", -2.5),
            ("", -3.0),
            ("C1CC", -3.5),              # truncated ring, RDKit rejects
            (L_ALANINE_SMILES, -4.0),
        ]
    )
    resp = generate(
        _req(caffeine_spectrum, n_candidates=5),
        generator=gen,
        fingerprinter=fingerprinter,
    )
    assert resp.n_generated_raw == 5
    assert resp.n_valid == 2
    for c in resp.candidates:
        assert Chem.MolFromSmiles(c.smiles) is not None
    # And no emitted garbage survived.
    assert "not a molecule" not in {c.smiles for c in resp.candidates}


def test_sparse_spectrum_does_not_crash(fingerprinter):
    """Contract case 8: a 3-peak spectrum still yields a clean response."""
    tiny = Spectrum(
        mz=[100.0, 120.0, 150.0],
        intensity=[1.0, 0.5, 0.2],
        precursor_mz=180.0,
        adduct="[M+H]+",
        ionization_mode="positive",
        collision_energy=None,
    )
    gen = MockGenerator([(CAFFEINE_SMILES, -2.0), (L_ALANINE_SMILES, -3.0)])
    resp = generate(
        _req(tiny, n_candidates=2),
        generator=gen,
        fingerprinter=fingerprinter,
    )
    assert resp.n_generated_raw == 2
    assert all(0.0 <= c.score <= 1.0 for c in resp.candidates)


# ---------------------------------------------------------------------------
# Additional coverage beyond the explicit contract cases
# ---------------------------------------------------------------------------


def test_all_invalid_raises_no_valid_candidates(caffeine_spectrum, fingerprinter):
    """When every generated SMILES fails RDKit parsing, the tool raises."""
    gen = MockGenerator([("qqq", -1.0), ("", -2.0), ("not smiles", -3.0)])
    with pytest.raises(NoValidCandidatesError):
        generate(
            _req(caffeine_spectrum, n_candidates=3),
            generator=gen,
            fingerprinter=fingerprinter,
        )


def test_candidates_sorted_desc_by_score(caffeine_spectrum, fingerprinter):
    """Candidates are sorted by score descending."""
    gen = MockGenerator(
        [
            (L_ALANINE_SMILES, -10.0),
            (CAFFEINE_SMILES, -1.0),
            (THEOBROMINE_SMILES, -5.0),
        ]
    )
    resp = generate(
        _req(caffeine_spectrum, n_candidates=3),
        generator=gen,
        fingerprinter=fingerprinter,
    )
    scores = [c.score for c in resp.candidates]
    assert scores == sorted(scores, reverse=True)


def test_ground_truth_fingerprinter_parses_token_string():
    """GroundTruthFingerprinter.from_token_string correctly extracts bit indices."""
    fp = GroundTruthFingerprinter.from_token_string("<fp0042><fp0249><fp1380>")
    assert fp.predict(_dummy_spectrum()) == [42, 249, 1380]


def test_explain_is_populated(caffeine_spectrum, fingerprinter):
    """The explain field is a non-empty templated sentence."""
    gen = MockGenerator([(CAFFEINE_SMILES, -2.0)])
    resp = generate(
        _req(caffeine_spectrum, n_candidates=1),
        generator=gen,
        fingerprinter=fingerprinter,
    )
    assert resp.explain
    assert "Generated" in resp.explain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hill_formula(smiles: str) -> str:
    from rdkit.Chem import rdMolDescriptors
    mol = Chem.MolFromSmiles(smiles)
    return rdMolDescriptors.CalcMolFormula(mol)


def _mw(smiles: str) -> float:
    from rdkit.Chem import Descriptors
    return float(Descriptors.MolWt(Chem.MolFromSmiles(smiles)))


def _dummy_spectrum() -> Spectrum:
    return Spectrum(
        mz=[100.0],
        intensity=[1.0],
        precursor_mz=101.0,
        adduct="[M+H]+",
        ionization_mode="positive",
        collision_energy=None,
    )


def _morgan_on_bits(smiles: str, n_bits: int = 4096, radius: int = 2) -> set[int]:
    bv = AllChem.GetMorganFingerprintAsBitVect(
        Chem.MolFromSmiles(smiles), radius=radius, nBits=n_bits
    )
    return set(bv.GetOnBits())


def _cand(smiles: str, score: float = 1.0, source: str = "library") -> Candidate:
    return Candidate(
        smiles=smiles,
        name=None,
        source=source,
        score=score,
        source_id=f"test:{smiles[:10]}",
        explain="test",
    )


# ---------------------------------------------------------------------------
# CandidateFusionFingerprinter
# ---------------------------------------------------------------------------


def test_fusion_retrieved_only_picks_top_n_from_vote(_spectrum=None):
    """retrieved_only_N should take the top N bits of the mean-voted Morgan FP."""
    candidates = [_cand(CAFFEINE_SMILES), _cand(THEOBROMINE_SMILES)]
    fp = CandidateFusionFingerprinter(
        candidates, strategy="retrieved_only_60"
    )
    bits = fp.predict(_dummy_spectrum())
    # Must be strictly bounded by requested N and sorted.
    assert len(bits) <= 60
    assert bits == sorted(bits)
    assert all(0 <= b < 4096 for b in bits)
    # Every returned bit must have been ON in at least one candidate.
    union = _morgan_on_bits(CAFFEINE_SMILES) | _morgan_on_bits(THEOBROMINE_SMILES)
    assert set(bits).issubset(union)


def test_fusion_topn_blends_base_and_retrieved():
    """topn_N with a base fingerprint should promote base-ON bits via mist_weight."""
    candidates = [_cand(L_ALANINE_SMILES)]  # small FP → only a handful of ON bits
    # Pick 3 bits that are NOT in L-alanine's Morgan FP as the "base".
    alanine_on = _morgan_on_bits(L_ALANINE_SMILES)
    base_bits = [b for b in range(4096) if b not in alanine_on][:3]

    fp_retrieved_only = CandidateFusionFingerprinter(
        candidates, strategy="retrieved_only_60"
    )
    bits_retrieved_only = set(fp_retrieved_only.predict(_dummy_spectrum()))

    fp_topn = CandidateFusionFingerprinter(
        candidates,
        base_fingerprint=base_bits,
        strategy="topn_60",
        mist_weight=2.0,
    )
    bits_topn = set(fp_topn.predict(_dummy_spectrum()))

    # base_bits get score 2.0 → they outrank retrieved_vote (max 1.0) → must appear.
    assert set(base_bits).issubset(bits_topn)
    # And retrieved_only output must NOT contain them (they have 0 retrieved vote).
    assert not set(base_bits) & bits_retrieved_only


def test_fusion_empty_candidates_raises():
    """Empty candidate list is a FingerprinterError, not a silent empty FP."""
    with pytest.raises(FingerprinterError):
        CandidateFusionFingerprinter([], strategy="retrieved_only_60")


def test_fusion_skips_invalid_smiles():
    """Invalid SMILES in the candidate list are silently dropped, not raised on."""
    candidates = [
        _cand("not a molecule"),
        _cand(""),
        _cand(CAFFEINE_SMILES),   # single valid anchor
    ]
    fp = CandidateFusionFingerprinter(candidates, strategy="retrieved_only_60")
    bits = set(fp.predict(_dummy_spectrum()))
    # The single valid candidate's ON bits are the only possible source.
    assert bits.issubset(_morgan_on_bits(CAFFEINE_SMILES))
    assert len(bits) > 0


def test_fusion_all_invalid_candidates_raises():
    """If every candidate fails RDKit parsing, raise."""
    fp = CandidateFusionFingerprinter(
        [_cand("not a molecule"), _cand("")],
        strategy="retrieved_only_60",
    )
    with pytest.raises(FingerprinterError):
        fp.predict(_dummy_spectrum())


def test_fusion_feeds_cleanly_into_generate(caffeine_spectrum):
    """Fusion fingerprinter should be drop-in-compatible with generate()."""
    candidates = [_cand(CAFFEINE_SMILES), _cand(L_ALANINE_SMILES)]
    fp = CandidateFusionFingerprinter(candidates, strategy="retrieved_only_60")
    gen = MockGenerator([(CAFFEINE_SMILES, -1.0), (L_ALANINE_SMILES, -2.0)])
    resp = generate(
        _req(caffeine_spectrum, n_candidates=2),
        generator=gen,
        fingerprinter=fp,
    )
    assert len(resp.candidates) == 2
    assert all(c.source == "generated" for c in resp.candidates)
