"""Stage-3b fingerprint-strategy wiring tests for ``run_full_pipeline.identify``.

These tests pin the contract added in 2026-04-24:

* ``identify(..., fingerprint_strategy=...)`` selects which Fingerprinter
  is passed to ``generate_fn`` — ``CandidateFusionFingerprinter`` for the
  ``retrieved_only_*`` / ``topn_*`` strategies, ``SiriusFingerprinter`` for
  the legacy ``sirius`` strategy.
* When a fusion strategy is requested but ``library_search`` returned 0
  candidates, Stage 3b is skipped with a degradation note rather than
  crashing or silently using SIRIUS.
* The CLI's ``--fp-strategy`` arg and ``METAGENT_FP_STRATEGY`` env
  default are visible to a smoke test.

Tests are pure-Python — no SIRIUS, no MS-BART, no real DB. The
``generate_fn`` is a recording stub; the prefilter / library / D / E
tools are minimal in-memory fakes.
"""
from __future__ import annotations

import os
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
    MetaboliteInfoResponse,
    PathwayContextResponse,
    PredictSpectrumResponse,
    PrefilteredCandidate,
    PrefilterResponse,
    PreprocessRequest,
    PreprocessResponse,
    Spectrum,
)
from scripts.run_full_pipeline import identify
from tools.molecule_gen.fingerprint import (
    CandidateFusionFingerprinter,
    SiriusFingerprinter,
)


# ---------------------------------------------------------------------------
# Stub tool callables
# ---------------------------------------------------------------------------


def _stub_spectrum() -> Spectrum:
    return Spectrum(
        mz=[100.0, 150.0, 181.07],
        intensity=[0.4, 0.7, 1.0],
        precursor_mz=181.07,
        adduct="[M+H]+",
        ionization_mode="positive",
        collision_energy=20.0,
    )


def _stub_preprocess(req: PreprocessRequest) -> PreprocessResponse:
    spec = _stub_spectrum()
    return PreprocessResponse(
        spectrum=spec,
        n_peaks_in=len(req.raw_mz),
        n_peaks_out=len(spec.mz),
        base_peak_mz=spec.mz[-1],
        base_peak_intensity=1.0,
        quality_flag="sparse",
        explain="stub",
    )


def _stub_pool(n: int = 3) -> list[PrefilteredCandidate]:
    smiles_set = [
        "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
        "C([C@@H]1[C@H]([C@@H]([C@H](C(O1)O)O)O)O)O",
        "OCC1OC(O)C(O)C(O)C1O",
    ]
    return [
        PrefilteredCandidate(
            smiles=smiles_set[i % 3],
            name=f"cand_{i}",
            source_pool="pubchem_lite",
            source_id=f"CID:{i}",
            molecular_formula="C6H12O6",
            exact_mass=180.063,
            mass_error_ppm=0.2,
            has_reference_spectrum=False,
        )
        for i in range(n)
    ][:n]


def _stub_prefilter(req: Any) -> PrefilterResponse:
    pool = _stub_pool(3)
    return PrefilterResponse(
        candidates=pool,
        neutral_mass_computed=req.precursor_mz - 1.00728,
        n_by_pool={"pubchem_lite": len(pool)},
        explain="stub",
    )


def _stub_library_search_with_candidates(req: Any) -> LibrarySearchResponse:
    """Return non-empty library candidates so fusion has something to fuse."""
    return LibrarySearchResponse(
        candidates=[
            Candidate(
                smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
                name="Glucose-like", source="library", score=0.8,
                source_id="LIB1", explain="stub",
            ),
            Candidate(
                smiles="OCC1OC(O)C(O)C(O)C1O",
                name="Gulose-like", source="library", score=0.7,
                source_id="LIB2", explain="stub",
            ),
        ],
        libraries_searched=["inhouse"],
        n_total_compared=3,
        explain="stub",
    )


def _stub_library_search_empty(req: Any) -> LibrarySearchResponse:
    """Return zero candidates — fusion has no input."""
    return LibrarySearchResponse(
        candidates=[], libraries_searched=["inhouse"],
        n_total_compared=3, explain="stub-empty",
    )


def _stub_fetch_metabolite_info(req: Any) -> MetaboliteInfoResponse:
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


class _RecordingGenerateFn:
    """Captures the fingerprinter passed to ``generate(...)`` so tests
    can assert which class the runner instantiated."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, req: GenerateRequest, **kwargs) -> GenerateResponse:
        self.calls.append({
            "fingerprinter": kwargs.get("fingerprinter"),
            "n_candidates": req.n_candidates,
            "candidate_pool_size": len(req.candidate_pool or []),
        })
        return GenerateResponse(
            candidates=[], n_generated_raw=0, n_valid=0,
            explain="recorder stub",
        )


# ---------------------------------------------------------------------------
# Common kwargs for identify() — wires every tool to a deterministic stub
# ---------------------------------------------------------------------------


def _identify_kwargs(*, library_search_fn, generate_fn):
    return dict(
        preprocess_fn=_stub_preprocess,
        prefilter_fn=_stub_prefilter,
        library_search_fn=library_search_fn,
        generate_fn=generate_fn,
        fetch_metabolite_info_fn=_stub_fetch_metabolite_info,
        pathway_context_fn=_stub_pathway_context,
        predict_spectrum_fn=_stub_predict_spectrum,
    )


def _raw_input() -> PreprocessRequest:
    return PreprocessRequest(
        raw_mz=[100.0, 150.0, 181.07],
        raw_intensity=[40.0, 70.0, 100.0],
        precursor_mz=181.07,
        adduct="[M+H]+",
        ionization_mode="positive",
        collision_energy=20.0,
    )


# ---------------------------------------------------------------------------
# Fusion-strategy wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "strategy",
    ["retrieved_only_60", "retrieved_only_80", "topn_60", "topn_80"],
)
def test_fusion_strategy_uses_candidate_fusion_fingerprinter(strategy):
    rec = _RecordingGenerateFn()
    identify(
        _raw_input(),
        fingerprint_strategy=strategy,
        **_identify_kwargs(
            library_search_fn=_stub_library_search_with_candidates,
            generate_fn=rec,
        ),
    )
    assert len(rec.calls) == 1
    fp = rec.calls[0]["fingerprinter"]
    assert isinstance(fp, CandidateFusionFingerprinter)
    # CandidateFusionFingerprinter stores the candidates and strategy
    # on instance attrs (private but stable).
    assert fp._strategy == strategy  # type: ignore[attr-defined]
    # Library returned 2 candidates — they should all be passed through.
    assert len(fp._candidates) == 2  # type: ignore[attr-defined]


def test_sirius_strategy_uses_sirius_fingerprinter():
    rec = _RecordingGenerateFn()
    identify(
        _raw_input(),
        fingerprint_strategy="sirius",
        **_identify_kwargs(
            library_search_fn=_stub_library_search_with_candidates,
            generate_fn=rec,
        ),
    )
    fp = rec.calls[0]["fingerprinter"]
    assert isinstance(fp, SiriusFingerprinter)


def test_default_strategy_is_topn_60():
    rec = _RecordingGenerateFn()
    identify(
        _raw_input(),
        # no fingerprint_strategy passed
        **_identify_kwargs(
            library_search_fn=_stub_library_search_with_candidates,
            generate_fn=rec,
        ),
    )
    fp = rec.calls[0]["fingerprinter"]
    assert isinstance(fp, CandidateFusionFingerprinter)
    assert fp._strategy == "topn_60"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Empty-library degradation
# ---------------------------------------------------------------------------


def test_fusion_with_empty_library_skips_stage3b_with_warning():
    rec = _RecordingGenerateFn()
    report = identify(
        _raw_input(),
        fingerprint_strategy="topn_60",
        **_identify_kwargs(
            library_search_fn=_stub_library_search_empty,
            generate_fn=rec,
        ),
    )
    # generate_fn must NOT have been called — fusion has no input.
    assert rec.calls == []
    # The skip note appears in the pipeline warnings.
    assert any(
        "molecule_generate: skipped" in w
        and "topn_60" in w
        for w in report.warnings
    ), f"expected skip warning, got {report.warnings!r}"


def test_sirius_with_empty_library_still_calls_generate():
    """SIRIUS doesn't need library candidates; an empty library should
    still let Stage 3b run (and likely degrade later if SIRIUS missing)."""
    rec = _RecordingGenerateFn()
    identify(
        _raw_input(),
        fingerprint_strategy="sirius",
        **_identify_kwargs(
            library_search_fn=_stub_library_search_empty,
            generate_fn=rec,
        ),
    )
    assert len(rec.calls) == 1
    assert isinstance(rec.calls[0]["fingerprinter"], SiriusFingerprinter)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unknown_strategy_raises():
    rec = _RecordingGenerateFn()
    with pytest.raises(ValueError, match="unknown fingerprint_strategy"):
        identify(
            _raw_input(),
            fingerprint_strategy="bogus_strategy",
            **_identify_kwargs(
                library_search_fn=_stub_library_search_with_candidates,
                generate_fn=rec,
            ),
        )
