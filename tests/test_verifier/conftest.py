"""Shared fixtures for the verifier unit-test suite.

Covers three real-world-like ``IdentificationReport`` fixtures — glucose,
caffeine, lcarnitine — matching the three O1 delivery fixtures. These are
the *source reports* the verifier cross-checks claims against; the
verbatim LLM outputs live in ``test_agent_real_o1_outputs.py``.

Every test that calls into ``common.llm_client`` gets a tempfile log path
auto-installed, so the repo's ``logs/llm_calls.jsonl`` is never polluted
by a test run.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Log-path isolation — every test gets its own tempfile
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_llm_log(tmp_path):
    from common import llm_client

    prev = llm_client.get_log_path()
    llm_client.set_log_path(tmp_path / "llm_calls.jsonl")
    try:
        yield
    finally:
        llm_client.set_log_path(prev)


@pytest.fixture(autouse=True)
def _clear_mock_between_tests():
    from common import llm_client

    llm_client.clear_mock()
    yield
    llm_client.clear_mock()


# ---------------------------------------------------------------------------
# Report fixtures
# ---------------------------------------------------------------------------


def _spectrum(precursor: float, ce: float = 20.0):
    from schemas.common import Spectrum

    return Spectrum(
        mz=[precursor],
        intensity=[1.0],
        precursor_mz=precursor,
        adduct="[M+H]+",
        ionization_mode="positive",
        collision_energy=ce,
    )


def _cand_report(
    *,
    name,
    smiles,
    score,
    formula=None,
    cross_refs=None,
    inchikey=None,
    pathways=None,
    predicted_cosine=None,
    evidence_score,
    mass_match=1.0,
    degraded_info=False,
    synonyms=None,
):
    from schemas.common import Candidate, PathwayEntry
    from schemas.molecule import MetaboliteInfoResponse
    from schemas.pathway import PathwayContextResponse
    from schemas.report import CandidateReport

    cand = Candidate(
        smiles=smiles, name=name, source="library",
        score=score, source_id=f"X:{name}", explain="library hit",
    )
    if degraded_info:
        info = None
    else:
        info = MetaboliteInfoResponse(
            found=True, primary_name=name,
            synonyms=list(synonyms or []),
            molecular_formula=formula,
            exact_mass=None,
            smiles=smiles, inchikey=inchikey,
            chemical_class=None,
            cross_refs=dict(cross_refs or {}),
            source="hmdb", explain="hit",
        )
    pc = None
    if pathways:
        pc = PathwayContextResponse(
            pathways=[
                PathwayEntry(id=p["id"], name=p["name"], source=p["source"],
                             hit_count=p.get("hit_count", 1), url="X")
                for p in pathways
            ],
            upstream_neighbours=[], downstream_neighbours=[],
            cooccurrence_score=0.0, plausibility_summary="X", explain="X",
        )
    return CandidateReport(
        candidate=cand, prefilter_match=None,
        metabolite_info=info, pathway_context=pc,
        predicted_spectrum_cosine=predicted_cosine,
        predicted_model_version="cfm-id-4.4.7" if predicted_cosine else None,
        mass_match_indicator=mass_match,
        pathway_presence_indicator=1.0 if pathways else 0.0,
        evidence_score=evidence_score, notes=[],
    )


def _wrap_report(*, precursor, neutral, candidates):
    from schemas.report import IdentificationReport

    return IdentificationReport(
        experimental_spectrum=_spectrum(precursor),
        preprocess_quality_flag="sparse",
        neutral_mass_computed=neutral,
        n_prefilter_candidates=len(candidates) * 10,
        n_library_candidates=len(candidates),
        n_generated_candidates=0,
        candidates=candidates,
        pipeline_version="integration-day1:2bc192d",
        tool_versions={"cfm-id": "cfm-id-4.4.7"},
        warnings=[],
    )


@pytest.fixture
def glucose_report():
    """Matches the glucose_pos O1 fixture: D-Gulose top, Glucose second,
    plus pathway context for the top candidate."""
    return _wrap_report(
        precursor=181.0707, neutral=180.0634,
        candidates=[
            _cand_report(
                name="D-Gulose", smiles="OCC1OC(O)C(O)C(O)C1O",
                score=0.860, formula="C6H12O6",
                inchikey="WQZGKKKJIJFFOK-VFUOTHLCSA-N",
                cross_refs={"hmdb": "HMDB0250761", "kegg": "C00738", "pubchem_cid": "206"},
                pathways=[
                    {"id": "SMP00525", "name": "Fabry disease", "source": "smpdb"},
                    {"id": "SMP00043", "name": "Galactose Metabolism", "source": "smpdb"},
                    {"id": "map00052", "name": "Galactose Metabolism", "source": "kegg"},
                    {"id": "SMP00182", "name": "Galactosemia", "source": "smpdb"},
                ],
                predicted_cosine=0.423, evidence_score=0.771,
                synonyms=["Gulose"],
            ),
            _cand_report(
                name="Glucose",
                smiles="C([C@@H]1[C@H]([C@@H]([C@H](C(O1)O)O)O)O)O",
                score=0.835, formula="C6H12O6",
                cross_refs={"hmdb": "HMDB0304632", "kegg": "C00031",
                            "chebi": "4167", "pubchem_cid": "5793"},
                predicted_cosine=0.423, evidence_score=0.761,
            ),
        ],
    )


@pytest.fixture
def caffeine_report():
    """Matches the caffeine_pos O1 fixture: Caffeine top with KEGG map00232."""
    return _wrap_report(
        precursor=195.0877, neutral=194.0804,
        candidates=[
            _cand_report(
                name="Caffeine", smiles="Cn1c(=O)c2c(ncn2C)n(C)c1=O",
                score=0.975, formula="C8H10N4O2",
                inchikey="RYYVLZVUVIJVGH-UHFFFAOYSA-N",
                cross_refs={"hmdb": "HMDB0001847", "kegg": "C07481",
                            "chebi": "27732", "pubchem_cid": "2519"},
                synonyms=["1,3,7-trimethylxanthine",
                          "1,3,7-Trimethyl-1H-purine-2,6(3H,7H)-dione"],
                pathways=[
                    {"id": "SMP00028", "name": "Caffeine Metabolism", "source": "smpdb"},
                    {"id": "map00232", "name": "Caffeine Metabolism", "source": "kegg"},
                ],
                predicted_cosine=0.316, evidence_score=0.785,
            ),
            _cand_report(
                name="Isocaffeine",
                smiles="CN1C=NC2=C1N(C(=O)N(C2=O)C)C",
                score=0.797, formula="C8H10N4O2",
                predicted_cosine=0.439, evidence_score=0.651,
                degraded_info=True,
            ),
            _cand_report(
                name="1,3,8-trimethyl-7H-purine-2,6-dione",
                smiles="CC1=NC2=C(N1)C(=O)N(C(=O)N2C)C",
                score=0.790, formula="C8H10N4O2",
                predicted_cosine=0.338, evidence_score=0.617,
                degraded_info=True,
            ),
        ],
    )


@pytest.fixture
def lcarnitine_report():
    """Matches the lcarnitine_pos O1 fixture: the deterministic pipeline
    does NOT return L-carnitine at the top — instead it returns the
    zwitterion-matched library hit. Verifier must respect this (H6)."""
    return _wrap_report(
        precursor=162.1125, neutral=161.1052,
        candidates=[
            _cand_report(
                name="2-[2-hydroxyethyl(methyl)amino]ethyl acetate",
                smiles="CC(=O)OCCN(C)CCO",
                score=0.737, formula="C7H15NO3",
                predicted_cosine=0.112, evidence_score=0.529,
                degraded_info=True,
            ),
            _cand_report(
                name="[dimethyl-(trimethylsilylamino)silyl]methane",
                smiles="C[Si](C)(C)N[Si](C)(C)C",
                score=0.748, formula="C6H19NSi2",
                predicted_cosine=0.0, evidence_score=0.499,
                degraded_info=True,
            ),
            _cand_report(
                name="3-[2-(dimethylamino)ethoxy]propanoic acid",
                smiles="CN(C)CCOCCC(=O)O",
                score=0.722, formula="C7H15NO3",
                predicted_cosine=0.035, evidence_score=0.499,
                degraded_info=True,
            ),
        ],
    )
