"""Phase 6.7 — verify run_casmi.py wires LLM chat_fn into identify_spectrum
when --reranker=llm. Uses argparse only (no subprocess) and asserts the
helper functions resolve correctly."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def test_resolve_narrative_llm_opus47():
    from evaluation.sub6.run_sub6a import resolve_narrative_llm
    provider, model = resolve_narrative_llm("opus47")
    assert provider == "openai"
    assert "claude-opus" in model


def test_run_casmi_imports_llm_helpers():
    """Smoke-test that the new imports resolve."""
    from scripts.eval_sub6 import run_casmi
    assert hasattr(run_casmi, "_resolve_llm_keys")
    assert hasattr(run_casmi, "resolve_narrative_llm")
    assert hasattr(run_casmi, "_chat_kwargs")


def test_parse_args_includes_narrative_llm():
    """--narrative-llm flag exists with the right choices."""
    from scripts.eval_sub6 import run_casmi
    parser = run_casmi._parse_args
    # call argparse with required arg + new flag
    import argparse, sys as _sys
    old = _sys.argv
    try:
        _sys.argv = ["run_casmi.py", "--out-dir", "/tmp/x",
                     "--reranker", "llm", "--narrative-llm", "opus47"]
        args = parser()
        assert args.reranker == "llm"
        assert args.narrative_llm == "opus47"
        assert args.llm_temperature == 0.0
    finally:
        _sys.argv = old


def test_llm_path_passes_chat_fn(monkeypatch, tmp_path):
    """When --reranker=llm, identify_spectrum must receive llm_chat_fn."""
    from scripts.eval_sub6 import run_casmi

    captured = {}

    def fake_identify_spectrum(*args, **kwargs):
        captured["llm_chat_fn"] = kwargs.get("llm_chat_fn")
        captured["llm_chat_kwargs"] = kwargs.get("llm_chat_kwargs")
        captured["reranker_mode"] = kwargs.get("reranker_mode")

        class _Stub:
            spectrum_id = "t1"
            source_id = None
            gt_inchikey_first_block = None
            predicted_inchikey_first_block = None
            predicted_name = None
            predicted_smiles = None
            predicted_score = None
            predicted_source_id = None
            correct_top1 = None
            n_candidates_returned = 0
            n_after_exclusion = 0
            primary_retriever = "msclip"
            reranker_mode = "llm"
            rerank_applied = ()
            peak_evidence = None
            llm_rerank_narrative = "stub"
            llm_rerank_peak_claims = []
            llm_rerank_confidence = "low"
            llm_rerank_fallback_used = False
            llm_rerank_parse_error = None
            llm_rerank_ranked_indices = []
            ranked_candidates = []
            error = None

        return _Stub()

    # Patch identify_spectrum + the CASMI loader to avoid touching disk.
    monkeypatch.setattr(run_casmi, "identify_spectrum", fake_identify_spectrum)

    from evaluation.sub6.casmi_loader import CasmiSpec
    fake_spec = CasmiSpec(
        spectrum_id="t1", dataset="casmi2022", formula="C2H6O", smiles="CCO",
        inchikey="LFQSCWFLJHTTHZ-UHFFFAOYSA-N", inchikey_first_block="LFQSCWFLJHTTHZ",
        adduct="[M+H]+", ion_mode="positive", precursor_mz=47.0,
        peaks=[(46.0, 100.0), (29.0, 50.0)],
    )
    monkeypatch.setattr(run_casmi, "load_casmi_2022_specs", lambda root: [fake_spec])

    class _Retr:
        @classmethod
        def from_dir(cls, _):
            return cls()
        def candidates_for_formula(self, _):
            return ["CCO"]
    monkeypatch.setattr(run_casmi, "PubChemRetrievalIndex", _Retr)

    def _build_pool(*args, **kwargs):
        from schemas.common import PrefilteredCandidate
        return [PrefilteredCandidate(
            smiles="CCO", name=None, source_pool="pubchem_lite",
            source_id="PUB:test#0", molecular_formula="C2H6O",
            exact_mass=46.04186, mass_error_ppm=0.0,
            has_reference_spectrum=False,
        )]
    monkeypatch.setattr(run_casmi, "build_pubchem_pool", _build_pool)

    # Patch root existence check
    monkeypatch.setattr(run_casmi, "DEFAULT_CASMI_2022_ROOT", tmp_path)
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "retrieval_hdf").mkdir(exist_ok=True)

    # Patch api-key loader (so it doesn't crash on missing key files in CI).
    monkeypatch.setattr(run_casmi, "_resolve_llm_keys", lambda *a, **k: None)

    # And the llm_client.chat we expect to be threaded through.
    monkeypatch.setattr(run_casmi.llm_client, "chat", lambda *a, **k: '{"ok":1}')

    import sys as _sys
    out_dir = tmp_path / "out"
    old = _sys.argv
    try:
        _sys.argv = [
            "run_casmi.py", "--casmi", "2022", "--out-dir", str(out_dir),
            "--reranker", "llm", "--narrative-llm", "opus47",
            "--limit", "1",
        ]
        run_casmi.main()
    finally:
        _sys.argv = old

    # The critical assertions: chat_fn was threaded.
    assert captured["llm_chat_fn"] is not None
    assert captured["reranker_mode"] == "llm"
    assert captured["llm_chat_kwargs"]["caller"] == "casmi_llm_reranker"
    assert "model" in captured["llm_chat_kwargs"]
