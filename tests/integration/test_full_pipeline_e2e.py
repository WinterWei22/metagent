"""End-to-end tests for the full deterministic identification pipeline.

Flavour split, in keeping with the existing integration suite:

- **Mock** — real A1 (offline), fake A2 with a one-entry pool around the
  fixture's truth compound, real B + C wired with `MockInHouseRetriever` /
  `MockGenerator` / `MockFingerprinter`, fake D1 / D2 / E callables. Runs
  anywhere, no env required. Proves the composition layer is sound.
- **Real** — everything hits the real backend(s). Gated on the union of
  METAGENT_* env vars we need; skipped with a clear reason when any is
  missing. This is the authoritative "does the whole pipeline work"
  signal.

The brief's five tests:

1. `test_full_pipeline_<fixture>_runs_without_crash` — shape.
2. `test_full_pipeline_<fixture>_finds_truth_by_connectivity` — ranking.
3. `test_full_pipeline_handles_enrichment_failure_gracefully` — D1/D2/E
   failures must degrade to None, never crash.
4. `test_full_pipeline_evidence_score_composition` — unit-test the formula.
5. `test_full_pipeline_respects_exact_mass_caveat` — D-1 honouring
   (HMDB stores L-carnitine as cation; pipeline uses SMILES-derived mass).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from rdkit import Chem

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from schemas import (
    Candidate,
    GenerateResponse,
    LibrarySearchResponse,
    MetaboliteInfoResponse,
    PathwayContextResponse,
    PredictSpectrumResponse,
    PrefilterResponse,
    PrefilteredCandidate,
    PreprocessResponse,
    Spectrum,
)
from schemas.common import PathwayEntry
from schemas.report import (
    CandidateReport,
    IdentificationReport,
    W_CANDIDATE,
    W_MASS_MATCH,
    W_PATHWAY_PRESENCE,
    W_PREDICTED_COSINE,
)
from scripts.run_full_pipeline import (
    _exact_mass_from_smiles,
    _load_fixture,
    _mass_match_indicator,
    identify,
)

from tools.library_search import library_search as _real_library_search
from tools.library_search.model import MockInHouseRetriever
from tools.metabolite_info.errors import IdentifierFormatError
from tools.molecule_gen import generate as _real_generate
from tools.molecule_gen.fingerprint import MockFingerprinter
from tools.molecule_gen.model import MockGenerator
from tools.pathway_context.errors import MetaboliteNotInNetworkError
from tools.spectrum_predict import (
    CfmUnavailableError,
    InvalidSmilesError,
    PredictionTimeoutError,
)
from tools.spectrum_predict.errors import ToolError as _SpectrumPredictToolError  # noqa: F401 - intentional, keeps import alive

_FIXTURE_NAMES = ["glucose_pos", "caffeine_pos", "lcarnitine_pos"]

_TRUTH_CONNECTIVITY = {
    # First 14 chars of the fixture InChIKey. MS-BART and HMDB both can
    # return stereo-stripped or stereo-differing forms; matching on
    # connectivity only is Track C §8.5's ruling.
    "glucose_pos": "WQZGKKKJIJFFOK",
    "caffeine_pos": "RYYVLZVUVIJVGH",
    "lcarnitine_pos": "PHIQHXFUZVPYII",
}

_FIXTURE_FORMULA = {
    # Match HMDB's stored forms so the mock A2's formula is internally
    # consistent with what the real A2 would emit. L-carnitine uses the
    # HMDB cation form per D-1 (maintainer's guidance: option (b) in the
    # brief — use HMDB-actual values, document the zwitterion).
    "glucose_pos": "C6H12O6",
    "caffeine_pos": "C8H10N4O2",
    "lcarnitine_pos": "C7H16NO3",  # HMDB cation form per D-1
}

_REQUIRED_BACKEND_ENV = [
    "METAGENT_GNPS_PATH",
    "METAGENT_GNPS_SPECTRA_PATH",
    "METAGENT_PUBCHEM_LITE_PATH",
    "METAGENT_HMDB_PATH",
    "METAGENT_RAMP_PATH",
    "METAGENT_CFM_URL",
]


def _missing_backend_env() -> list[str]:
    return [e for e in _REQUIRED_BACKEND_ENV if not os.environ.get(e)]


_BACKEND_AVAILABLE = len(_missing_backend_env()) == 0


# ---------------------------------------------------------------------------
# Mock tool-callable factories.
# ---------------------------------------------------------------------------


def _fake_prefilter_for(fixture_meta: dict, *, extra_decoys: int = 1):
    """Return a fake prefilter(req) that emits a minimal pool around truth.

    The pool always contains the truth SMILES (mass_error_ppm=0.2) plus an
    optional number of mass-identical decoy entries so downstream ranking
    actually has something to pick between.
    """
    truth_smiles = fixture_meta["smiles"]
    truth_hmdb = fixture_meta["hmdb_id"]
    formula = _FIXTURE_FORMULA[fixture_meta["name"]]

    def fn(req):
        # Back-out neutral mass from precursor_mz (matches what the real A2
        # does for [M+H]+; we do not re-implement the adduct table here).
        neutral = req.precursor_mz - 1.00728
        # Build the pool. Use the truth SMILES; a decoy SMILES shares
        # formula but differs in structure so modified-cosine ranking can
        # still distinguish them.
        pool: list[PrefilteredCandidate] = [
            PrefilteredCandidate(
                smiles=truth_smiles,
                name=fixture_meta["compound_name"],
                source_pool="pubchem_lite",
                source_id=truth_hmdb,
                molecular_formula=formula,
                exact_mass=neutral,
                mass_error_ppm=0.2,
                has_reference_spectrum=False,
            )
        ]
        # Mild decoy — different SMILES, same molecular formula to exercise
        # the ranking path. For tests that only care about "truth present",
        # extra_decoys=0 skips this.
        decoy_smiles = {
            "glucose_pos": "OC[C@H]1O[C@H](O)[C@H](O)[C@@H](O)[C@@H]1O",
            "caffeine_pos": "CN1C=NC2=C1C(=O)NC(=O)N2C",
            "lcarnitine_pos": "CC(C)(C)NCC(O)CC(=O)O",
        }[fixture_meta["name"]]
        for i in range(extra_decoys):
            pool.append(PrefilteredCandidate(
                smiles=decoy_smiles,
                name=f"{fixture_meta['compound_name']}-decoy-{i}",
                source_pool="pubchem_lite",
                source_id=f"{truth_hmdb}-DECOY{i}",
                molecular_formula=formula,
                exact_mass=neutral,
                mass_error_ppm=0.4 + i * 0.1,
                has_reference_spectrum=False,
            ))
        return PrefilterResponse(
            candidates=pool,
            neutral_mass_computed=neutral,
            n_by_pool={"pubchem_lite": len(pool), "gnps": 0},
            explain=f"fake prefilter: {len(pool)} entries (truth + {extra_decoys} decoy)",
        )

    return fn


def _fake_library_search_fn(truth_smiles: str, truth_score: float = 0.82):
    """Return a library_search callable that routes the request into the real
    library_search tool with a deterministic MockInHouseRetriever. The truth
    SMILES always gets the higher score; the decoy gets 0.45.
    """
    def fn(req, *args, **kwargs):
        score_map = {truth_smiles: truth_score}
        if req.candidate_pool:
            for entry in req.candidate_pool:
                if entry.smiles != truth_smiles:
                    score_map.setdefault(entry.smiles, 0.45)
        return _real_library_search(
            req,
            retriever=MockInHouseRetriever(score_map, default=0.0),
        )
    return fn


def _fake_generate_fn(truth_smiles: str):
    """Return a molecule_generate callable using MockGenerator + MockFingerprinter.

    Emits the truth SMILES with a high log-prob so it outranks anything else.
    """
    def fn(req, *args, **kwargs):
        emissions = [(truth_smiles, -0.5)]
        # Add one additional emission so n_valid > 1 and the merge step is
        # exercised even when the pool bonus fires for only one entry.
        if req.candidate_pool:
            for entry in req.candidate_pool:
                if entry.smiles != truth_smiles:
                    emissions.append((entry.smiles, -2.5))
                    break
        return _real_generate(
            req,
            generator=MockGenerator(emissions),
            fingerprinter=MockFingerprinter(),
        )
    return fn


def _fake_fetch_info_found(smiles: str, name: str, hmdb: str, formula: str, exact_mass: float):
    """Build a MetaboliteInfoResponse as if HMDB returned a clean hit."""
    ik = Chem.MolToInchiKey(Chem.MolFromSmiles(smiles))

    def fn(req):
        # Match either by hmdb ID or by inchikey / smiles. Good enough for tests.
        return MetaboliteInfoResponse(
            found=True,
            primary_name=name,
            synonyms=[name.lower()],
            molecular_formula=formula,
            exact_mass=exact_mass,
            smiles=smiles,
            inchikey=ik,
            chemical_class="TestClass",
            cross_refs={"hmdb": hmdb},
            source="hmdb",
            explain=f"fake fetch_metabolite_info: resolved {hmdb} via id_type={req.id_type}",
        )
    return fn


def _fake_fetch_info_notfound():
    def fn(req):
        return MetaboliteInfoResponse(
            found=False,
            explain=f"fake fetch_metabolite_info: no hit for {req.identifier!r}",
        )
    return fn


def _fake_pathway_context_found(hmdb: str):
    def fn(req):
        return PathwayContextResponse(
            pathways=[
                PathwayEntry(
                    id="hsa00010", name="Glycolysis",
                    source="kegg", hit_count=1,
                    url="https://www.kegg.jp/pathway/hsa00010",
                ),
            ],
            upstream_neighbours=[],
            downstream_neighbours=[],
            cooccurrence_score=0.0,
            plausibility_summary=f"Templated summary for {hmdb}: 1 pathway found.",
            explain=f"fake pathway_context: {hmdb}",
        )
    return fn


def _fake_pathway_context_orphan():
    def fn(req):
        raise MetaboliteNotInNetworkError(
            f"{req.metabolite_id} not in RaMP", code="PATHWAY_NOT_IN_NETWORK",
            recoverable=False,
        )
    return fn


def _fake_predict_spectrum_ok(spectrum_source: Spectrum):
    """Return a predict_spectrum callable that echoes the experimental peaks
    as its prediction — guarantees cosine=1.0 so the evidence_score path
    with a real cosine gets exercised."""
    def fn(req):
        return PredictSpectrumResponse(
            predicted=Spectrum(
                mz=list(spectrum_source.mz),
                intensity=list(spectrum_source.intensity),
                precursor_mz=spectrum_source.precursor_mz,
                adduct=spectrum_source.adduct,
                ionization_mode=spectrum_source.ionization_mode,
            ),
            per_energy={},
            model_version="cfm-id-fake-1.0",
            explain="fake predict_spectrum: echoed experimental peaks",
        )
    return fn


def _fake_predict_timeout():
    def fn(req):
        raise PredictionTimeoutError(
            "fake timeout", code="PREDICT_TIMEOUT", recoverable=True,
        )
    return fn


def _fake_predict_unavailable():
    def fn(req):
        raise CfmUnavailableError(
            "fake cfm unavailable", code="PREDICT_UNAVAILABLE", recoverable=True,
        )
    return fn


# ---------------------------------------------------------------------------
# Helpers to build the full mock kwargs dict.
# ---------------------------------------------------------------------------


def _build_mock_kwargs(fixture_meta: dict, spectrum_for_predict: Spectrum | None = None) -> dict:
    """Return a dict ready to splat into identify(..., **kwargs)."""
    from tools.spectrum_ops import preprocess as _real_preprocess

    truth_smiles = fixture_meta["smiles"]
    truth_name = fixture_meta["compound_name"]
    truth_hmdb = fixture_meta["hmdb_id"]
    formula = _FIXTURE_FORMULA[fixture_meta["name"]]
    em = _exact_mass_from_smiles(truth_smiles)

    kwargs = dict(
        preprocess_fn=_real_preprocess,
        prefilter_fn=_fake_prefilter_for(fixture_meta, extra_decoys=1),
        library_search_fn=_fake_library_search_fn(truth_smiles),
        generate_fn=_fake_generate_fn(truth_smiles),
        fetch_metabolite_info_fn=_fake_fetch_info_found(
            smiles=truth_smiles, name=truth_name, hmdb=truth_hmdb,
            formula=formula, exact_mass=(em or 0.0),
        ),
        pathway_context_fn=_fake_pathway_context_found(truth_hmdb),
        predict_spectrum_fn=_fake_predict_spectrum_ok(spectrum_for_predict) if spectrum_for_predict else None,
    )
    return kwargs


def _load_fixture_with_name(name: str) -> tuple:
    """Wrap the runner's loader and tack the name onto the meta dict."""
    req, meta = _load_fixture(name)
    meta = {**meta, "name": name}
    return req, meta


# Parametrised across all three fixtures.
@pytest.fixture(params=_FIXTURE_NAMES)
def fixture(request):
    name = request.param
    req, meta = _load_fixture_with_name(name)
    return req, meta


# ---------------------------------------------------------------------------
# Test 1: runs without crash (mocked flavour).
# ---------------------------------------------------------------------------


class TestFullPipelineRunsWithoutCrashMock:
    """Shape-only. Real output schemas flow end-to-end with mocked tools."""

    def test_returns_valid_identification_report(self, fixture):
        req, meta = fixture
        # First run without predict_spectrum to verify the None-cosine path
        # works cleanly.
        kwargs = _build_mock_kwargs(meta)
        # identify needs a callable, not None — build a passthrough that
        # raises CfmUnavailable so the pipeline skips E gracefully.
        kwargs["predict_spectrum_fn"] = _fake_predict_unavailable()
        report = identify(req, top_k=5, predict_top_n=3, **kwargs)

        assert isinstance(report, IdentificationReport)
        # Schema validates by the fact that construction succeeded.
        # Content sanity:
        assert len(report.candidates) >= 1
        assert isinstance(report.warnings, list)
        assert all(isinstance(w, str) for w in report.warnings)
        assert isinstance(report.tool_versions, dict)
        # pipeline_version should describe the branch.
        assert ":" in report.pipeline_version
        # Each CandidateReport has the required shape.
        for cr in report.candidates:
            assert 0.0 <= cr.evidence_score <= 1.0
            assert cr.mass_match_indicator in (0.0, 1.0)
            assert cr.pathway_presence_indicator in (0.0, 1.0)


# ---------------------------------------------------------------------------
# Test 2: truth connectivity in top-5 (mocked flavour).
# ---------------------------------------------------------------------------


class TestFullPipelineFindsTruthMock:
    """The mock retriever / generator both know the truth SMILES, so the
    truth compound MUST appear in the final top-5 by connectivity hash.
    Anything else is a composition-layer regression (merge, dedupe, or
    sort broke).
    """

    def test_truth_in_top5_by_connectivity(self, fixture):
        req, meta = fixture
        # Seed predict_spectrum to echo — gives truth a real cosine=1.0.
        # We construct it in two passes: first run A1 offline to get the
        # preprocessed spectrum, then build the fake predict fn around it.
        from tools.spectrum_ops import preprocess as _real_preprocess
        spec = _real_preprocess(req).spectrum

        kwargs = _build_mock_kwargs(meta, spectrum_for_predict=spec)
        report = identify(req, top_k=10, predict_top_n=5, **kwargs)

        # Collect connectivity hashes from the top-5.
        top5_conns: set[str] = set()
        for cr in report.candidates[:5]:
            mol = Chem.MolFromSmiles(cr.candidate.smiles)
            if mol is None:
                continue
            top5_conns.add(Chem.MolToInchiKey(mol).split("-")[0])

        truth = _TRUTH_CONNECTIVITY[meta["name"]]
        assert truth in top5_conns, (
            f"{meta['compound_name']} (truth connectivity {truth}) not in "
            f"top-5 mocked: got {sorted(top5_conns)}. "
            f"Full order: {[c.candidate.smiles for c in report.candidates]}"
        )


# ---------------------------------------------------------------------------
# Test 3: graceful handling of enrichment failures.
# ---------------------------------------------------------------------------


class TestFullPipelineHandlesEnrichmentFailure:
    """Each of D1 / D2 / E can raise a ToolError. The pipeline must return a
    valid IdentificationReport, mark the relevant field None on affected
    candidates, record a per-candidate note, and bump warnings."""

    def test_fetch_metabolite_info_failure(self):
        req, meta = _load_fixture_with_name("glucose_pos")
        from tools.spectrum_ops import preprocess as _real_preprocess
        spec = _real_preprocess(req).spectrum
        kwargs = _build_mock_kwargs(meta, spectrum_for_predict=spec)

        # Replace fetch with a raising callable.
        def raises_identifier_error(r):
            raise IdentifierFormatError(
                "mock format error", code="FETCH_ID_FORMAT", recoverable=False,
            )

        kwargs["fetch_metabolite_info_fn"] = raises_identifier_error

        report = identify(req, top_k=3, predict_top_n=3, **kwargs)
        # Every CandidateReport's metabolite_info is None and a note exists.
        for cr in report.candidates:
            assert cr.metabolite_info is None, (
                f"expected metabolite_info=None under D1 failure; got {cr.metabolite_info!r}"
            )
            assert any("fetch_metabolite_info" in n for n in cr.notes), (
                f"expected a fetch_metabolite_info note; got {cr.notes}"
            )
            # pathway_presence must be 0 because D2 is skipped without info.
            assert cr.pathway_presence_indicator == 0.0
            assert cr.pathway_context is None
        # Warnings mentions degradation count.
        assert any("fetch_metabolite_info" in w for w in report.warnings)

    def test_pathway_context_failure(self):
        req, meta = _load_fixture_with_name("glucose_pos")
        from tools.spectrum_ops import preprocess as _real_preprocess
        spec = _real_preprocess(req).spectrum
        kwargs = _build_mock_kwargs(meta, spectrum_for_predict=spec)
        kwargs["pathway_context_fn"] = _fake_pathway_context_orphan()

        report = identify(req, top_k=3, predict_top_n=3, **kwargs)
        for cr in report.candidates:
            assert cr.pathway_context is None
            assert cr.pathway_presence_indicator == 0.0
            assert any("pathway_context" in n for n in cr.notes)
        assert any("pathway_context" in w for w in report.warnings)

    def test_predict_spectrum_timeout(self):
        req, meta = _load_fixture_with_name("glucose_pos")
        kwargs = _build_mock_kwargs(meta)
        kwargs["predict_spectrum_fn"] = _fake_predict_timeout()

        report = identify(req, top_k=3, predict_top_n=3, **kwargs)
        for cr in report.candidates:
            assert cr.predicted_spectrum_cosine is None
            assert cr.predicted_model_version is None
            assert any("predict_spectrum" in n for n in cr.notes)
        assert any("predict_spectrum" in w for w in report.warnings)

    def test_predict_spectrum_unavailable(self):
        req, meta = _load_fixture_with_name("glucose_pos")
        kwargs = _build_mock_kwargs(meta)
        kwargs["predict_spectrum_fn"] = _fake_predict_unavailable()

        report = identify(req, top_k=3, predict_top_n=3, **kwargs)
        for cr in report.candidates:
            assert cr.predicted_spectrum_cosine is None


# ---------------------------------------------------------------------------
# Test 4: evidence_score composition is faithful to the documented formula.
# ---------------------------------------------------------------------------


class TestEvidenceScoreComposition:
    """Unit test the scoring formula directly — no pipeline, no tools.

    The formula in schemas/report.py must match the formula documented in
    that module's docstring and in `reports/integration_report_full_*`.
    Anything else drifts the audit trail.
    """

    def test_weights_sum_to_one(self):
        assert abs(
            W_CANDIDATE + W_PREDICTED_COSINE + W_MASS_MATCH + W_PATHWAY_PRESENCE - 1.0
        ) < 1e-9

    def test_all_max_yields_one(self):
        score = CandidateReport.compute_evidence_score(
            candidate_score=1.0,
            predicted_spectrum_cosine=1.0,
            mass_match_indicator=1.0,
            pathway_presence_indicator=1.0,
        )
        assert abs(score - 1.0) < 1e-9

    def test_all_zero_yields_zero(self):
        score = CandidateReport.compute_evidence_score(
            candidate_score=0.0,
            predicted_spectrum_cosine=0.0,
            mass_match_indicator=0.0,
            pathway_presence_indicator=0.0,
        )
        assert score == 0.0

    def test_none_cosine_treated_as_zero(self):
        s_with_none = CandidateReport.compute_evidence_score(
            candidate_score=0.5,
            predicted_spectrum_cosine=None,
            mass_match_indicator=1.0,
            pathway_presence_indicator=1.0,
        )
        s_with_zero = CandidateReport.compute_evidence_score(
            candidate_score=0.5,
            predicted_spectrum_cosine=0.0,
            mass_match_indicator=1.0,
            pathway_presence_indicator=1.0,
        )
        assert s_with_none == s_with_zero

    def test_linearity_in_each_component(self):
        """With all other components fixed at 0, varying each one independently
        should produce score = weight * value."""
        for (kw, w) in [
            ("candidate_score", W_CANDIDATE),
            ("predicted_spectrum_cosine", W_PREDICTED_COSINE),
            ("mass_match_indicator", W_MASS_MATCH),
            ("pathway_presence_indicator", W_PATHWAY_PRESENCE),
        ]:
            for v in (0.0, 0.25, 0.5, 0.75, 1.0):
                kwargs = dict(
                    candidate_score=0.0,
                    predicted_spectrum_cosine=0.0,
                    mass_match_indicator=0.0,
                    pathway_presence_indicator=0.0,
                )
                kwargs[kw] = v
                score = CandidateReport.compute_evidence_score(**kwargs)
                assert abs(score - w * v) < 1e-9, (
                    f"linearity broke for {kw}={v}: expected {w*v}, got {score}"
                )

    def test_formula_via_handbuilt_candidate_report(self):
        """Build a CandidateReport by hand (no pipeline) and verify the
        precomputed evidence_score on it matches the staticmethod."""
        cand = Candidate(
            smiles="OCC1OC(O)C(O)C(O)C1O",
            name="glucose",
            source="library",
            score=0.8,
            source_id="HMDB0000122",
            explain="test",
        )
        expected = CandidateReport.compute_evidence_score(
            candidate_score=0.8,
            predicted_spectrum_cosine=0.6,
            mass_match_indicator=1.0,
            pathway_presence_indicator=1.0,
        )
        cr = CandidateReport(
            candidate=cand, prefilter_match=None, metabolite_info=None,
            pathway_context=None, predicted_spectrum_cosine=0.6,
            predicted_model_version="cfm-id-test",
            mass_match_indicator=1.0, pathway_presence_indicator=1.0,
            evidence_score=expected, notes=["test"],
        )
        # Recompute from the stored fields and confirm the number we stored
        # matches the formula.
        recomputed = CandidateReport.compute_evidence_score(
            candidate_score=cr.candidate.score,
            predicted_spectrum_cosine=cr.predicted_spectrum_cosine,
            mass_match_indicator=cr.mass_match_indicator,
            pathway_presence_indicator=cr.pathway_presence_indicator,
        )
        assert abs(recomputed - cr.evidence_score) < 1e-9


# ---------------------------------------------------------------------------
# Test 5: L-carnitine D-1 zwitterion caveat honoured.
# ---------------------------------------------------------------------------


class TestLcarnitineZwitterionCaveat:
    """D-1: HMDB stores L-carnitine as the protonated cation (C7H16NO3, 162.113 Da);
    the fixture uses the zwitterion (C7H15NO3 neutral, 161.105 Da after
    back-calculation from [M+H]+). The pipeline MUST:

    1. Record HMDB's exact_mass verbatim in metabolite_info.exact_mass.
    2. Use a SMILES-derived mass for mass_match_indicator (so precursor
       matching is not broken by HMDB's curation choice).
    3. Append a note to the candidate's notes list mentioning the
       zwitterion caveat.

    Uses mocked HMDB returning the cation representation so the test does
    not require METAGENT_HMDB_PATH.
    """

    def test_zwitterion_caveat(self):
        req, meta = _load_fixture_with_name("lcarnitine_pos")
        from tools.spectrum_ops import preprocess as _real_preprocess
        spec = _real_preprocess(req).spectrum

        truth_smiles = meta["smiles"]  # the zwitterion from the fixture
        # HMDB's representation — cation (one fewer charged atom in the SMILES).
        hmdb_cation_smiles = "C[N+](C)(C)C[C@H](O)CC(=O)O"
        hmdb_cation_mass = 162.113

        kwargs = _build_mock_kwargs(meta, spectrum_for_predict=spec)
        # Override the fake D1 to return the HMDB cation shape.
        ik_cation = Chem.MolToInchiKey(Chem.MolFromSmiles(hmdb_cation_smiles))

        def fake_fetch_cation(r):
            return MetaboliteInfoResponse(
                found=True,
                primary_name="L-Carnitine (HMDB cation form)",
                synonyms=["L-carnitine"],
                molecular_formula="C7H16NO3",  # cation
                exact_mass=hmdb_cation_mass,   # HMDB's stored value
                smiles=hmdb_cation_smiles,
                inchikey=ik_cation,
                chemical_class="Quaternary ammonium",
                cross_refs={"hmdb": "HMDB0000062"},
                source="hmdb",
                explain="fake HMDB returns the cation form per D-1",
            )
        kwargs["fetch_metabolite_info_fn"] = fake_fetch_cation

        report = identify(req, top_k=5, predict_top_n=3, **kwargs)

        # Find the truth candidate (by connectivity).
        truth_conn = _TRUTH_CONNECTIVITY["lcarnitine_pos"]
        truth_cr = None
        for cr in report.candidates:
            m = Chem.MolFromSmiles(cr.candidate.smiles)
            if m and Chem.MolToInchiKey(m).split("-")[0] == truth_conn:
                truth_cr = cr
                break
        assert truth_cr is not None, (
            f"L-carnitine truth not found among {[c.candidate.smiles for c in report.candidates]}"
        )

        # 1. HMDB's exact_mass recorded verbatim.
        assert truth_cr.metabolite_info is not None
        assert abs(truth_cr.metabolite_info.exact_mass - hmdb_cation_mass) < 0.01, (
            f"HMDB exact_mass not preserved verbatim: "
            f"got {truth_cr.metabolite_info.exact_mass}, expected {hmdb_cation_mass}"
        )
        # 2. mass_match_indicator was computed from SMILES (neutral ≈ 161.105);
        #    the candidate's SMILES is the zwitterion, so SMILES-derived mass
        #    = 161.105 matches A2's neutral_mass_computed = 161.105 within 5 ppm,
        #    giving mass_match_indicator=1. Confirms we bypass HMDB's cation.
        candidate_smiles_mass = _exact_mass_from_smiles(truth_cr.candidate.smiles)
        assert candidate_smiles_mass is not None
        assert abs(candidate_smiles_mass - 161.105) < 0.01, (
            f"candidate SMILES-derived mass should be ≈ 161.105, got {candidate_smiles_mass}"
        )
        # neutral_mass_computed should also be ≈ 161.105 (A2 back-calc).
        assert abs(report.neutral_mass_computed - 161.105) < 0.01
        assert truth_cr.mass_match_indicator == 1.0, (
            f"mass_match_indicator should be 1.0 (SMILES-derived mass matches A2 "
            f"within ppm); got {truth_cr.mass_match_indicator}. If this is 0 it "
            f"means the pipeline used HMDB's cation exact_mass instead of RDKit."
        )
        # 3. A zwitterion note is present.
        assert any("zwitterion" in n.lower() or "d-1" in n.lower() for n in truth_cr.notes), (
            f"expected a zwitterion / D-1 caveat note; got {truth_cr.notes}"
        )


# ---------------------------------------------------------------------------
# Real-backend flavour.
#
# Gated via a module-level skipif so we keep pytest collection fast and
# avoid env-cross-contamination. The fixture set is deliberately small and
# one per test so an L-carnitine failure doesn't block caffeine / glucose
# reporting.
# ---------------------------------------------------------------------------


_SKIP_REAL_REASON = (
    f"requires full backend env: missing {sorted(_missing_backend_env())}. "
    "Set METAGENT_GNPS_PATH / METAGENT_GNPS_SPECTRA_PATH / "
    "METAGENT_PUBCHEM_LITE_PATH / METAGENT_HMDB_PATH / METAGENT_RAMP_PATH / "
    "METAGENT_CFM_URL and retry."
)


@pytest.mark.skipif(not _BACKEND_AVAILABLE, reason=_SKIP_REAL_REASON)
class TestFullPipelineFindsTruthReal:
    """Authoritative signal: does the real pipeline recover each fixture's truth?

    Parametrised per-fixture so an L-carnitine anomaly does not mask
    glucose / caffeine success. Connectivity hash (first 14 chars of
    InChIKey) is the comparator — MS-BART strips stereo, HMDB may store
    non-neutral forms, so a full-InChIKey match would be brittle.
    """

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "glucose_pos",
            "caffeine_pos",
            pytest.param(
                "lcarnitine_pos",
                marks=pytest.mark.xfail(
                    strict=False,
                    reason=(
                        "D-1: HMDB stores L-carnitine as the protonated cation "
                        "(C7H16NO3, 162.113 Da). The fixture precursor 162.1125 "
                        "[M+H]+ back-calculates to the neutral C7H15NO3 at "
                        "161.105 Da, which does NOT exist in HMDB or GNPS — "
                        "those pools index only the cation form. Composition "
                        "cannot find the truth regardless of B/C configuration. "
                        "Fix routed to D-2 fixture refresh per "
                        "reports/delivery_integration_de_2026-04-23.md §6 #8. "
                        "Unxfail once the fixture is regenerated with precursor "
                        "163.120 (cation [M+H]+) or the A2 pool indexes the "
                        "neutral form."
                    ),
                ),
            ),
        ],
    )
    def test_truth_in_top5(self, fixture_name):
        req, meta = _load_fixture_with_name(fixture_name)
        report = identify(req, top_k=10, predict_top_n=5)

        top5_conns: set[str] = set()
        for cr in report.candidates[:5]:
            mol = Chem.MolFromSmiles(cr.candidate.smiles)
            if mol is None:
                continue
            top5_conns.add(Chem.MolToInchiKey(mol).split("-")[0])

        truth = _TRUTH_CONNECTIVITY[fixture_name]
        assert truth in top5_conns, (
            f"{fixture_name}: truth connectivity {truth} NOT in top-5 real pipeline. "
            f"Got top-5 connectivity hashes {sorted(top5_conns)}. "
            f"Full candidates: {[(c.candidate.smiles, c.evidence_score) for c in report.candidates]}. "
            f"This is the primary acceptance signal — do NOT loosen to top-10."
        )


# ---------------------------------------------------------------------------
# Marker registration — keeps pytest from warning on our no-op use of
# requires_full_backend (we use skipif instead, but someone reading the
# list of markers should still see it documented).
# ---------------------------------------------------------------------------


def pytest_configure(config):
    """Register the marker so --markers lists it. No-op otherwise — our
    skipif handles the actual gating."""
    config.addinivalue_line(
        "markers",
        "requires_full_backend: integration test that requires all of GNPS + "
        "PubChem-Lite + HMDB + RaMP + CFM-ID env vars; see test_full_pipeline_e2e.py.",
    )
