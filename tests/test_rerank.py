"""Unit tests for evaluation/sub6/rerank.py.

Mocked SIRIUS + CFM-ID — does not require docker / SIRIUS binary.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.sub6.rerank import (
    PeakEvidence,
    rerank_with_sirius_cfmid,
    _formula_to_mass,
    _mass_match_indicator,
    predict_with_cache,
)
from schemas.common import Candidate, Spectrum
from schemas.spectrum import PredictSpectrumRequest, PredictSpectrumResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def experimental_spec() -> Spectrum:
    """Acetylcarnitine [M+H]+ exemplar — 5 peaks, precursor 204.123."""
    return Spectrum(
        mz=[60.0808, 85.0285, 102.0550, 144.1019, 204.1234],
        intensity=[1.0, 0.8, 0.6, 0.9, 0.5],
        precursor_mz=204.1234,
        ionization_mode="positive",
        adduct="[M+H]+",
    )


def _candidate(smiles: str, score: float, name: str | None = None, source_id: str | None = None) -> Candidate:
    return Candidate(
        smiles=smiles, name=name, source="library", score=score,
        source_id=source_id, explain="test fixture",
    )


def _mock_sirius_with_top1(formula: str = "C9H17NO4", score: float = 0.9):
    fragment = SimpleNamespace(
        mz_observed=204.1234, formula=formula, formula_score=score,
        neutral_loss="", neutral_loss_formula="", intensity=0.5, depth=0,
    )
    return SimpleNamespace(
        predicted_formula=formula, formula_score=score,
        fragments=[fragment], tree_node_count=1, sirius_version="6.3.4-mock",
        explain="mock",
    )


def _mock_cfm(predict_log: list, predicted_cosine_target: float = 0.7):
    """Return a callable that records calls and returns a CFM-shaped response."""
    def _fn(req: PredictSpectrumRequest) -> PredictSpectrumResponse:
        predict_log.append(req.smiles)
        # Return a simple union spectrum overlapping experimental peaks
        # to a varying degree depending on smiles (so cosine differs).
        if "carnitine" in (req.smiles or "").lower() or "C(C[N+]" in req.smiles:
            mz = [60.0808, 85.0285, 144.1019, 204.1234]
            inten = [0.9, 0.7, 1.0, 0.5]
        else:
            mz = [50.0, 100.0, 150.0]
            inten = [1.0, 0.5, 0.3]
        spec = Spectrum(
            mz=mz, intensity=inten, precursor_mz=204.1234,
            ionization_mode="positive", adduct="[M+H]+",
        )
        return PredictSpectrumResponse(
            predicted=spec, per_energy={}, model_version="mock-cfm-4.4.7",
            explain="mock",
        )
    return _fn


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


def test_formula_to_mass_acetylcarnitine():
    # C9H17NO4 monoisotopic = 9*12.0 + 17*1.00782503 + 14.00307 + 4*15.99491 = 203.1158
    m = _formula_to_mass("C9H17NO4")
    assert m is not None
    assert abs(m - 203.1158) < 0.01


def test_formula_to_mass_invalid_returns_none():
    assert _formula_to_mass("XYZ") is None
    assert _formula_to_mass("") is None


def test_mass_match_indicator_within_5ppm():
    # acetylcarnitine M = 203.1158, [M+H]+ precursor 204.1234 → within 5 ppm
    assert _mass_match_indicator(204.1234, "C9H17NO4") == 1.0


def test_mass_match_indicator_off():
    # Wrong precursor by ~30 Da
    assert _mass_match_indicator(174.1234, "C9H17NO4") == 0.0


def test_mass_match_indicator_handles_missing_formula():
    assert _mass_match_indicator(204.1234, None) == 0.0
    assert _mass_match_indicator(204.1234, "") == 0.0


# ---------------------------------------------------------------------------
# CFM disk cache
# ---------------------------------------------------------------------------


def test_cfmid_cache_hit(tmp_path: Path, experimental_spec):
    log: list[str] = []
    fn = _mock_cfm(log)
    req = PredictSpectrumRequest(
        smiles="CC(=O)OCC(C[N+](C)(C)C)O",
        adduct="[M+H]+", ionization_mode="positive",
        collision_energies=[10.0, 20.0, 40.0],
    )
    resp1, hit1 = predict_with_cache(req, predict_fn=fn, cache_dir=tmp_path)
    resp2, hit2 = predict_with_cache(req, predict_fn=fn, cache_dir=tmp_path)
    assert hit1 is False
    assert hit2 is True
    assert len(log) == 1, "second call should hit disk cache, not invoke CFM"
    assert resp1.model_version == resp2.model_version


# ---------------------------------------------------------------------------
# Reranker — main happy path
# ---------------------------------------------------------------------------


def test_rerank_promotes_correct_candidate(tmp_path: Path, experimental_spec):
    """Correct candidate (CHNO formula matches SIRIUS top-1) is reranked above
    a candidate whose formula disagrees with SIRIUS (gets ×0.5 sanity gate)."""
    correct = _candidate(
        "CC(=O)OCC(C[N+](C)(C)C)O", score=0.50, name="acetylcarnitine", source_id="GNPS:1",
    )
    decoy = _candidate(  # sucrose; formula C12H22O11 (won't match SIRIUS C9H17NO4)
        "OC[C@H]1O[C@H](O[C@]2(CO)O[C@H](CO)[C@@H](O)[C@@H]2O)[C@H](O)[C@@H](O)[C@@H]1O",
        score=0.55, name="sucrose", source_id="GNPS:2",
    )
    # decoy has higher modcos (0.55 vs 0.50). Without rerank, decoy would win.
    log: list[str] = []
    cfm_fn = _mock_cfm(log)
    sirius_fn = lambda spec: _mock_sirius_with_top1("C9H17NO4")  # noqa: E731

    reranked, evidence = rerank_with_sirius_cfmid(
        spectrum_id="spec1",
        experimental=experimental_spec,
        candidates=[decoy, correct],
        top_k_for_rerank=2,
        use_sirius=True,
        use_cfmid=True,
        cfmid_cache_dir=tmp_path,
        sirius_fn=sirius_fn,
        cfmid_fn=cfm_fn,
    )

    # Correct candidate should now lead
    assert reranked[0].smiles == correct.smiles, "correct candidate should be reranked top-1"
    assert reranked[1].smiles == decoy.smiles

    # Peak evidence schema sanity
    pe_dict = evidence.to_dict()
    assert pe_dict["spectrum_id"] == "spec1"
    assert len(pe_dict["experimental_peaks"]) == 5
    assert pe_dict["sirius"]["top_formulas"][0]["formula"] == "C9H17NO4"
    assert "cosine_vs_experimental" in pe_dict["cfmid_top1"]
    assert len(pe_dict["candidates_evaluated"]) == 2
    # rank_after_rerank assigned
    ranks = sorted(c["rank_after_rerank"] for c in pe_dict["candidates_evaluated"])
    assert ranks == [1, 2]


def test_rerank_sirius_gate_demotes_wrong_formula(tmp_path: Path, experimental_spec):
    cand = _candidate("CCO", score=0.9, name="ethanol", source_id="X")  # C2H6O
    log: list[str] = []
    reranked, evidence = rerank_with_sirius_cfmid(
        spectrum_id="spec2",
        experimental=experimental_spec,
        candidates=[cand],
        top_k_for_rerank=1,
        use_sirius=True,
        use_cfmid=False,  # isolate SIRIUS gate effect
        cfmid_cache_dir=tmp_path,
        sirius_fn=lambda spec: _mock_sirius_with_top1("C9H17NO4"),
        cfmid_fn=_mock_cfm(log),
    )
    rec = evidence.candidates_evaluated[0]
    assert rec["sirius_match"] == 0.0
    assert rec["sirius_gate_applied"] is True
    # evidence_score should be exactly 0.5 × pre-gate value
    pre_gate = 0.4 * 0.9 + 0.0 + 0.2 * 0.0 + 0.0  # mass_match for CCO precursor 204 → 0
    assert abs(rec["evidence_score"] - 0.5 * pre_gate) < 1e-9


def test_rerank_disabled_preserves_order(tmp_path: Path, experimental_spec):
    a = _candidate("CCO", score=0.6, source_id="A")
    b = _candidate("CCC", score=0.5, source_id="B")
    reranked, _ = rerank_with_sirius_cfmid(
        spectrum_id="spec3",
        experimental=experimental_spec,
        candidates=[a, b],
        top_k_for_rerank=2,
        use_sirius=False,
        use_cfmid=False,
        cfmid_cache_dir=tmp_path,
    )
    # When sirius+cfmid both off, evidence_score = 0.4*modcos (+ small mass_match
    # if formula happens to match, but for CCO/CCC at precursor 204 it won't).
    # Order stays by modcos desc → original order preserved.
    assert [c.smiles for c in reranked] == ["CCO", "CCC"]


def test_rerank_tail_preserved(tmp_path: Path, experimental_spec):
    """Candidates beyond top_k_for_rerank are appended verbatim, not scored."""
    head = [
        _candidate("CC(=O)OCC(C[N+](C)(C)C)O", score=0.5, source_id="H1"),
        _candidate("CCO", score=0.4, source_id="H2"),
    ]
    tail = [_candidate(f"C{i}", score=0.1, source_id=f"T{i}") for i in range(3)]
    log: list[str] = []
    reranked, _ = rerank_with_sirius_cfmid(
        spectrum_id="spec4",
        experimental=experimental_spec,
        candidates=head + tail,
        top_k_for_rerank=2,
        use_sirius=False,
        use_cfmid=False,
        cfmid_cache_dir=tmp_path,
        sirius_fn=lambda spec: _mock_sirius_with_top1(),
        cfmid_fn=_mock_cfm(log),
    )
    assert len(reranked) == len(head) + len(tail)
    # Tail order preserved verbatim
    assert [c.source_id for c in reranked[-3:]] == ["T0", "T1", "T2"]


def test_rerank_cfmid_failure_does_not_kill_run(tmp_path: Path, experimental_spec):
    """If CFM-ID raises for one candidate, that candidate gets predicted_cosine=0
    and the rerank still completes."""
    def _crashing_cfm(req):
        raise RuntimeError("simulated CFM container down")

    cand = _candidate("CC(=O)OCC(C[N+](C)(C)C)O", score=0.7, source_id="X")
    reranked, evidence = rerank_with_sirius_cfmid(
        spectrum_id="spec5",
        experimental=experimental_spec,
        candidates=[cand],
        top_k_for_rerank=1,
        use_sirius=False,
        use_cfmid=True,
        cfmid_cache_dir=tmp_path,
        cfmid_fn=_crashing_cfm,
    )
    rec = evidence.candidates_evaluated[0]
    assert rec["predicted_cosine"] == 0.0
    assert reranked[0].smiles == cand.smiles


# ---------------------------------------------------------------------------
# SIRIUS auto-relogin retry
# ---------------------------------------------------------------------------


def test_sirius_login_error_classifier():
    from evaluation.sub6.rerank import _is_sirius_login_error
    class FakeError(Exception):
        pass
    assert _is_sirius_login_error(FakeError("This build requires login before running formula trees"))
    assert _is_sirius_login_error(FakeError("Not Logged in, No valid refresh token Available"))
    assert _is_sirius_login_error(FakeError("HTTP 401 Client Error"))
    assert not _is_sirius_login_error(FakeError("Java OOM"))
    assert not _is_sirius_login_error(FakeError("connection refused"))


def test_sirius_retry_on_login_error_then_success(tmp_path: Path, experimental_spec, monkeypatch):
    """SIRIUS fn raises login error first call, then returns valid response.
    With env vars set + relogin success, second call should be invoked."""
    import evaluation.sub6.rerank as rerank_mod
    rerank_mod._LAST_RELOGIN_TS = 0.0  # reset throttle

    monkeypatch.setenv("METAGENT_SIRIUS_USER", "test@example.com")
    monkeypatch.setenv("METAGENT_SIRIUS_PASS", "secret")
    monkeypatch.setattr(rerank_mod, "_maybe_relogin_sirius", lambda: True)

    call_log: list[int] = []
    def _flaky_sirius(spec):
        call_log.append(1)
        if len(call_log) == 1:
            from tools.sirius.errors import SiriusNotInstalledError
            raise SiriusNotInstalledError("requires login before running formula trees")
        return _mock_sirius_with_top1("C9H17NO4")

    cand = _candidate("CC(=O)OCC(C[N+](C)(C)C)O", score=0.5, source_id="A")
    reranked, evidence = rerank_with_sirius_cfmid(
        spectrum_id="retry-spec",
        experimental=experimental_spec,
        candidates=[cand],
        top_k_for_rerank=1,
        use_sirius=True,
        use_cfmid=False,
        cfmid_cache_dir=tmp_path,
        sirius_fn=_flaky_sirius,
    )
    assert len(call_log) == 2, "SIRIUS should be retried once after relogin"
    assert evidence.sirius["top_formulas"][0]["formula"] == "C9H17NO4"


def test_sirius_no_retry_on_non_login_error(tmp_path: Path, experimental_spec, monkeypatch):
    """Non-login errors should NOT trigger relogin retry."""
    import evaluation.sub6.rerank as rerank_mod
    monkeypatch.setenv("METAGENT_SIRIUS_USER", "test@example.com")
    monkeypatch.setenv("METAGENT_SIRIUS_PASS", "secret")
    monkeypatch.setattr(rerank_mod, "_maybe_relogin_sirius", lambda: True)

    call_log: list[int] = []
    def _crashing_sirius(spec):
        call_log.append(1)
        raise RuntimeError("Java OOM")

    cand = _candidate("CCO", score=0.5, source_id="A")
    _, evidence = rerank_with_sirius_cfmid(
        spectrum_id="oom-spec",
        experimental=experimental_spec,
        candidates=[cand],
        top_k_for_rerank=1,
        use_sirius=True,
        use_cfmid=False,
        cfmid_cache_dir=tmp_path,
        sirius_fn=_crashing_sirius,
    )
    assert len(call_log) == 1, "Non-login errors must not trigger retry"
    assert "OOM" in evidence.sirius.get("error", "")


def test_sirius_relogin_throttle(tmp_path: Path, experimental_spec, monkeypatch):
    """Throttle: relogin must not fire twice within MIN_INTERVAL."""
    import evaluation.sub6.rerank as rerank_mod
    rerank_mod._LAST_RELOGIN_TS = time.time()  # pretend we just relogged in
    import time as _time

    relogin_calls: list[int] = []
    def _record_relogin():
        relogin_calls.append(1)
        return True
    monkeypatch.setenv("METAGENT_SIRIUS_USER", "u@x")
    monkeypatch.setenv("METAGENT_SIRIUS_PASS", "p")
    # Don't patch _maybe_relogin_sirius — exercise the real one's throttle.
    # Patch the subprocess so even if it does fire, no real shell-out.
    monkeypatch.setattr(rerank_mod.subprocess, "run", lambda *a, **kw: type("R", (), {"stdout": "Login successful!", "stderr": ""})())
    # Within throttle window: returns False without invoking subprocess.
    assert rerank_mod._maybe_relogin_sirius() is False
