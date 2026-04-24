"""Stage-7 (literature_search) wiring tests for ``run_full_pipeline.identify``.

Pins the contract added in 2026-04-24:

* ``identify(..., literature_top_n=N)`` calls ``literature_search_fn``
  exactly N times — one per top-N candidate after the evidence-score
  sort. The records land in ``CandidateReport.literature_records``.
* ``literature_top_n=0`` skips Stage 7 entirely (zero literature_search
  calls, empty records lists, skip note in pipeline warnings).
* Per-candidate failures degrade gracefully (empty records + per-cand
  note + aggregate warning); other candidates are unaffected.
* Candidates with ``name=None`` skip Stage 7 (free-text query on raw
  SMILES is too noisy in v0).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from schemas import (
    Candidate,
    GenerateRequest,
    GenerateResponse,
    LibrarySearchResponse,
    LiteratureRecord,
    LiteratureSearchRequest,
    LiteratureSearchResponse,
    MetaboliteInfoResponse,
    PathwayContextResponse,
    PredictSpectrumResponse,
    PrefilteredCandidate,
    PrefilterResponse,
    PreprocessRequest,
    PreprocessResponse,
    Spectrum,
    ToolError,
)
from scripts.run_full_pipeline import identify


# Reuse stubs that mirror those in test_pipeline_fp_strategy.py.
def _stub_spectrum() -> Spectrum:
    return Spectrum(
        mz=[100.0, 150.0, 181.07], intensity=[0.4, 0.7, 1.0],
        precursor_mz=181.07, adduct="[M+H]+",
        ionization_mode="positive", collision_energy=20.0,
    )


def _stub_preprocess(req: PreprocessRequest) -> PreprocessResponse:
    spec = _stub_spectrum()
    return PreprocessResponse(
        spectrum=spec, n_peaks_in=len(req.raw_mz), n_peaks_out=len(spec.mz),
        base_peak_mz=spec.mz[-1], base_peak_intensity=1.0,
        quality_flag="sparse", explain="stub",
    )


def _stub_pool() -> list[PrefilteredCandidate]:
    return [
        PrefilteredCandidate(
            smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
            name="Glucose-pool", source_pool="pubchem_lite",
            source_id="CID:5793", molecular_formula="C6H12O6",
            exact_mass=180.063, mass_error_ppm=0.2,
            has_reference_spectrum=False,
        ),
    ]


def _stub_prefilter(req: Any) -> PrefilterResponse:
    return PrefilterResponse(
        candidates=_stub_pool(),
        neutral_mass_computed=req.precursor_mz - 1.00728,
        n_by_pool={"pubchem_lite": 1}, explain="stub",
    )


def _stub_library_search_with_named(req: Any) -> LibrarySearchResponse:
    """Return 3 named library candidates so we can vary which got
    literature_search calls."""
    return LibrarySearchResponse(
        candidates=[
            Candidate(
                smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
                name="Glucose", source="library", score=0.9,
                source_id="LIB1", explain="stub",
            ),
            Candidate(
                smiles="OCC1OC(O)C(O)C(O)C1O",
                name="Gulose", source="library", score=0.8,
                source_id="LIB2", explain="stub",
            ),
            Candidate(
                smiles="C(C(C(C(C(CO)O)O)O)O)O",
                name="Sorbitol", source="library", score=0.6,
                source_id="LIB3", explain="stub",
            ),
        ],
        libraries_searched=["inhouse"], n_total_compared=3, explain="stub",
    )


def _stub_library_search_with_nameless(req: Any) -> LibrarySearchResponse:
    """One named, two nameless candidates — verifies name-skip rule."""
    return LibrarySearchResponse(
        candidates=[
            Candidate(
                smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
                name="Glucose", source="library", score=0.9,
                source_id="LIB1", explain="stub",
            ),
            Candidate(
                smiles="OCC1OC(O)C(O)C(O)C1O",
                name=None, source="library", score=0.8,
                source_id="LIB2", explain="stub",
            ),
        ],
        libraries_searched=["inhouse"], n_total_compared=2, explain="stub",
    )


def _stub_generate(req: Any, **kwargs) -> GenerateResponse:
    return GenerateResponse(
        candidates=[], n_generated_raw=0, n_valid=0, explain="stub",
    )


def _stub_metabolite_info(req: Any) -> MetaboliteInfoResponse:
    return MetaboliteInfoResponse(found=False, explain="stub-miss")


def _stub_pathway_context(req: Any) -> PathwayContextResponse:
    return PathwayContextResponse(
        pathways=[], upstream_neighbours=[], downstream_neighbours=[],
        cooccurrence_score=0.0, plausibility_summary="X", explain="X",
    )


def _stub_predict_spectrum(req: Any) -> PredictSpectrumResponse:
    return PredictSpectrumResponse(
        predicted=_stub_spectrum(),
        per_energy={20.0: _stub_spectrum()},
        model_version="stub-1.0", explain="stub",
    )


class _RecordingLiteratureFn:
    """Captures every literature_search call so tests can assert which
    candidates triggered F."""
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, req: LiteratureSearchRequest) -> LiteratureSearchResponse:
        self.calls.append({
            "query": req.query, "max_results": req.max_results,
        })
        # Return one canned record per call so we can verify it lands in
        # CandidateReport.literature_records.
        rec = LiteratureRecord(
            pmid=f"{10000000 + len(self.calls)}",
            title=f"Paper for {req.query}",
            abstract="abstract", authors=["A"],
            year=2020, journal="Journal", doi=None,
            url="https://europepmc.org/MED/12345",
        )
        return LiteratureSearchResponse(
            records=[rec], query_used=req.query, explain="stub",
        )


def _identify_kwargs(
    *, library_search_fn, literature_search_fn, generate_fn=_stub_generate,
):
    return dict(
        preprocess_fn=_stub_preprocess,
        prefilter_fn=_stub_prefilter,
        library_search_fn=library_search_fn,
        generate_fn=generate_fn,
        fetch_metabolite_info_fn=_stub_metabolite_info,
        pathway_context_fn=_stub_pathway_context,
        predict_spectrum_fn=_stub_predict_spectrum,
        literature_search_fn=literature_search_fn,
    )


def _raw_input() -> PreprocessRequest:
    return PreprocessRequest(
        raw_mz=[100.0, 150.0, 181.07],
        raw_intensity=[40.0, 70.0, 100.0],
        precursor_mz=181.07, adduct="[M+H]+",
        ionization_mode="positive", collision_energy=20.0,
    )


# ---------------------------------------------------------------------------
# Default behaviour — top-3 enrichment
# ---------------------------------------------------------------------------


def test_literature_search_called_once_per_top_n_candidate():
    rec = _RecordingLiteratureFn()
    report = identify(
        _raw_input(),
        literature_top_n=3,
        **_identify_kwargs(
            library_search_fn=_stub_library_search_with_named,
            literature_search_fn=rec,
        ),
    )
    assert len(rec.calls) == 3
    # Each top-N candidate now has 1 literature_record
    for cr in report.candidates[:3]:
        assert len(cr.literature_records) == 1
    # Lower-ranked candidates (none beyond top-3 in this fixture, but
    # check for completeness)
    for cr in report.candidates[3:]:
        assert cr.literature_records == []


def test_literature_top_n_zero_skips_stage_completely():
    rec = _RecordingLiteratureFn()
    report = identify(
        _raw_input(),
        literature_top_n=0,
        **_identify_kwargs(
            library_search_fn=_stub_library_search_with_named,
            literature_search_fn=rec,
        ),
    )
    assert rec.calls == []
    for cr in report.candidates:
        assert cr.literature_records == []
    assert any(
        "literature_search: skipped (literature_top_n=0)" in w
        for w in report.warnings
    )


def test_literature_top_n_smaller_than_candidates():
    """top-N=2 against 3 candidates: only top 2 get F."""
    rec = _RecordingLiteratureFn()
    report = identify(
        _raw_input(),
        literature_top_n=2,
        **_identify_kwargs(
            library_search_fn=_stub_library_search_with_named,
            literature_search_fn=rec,
        ),
    )
    assert len(rec.calls) == 2
    assert len(report.candidates[0].literature_records) == 1
    assert len(report.candidates[1].literature_records) == 1
    assert report.candidates[2].literature_records == []


def test_literature_top_n_larger_than_candidates():
    """top-N=10 against 3 candidates: only 3 calls (no padding)."""
    rec = _RecordingLiteratureFn()
    report = identify(
        _raw_input(),
        literature_top_n=10,
        **_identify_kwargs(
            library_search_fn=_stub_library_search_with_named,
            literature_search_fn=rec,
        ),
    )
    assert len(rec.calls) == 3


# ---------------------------------------------------------------------------
# Name-skip rule
# ---------------------------------------------------------------------------


def test_nameless_candidate_skipped_with_note():
    """A candidate with name=None is skipped — query on raw SMILES is
    too noisy in v0. The other named candidate still gets F."""
    rec = _RecordingLiteratureFn()
    report = identify(
        _raw_input(),
        literature_top_n=2,
        **_identify_kwargs(
            library_search_fn=_stub_library_search_with_nameless,
            literature_search_fn=rec,
        ),
    )
    # Only the named candidate triggered a call.
    assert len(rec.calls) == 1
    assert "Glucose" in rec.calls[0]["query"]
    # The nameless candidate has empty records + a per-cand note
    nameless = [cr for cr in report.candidates
                if cr.candidate.name is None][0]
    assert nameless.literature_records == []
    assert any("skipped" in n and "no name" in n for n in nameless.notes)


# ---------------------------------------------------------------------------
# Per-candidate degradation
# ---------------------------------------------------------------------------


def _flaky_literature_fn():
    """First call succeeds, second raises, third succeeds."""
    state = {"n": 0}
    def _fn(req: LiteratureSearchRequest) -> LiteratureSearchResponse:
        state["n"] += 1
        if state["n"] == 2:
            raise RuntimeError("flaky upstream")
        rec = LiteratureRecord(
            pmid=f"{10000000 + state['n']}", title=f"P{state['n']}",
            abstract="x", authors=["A"], year=2020, journal="J",
            doi=None, url="https://europepmc.org/MED/x",
        )
        return LiteratureSearchResponse(
            records=[rec], query_used=req.query, explain="stub",
        )
    return _fn


def test_per_candidate_failure_degrades_only_that_candidate():
    report = identify(
        _raw_input(),
        literature_top_n=3,
        **_identify_kwargs(
            library_search_fn=_stub_library_search_with_named,
            literature_search_fn=_flaky_literature_fn(),
        ),
    )
    # 2 candidates got records, 1 was empty + noted
    n_with_records = sum(
        1 for cr in report.candidates[:3] if cr.literature_records
    )
    assert n_with_records == 2
    n_skipped = sum(
        1 for cr in report.candidates[:3]
        if any("UNEXPECTED RuntimeError" in n
               or "literature_search:" in n and not cr.literature_records
               for n in cr.notes)
    )
    assert n_skipped == 1
    # Aggregate warning fires on degraded count > 0
    assert any("ran with degraded output" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# Default — no kwarg passed
# ---------------------------------------------------------------------------


def test_default_literature_top_n_is_three():
    rec = _RecordingLiteratureFn()
    identify(
        _raw_input(),
        # no literature_top_n passed; default is 3
        **_identify_kwargs(
            library_search_fn=_stub_library_search_with_named,
            literature_search_fn=rec,
        ),
    )
    assert len(rec.calls) == 3
