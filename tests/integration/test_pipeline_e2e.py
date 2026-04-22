"""End-to-end pipeline tests: A1 -> A2 -> (B, C) per fixture plus negatives.

Two parallel flavors per positive case:

1. A **mocked** e2e that runs in any environment. Mocks are injected at
   the two model boundaries (``MockInHouseRetriever`` for library_search,
   ``MockGenerator`` + ``MockFingerprinter`` for molecule_generate), and
   the candidate pool is hand-built in the shape ``candidate_prefilter``
   would emit so we don't depend on the PubChem-Lite SQLite DB.

2. A **real-pool** e2e that runs ``candidate_prefilter`` against the real
   indices. Marked ``requires_pubchem_lite`` (needs
   ``METAGENT_PUBCHEM_LITE_PATH``). If the env var is unset the test
   skips with a clear message.

The top-10 union ground-truth assertion (contract requirement: "correct
compound appears in top-10 union of library_search + molecule_generate
for at least 2 of the 3 fixtures") is expressed as a single test
parametrised over the three fixtures, gated on real resources; the
mocked flavor cannot validate ground truth because mocks don't know
chemistry.

Negative tests do not require any env and always run.
"""
from __future__ import annotations

import os
from typing import Callable

import pytest
from pydantic import ValidationError

from schemas import (
    GenerateRequest,
    LibrarySearchRequest,
    PrefilterRequest,
    PrefilteredCandidate,
    PreprocessRequest,
    Spectrum,
)
from tools.candidate_prefilter import prefilter
from tools.candidate_prefilter.errors import PubChemLiteNotBuiltError
from tools.library_search import library_search
from tools.library_search.model import MockInHouseRetriever
from tools.molecule_gen import generate
from tools.molecule_gen.fingerprint import MockFingerprinter
from tools.molecule_gen.model import MockGenerator
from tools.spectrum_ops import preprocess
from tools.spectrum_ops.errors import InvalidSpectrumError

from tests.integration.conftest import FixtureSpectrum


# ---------------------------------------------------------------------------
# Helpers: build a hand-crafted candidate pool in the A2 output shape.
# ---------------------------------------------------------------------------


def _hand_built_pool_for(fixture: FixtureSpectrum) -> list[PrefilteredCandidate]:
    """A tiny A2-style pool around the fixture's true compound.

    Includes the ground-truth compound plus one mass-identical decoy so
    that ranking (not mere presence) is exercised.
    """
    # Approximate neutral masses used to keep mass_error_ppm small and valid.
    # The tool code never consults these fields for correctness in the mocked
    # path — only library_search's _build_candidate passes them through.
    truth = PrefilteredCandidate(
        smiles=fixture.smiles,
        name=fixture.compound_name,
        source_pool="pubchem_lite",
        source_id=fixture.hmdb_id,
        molecular_formula="C6H12O6"
        if fixture.name == "glucose_pos"
        else ("C8H10N4O2" if fixture.name == "caffeine_pos" else "C7H15NO3"),
        exact_mass=fixture.precursor_mz - 1.00728,  # [M+H]+ back-off
        mass_error_ppm=0.2,
        has_reference_spectrum=False,
    )
    decoy_smiles = {
        "glucose_pos": "OC[C@H]1O[C@H](O)[C@H](O)[C@@H](O)[C@@H]1O",  # galactose
        "caffeine_pos": "CN1C=NC2=C1C(=O)NC(=O)N2C",  # theobromine (different formula, but close)
        "lcarnitine_pos": "C[N+](C)(C)CC[C@H](O)CC(=O)[O-]",  # betaine-like decoy
    }
    decoy = PrefilteredCandidate(
        smiles=decoy_smiles[fixture.name],
        name=f"{fixture.compound_name}-decoy",
        source_pool="pubchem_lite",
        source_id=f"{fixture.hmdb_id}-DECOY",
        molecular_formula=truth.molecular_formula,
        exact_mass=truth.exact_mass,
        mass_error_ppm=0.3,
        has_reference_spectrum=False,
    )
    return [truth, decoy]


def _run_mocked_pipeline(fixture: FixtureSpectrum):
    """preprocess -> hand-built pool -> (library_search, molecule_generate)."""
    spec = preprocess(fixture.to_preprocess_request()).spectrum
    pool = _hand_built_pool_for(fixture)
    mock_retriever = MockInHouseRetriever({fixture.smiles: 0.82, pool[1].smiles: 0.45})
    lib_resp = library_search(
        LibrarySearchRequest(
            spectrum=spec, candidate_pool=pool, top_k=10, libraries=["inhouse"],
        ),
        retriever=mock_retriever,
    )
    gen = MockGenerator([
        (fixture.smiles, -1.0),
        (pool[1].smiles, -2.5),
    ])
    gen_resp = generate(
        GenerateRequest(
            spectrum=spec,
            molecular_formula=pool[0].molecular_formula,
            candidate_pool=pool,
            n_candidates=2,
        ),
        generator=gen,
        fingerprinter=MockFingerprinter(),
    )
    return spec, pool, lib_resp, gen_resp


# ---------------------------------------------------------------------------
# Positive tests — mocked flavor (always runs)
# ---------------------------------------------------------------------------


class TestMockedPipeline:
    """Three fixtures x mocked pipeline. Asserts shape + range contracts."""

    def test_preprocess_produces_valid_spectrum(self, fixture_spectrum):
        resp = preprocess(fixture_spectrum.to_preprocess_request())
        # Contract: quality_flag ∈ good/sparse/noisy (invalid would have raised).
        assert resp.quality_flag in {"good", "sparse", "noisy"}
        # Contract: base peak intensity normalised to exactly 1.0.
        assert max(resp.spectrum.intensity) == pytest.approx(1.0, abs=1e-9)
        # Every intensity in [0, 1] (also schema-enforced).
        assert all(0.0 <= i <= 1.0 for i in resp.spectrum.intensity)
        # Number of peaks survived the filter.
        assert resp.n_peaks_out >= 3

    def test_mocked_library_search_returns_candidates_in_range(self, fixture_spectrum):
        _, _, lib_resp, _ = _run_mocked_pipeline(fixture_spectrum)
        assert len(lib_resp.candidates) >= 1
        # All scores in [0, 1] (schema-enforced; here we also verify empirically).
        assert all(0.0 <= c.score <= 1.0 for c in lib_resp.candidates)
        # Descending by score (schema-enforced via model_validator).
        scores = [c.score for c in lib_resp.candidates]
        assert scores == sorted(scores, reverse=True)

    def test_mocked_molecule_generate_returns_valid_smiles(self, fixture_spectrum):
        from rdkit import Chem

        _, _, _, gen_resp = _run_mocked_pipeline(fixture_spectrum)
        assert len(gen_resp.candidates) >= 1
        assert all(0.0 <= c.score <= 1.0 for c in gen_resp.candidates)
        for cand in gen_resp.candidates:
            mol = Chem.MolFromSmiles(cand.smiles)
            assert mol is not None, f"RDKit failed to parse {cand.smiles!r}"
            assert cand.source == "generated"

    def test_mocked_groundtruth_present_in_top10_union(self, fixture_spectrum):
        """Mocked version of the ground-truth assertion.

        Because we seeded the mock retriever / generator with the truth SMILES,
        the truth MUST appear in both sub-results — anything else indicates
        a regression in tool post-processing (e.g. dedup, filter, sort).
        """
        from rdkit import Chem

        _, _, lib_resp, gen_resp = _run_mocked_pipeline(fixture_spectrum)
        truth_inchikey = Chem.MolToInchiKey(Chem.MolFromSmiles(fixture_spectrum.smiles))
        top_smiles = [c.smiles for c in (lib_resp.candidates + gen_resp.candidates)[:20]]
        # Compare by InChIKey so stereochemistry differences in the mock don't
        # trip the assertion — library_search passes SMILES through unchanged,
        # but molecule_generate canonicalises via RDKit which may restate
        # stereo.
        top_inchikeys = set()
        for smi in top_smiles:
            mol = Chem.MolFromSmiles(smi)
            if mol is not None:
                top_inchikeys.add(Chem.MolToInchiKey(mol))
        assert truth_inchikey in top_inchikeys, (
            f"{fixture_spectrum.compound_name} (truth) not in mocked top-10 union "
            f"({len(top_inchikeys)} unique structures)."
        )


# ---------------------------------------------------------------------------
# Positive tests — real-pool flavor, skipped when env is absent
# ---------------------------------------------------------------------------


@pytest.mark.requires_pubchem_lite
class TestRealPoolPipeline:
    """Real candidate_prefilter runs. Requires METAGENT_PUBCHEM_LITE_PATH."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_db(self, has_pubchem_lite_env):
        if not has_pubchem_lite_env:
            pytest.skip(
                "METAGENT_PUBCHEM_LITE_PATH not set; build the DB per "
                "tools/candidate_prefilter/README_PUBCHEM_SETUP.md or run with "
                "pytest --integration and that env var defined."
            )

    def test_prefilter_returns_at_least_one_candidate(self, fixture_spectrum):
        spec = preprocess(fixture_spectrum.to_preprocess_request()).spectrum
        resp = prefilter(
            PrefilterRequest(
                precursor_mz=spec.precursor_mz,
                adduct=spec.adduct,
                mass_tolerance_ppm=5.0,
            )
        )
        # Truth compound's neutral mass must be within 0.01 Da of the back-
        # calculated neutral mass.
        truth_neutral = spec.precursor_mz - 1.00728  # [M+H]+
        assert abs(resp.neutral_mass_computed - truth_neutral) < 0.01
        assert len(resp.candidates) >= 1
        # Ground-truth InChIKey should appear somewhere in the pool.
        truth_ik_prefix = fixture_spectrum.inchikey.split("-")[0]
        found = any(
            (c.name or "").lower() == fixture_spectrum.compound_name.lower()
            or (c.source_id or "").startswith(fixture_spectrum.hmdb_id)
            for c in resp.candidates
        )
        # InChIKey comparison via RDKit — defensive, since PrefilteredCandidate
        # doesn't carry inchikey directly.
        if not found:
            from rdkit import Chem

            for c in resp.candidates:
                mol = Chem.MolFromSmiles(c.smiles)
                if mol is None:
                    continue
                if Chem.MolToInchiKey(mol).startswith(truth_ik_prefix):
                    found = True
                    break
        assert found, (
            f"Truth compound {fixture_spectrum.compound_name} "
            f"({fixture_spectrum.inchikey}) not found in real prefilter pool "
            f"of size {len(resp.candidates)}."
        )


@pytest.mark.requires_inhouse_model
def test_realmodel_groundtruth_top10_union_across_fixtures(
    all_fixtures, has_inhouse_model_env, has_pubchem_lite_env
):
    """Contract requirement: truth compound in top-10 of lib+gen union for >=2 / 3.

    Requires both PubChem-Lite DB (for real prefilter pool) and at least
    one real model checkpoint. If either is missing we skip rather than
    fake it — that's why this test is separate from the mocked block.
    """
    if not has_inhouse_model_env:
        pytest.skip(
            "No in-house model checkpoint configured "
            "(METAGENT_MSCLIP_CKPT or METAGENT_MSBART_CKPT)."
        )
    if not has_pubchem_lite_env:
        pytest.skip("METAGENT_PUBCHEM_LITE_PATH unset; cannot build real pool.")

    from rdkit import Chem

    hits = 0
    for fx in all_fixtures:
        spec = preprocess(fx.to_preprocess_request()).spectrum
        pool = prefilter(
            PrefilterRequest(
                precursor_mz=spec.precursor_mz, adduct=spec.adduct, mass_tolerance_ppm=5.0,
            )
        ).candidates
        if not pool:
            continue
        lib_resp = library_search(
            LibrarySearchRequest(spectrum=spec, candidate_pool=pool, top_k=10),
        )
        gen_resp = generate(
            GenerateRequest(spectrum=spec, candidate_pool=pool, n_candidates=10),
        )
        truth_ik = fx.inchikey
        union_iks = set()
        for cand in (lib_resp.candidates + gen_resp.candidates)[:20]:
            mol = Chem.MolFromSmiles(cand.smiles)
            if mol is not None:
                union_iks.add(Chem.MolToInchiKey(mol))
        if truth_ik in union_iks:
            hits += 1

    assert hits >= 2, (
        f"Truth compound appeared in top-10 union for only {hits} / 3 fixtures; "
        f"contract requires ≥ 2. Something upstream is misconfigured."
    )


# ---------------------------------------------------------------------------
# Negative tests — always run
# ---------------------------------------------------------------------------


def test_pipeline_rejects_invalid_spectrum():
    """Two-peak raw input should fail at the preprocess step, not downstream."""
    req = PreprocessRequest(
        raw_mz=[100.0, 101.0],
        raw_intensity=[1.0, 0.5],
        precursor_mz=150.0,
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    # After ppm merge + intensity filter, fewer than 3 peaks survive → raises.
    with pytest.raises(InvalidSpectrumError):
        preprocess(req)


def test_pipeline_empty_prefilter_cascades_cleanly():
    """Empty candidate_pool must not crash library_search or molecule_generate.

    Represents the "precursor outside any local pool" scenario. The contract
    says empty is not an error; downstream tools must handle it gracefully.
    """
    # Build a minimal valid Spectrum directly (skipping A1 — its math isn't
    # what we're testing here).
    spec = Spectrum(
        mz=[100.0, 110.0, 120.0, 130.0],
        intensity=[1.0, 0.8, 0.6, 0.4],
        precursor_mz=150.0,
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    empty_pool: list[PrefilteredCandidate] = []

    lib_resp = library_search(
        LibrarySearchRequest(
            spectrum=spec, candidate_pool=empty_pool, top_k=5, libraries=["inhouse"],
        ),
        retriever=MockInHouseRetriever({}),
    )
    assert lib_resp.candidates == []
    assert lib_resp.n_total_compared == 0
    # And the explain string should reference the empty pool, not silently
    # claim "retrieved N matches".
    assert "empty" in lib_resp.explain.lower() or "no " in lib_resp.explain.lower()

    # molecule_generate also accepts an empty pool (no bonus fires).
    gen_resp = generate(
        GenerateRequest(spectrum=spec, candidate_pool=empty_pool, n_candidates=1),
        generator=MockGenerator([("CCO", -1.0)]),
        fingerprinter=MockFingerprinter(),
    )
    # Ethanol is RDKit-valid, and with no formula constraint it survives.
    assert len(gen_resp.candidates) == 1
    assert "In prefilter pool" not in gen_resp.candidates[0].explain


def test_pipeline_nonsense_spectrum_returns_empty_from_library_search():
    """Nonsense spectrum → library_search returns empty when no candidate scores.

    The retrieval model has no idea what molecule produced the spectrum, so
    we pin its raw output to -1.0 (the most-negative end of the cosine range,
    rescaled to 0.0). With min_score=0.3 (contract default) the candidate
    must be dropped.

    Note on the mock: MockInHouseRetriever's ``default=0.0`` represents
    "cosine zero = orthogonal" not "no information", which rescales to 0.5
    and would spuriously clear min_score. Integration tests MUST set
    default=-1.0 to express "model thinks this candidate is unrelated".
    """
    nonsense_spec = Spectrum(
        mz=[800.1234, 850.5678, 900.9012],
        intensity=[1.0, 0.5, 0.3],
        precursor_mz=1000.0,
        adduct="[M+H]+",
        ionization_mode="positive",
    )
    pool = [
        PrefilteredCandidate(
            smiles="CCO",
            name="ethanol",
            source_pool="pubchem_lite",
            source_id="HMDB0000108",
            molecular_formula="C2H6O",
            exact_mass=46.0419,
            mass_error_ppm=0.0,
            has_reference_spectrum=False,
        )
    ]
    resp = library_search(
        LibrarySearchRequest(
            spectrum=nonsense_spec,
            candidate_pool=pool,
            top_k=10,
            min_score=0.3,
            libraries=["inhouse"],
        ),
        retriever=MockInHouseRetriever({}, default=-1.0),
    )
    assert resp.candidates == []


def test_prefilter_rejects_unknown_adduct():
    """Control: InvalidAdductError surfaces, not a wrong neutral mass."""
    from tools.candidate_prefilter.errors import InvalidAdductError

    with pytest.raises(InvalidAdductError):
        prefilter(
            PrefilterRequest(
                precursor_mz=181.0707,
                adduct="[M+WeirdAdduct]+",
                pools=["gnps"],  # gnps avoids pubchem-lite env dep
            )
        )


# ---------------------------------------------------------------------------
# Meta: the --integration flag.
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    # Re-declared here so the flag is recognised even when the integration
    # dir is run in isolation (`pytest tests/integration -v --integration`).
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Fail (instead of skipping) when a required env var is absent.",
    )


@pytest.fixture(autouse=True)
def _respect_integration_flag(request, has_pubchem_lite_env, has_inhouse_model_env):
    """When --integration is set, a required-env test that would skip errors instead.

    Rationale: in CI on a machine that *should* have all resources wired,
    a silent skip would mask a regression. With --integration the user has
    opted into "these must run"; flip skips into failures.
    """
    if not request.config.getoption("--integration", default=False):
        return
    marker_env_map: dict[str, bool] = {
        "requires_pubchem_lite": has_pubchem_lite_env,
        "requires_inhouse_model": has_inhouse_model_env,
        "requires_gnps": bool(os.environ.get("METAGENT_GNPS_PATH")),
    }
    for mark in request.node.iter_markers():
        want = marker_env_map.get(mark.name)
        if want is False:
            pytest.fail(
                f"--integration was passed but the resource for "
                f"@pytest.mark.{mark.name} is absent."
            )
