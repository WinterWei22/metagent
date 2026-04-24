"""Smoke tests for ui.data.loaders."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def test_list_log_trace_ids_empty_when_no_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ui.data.loaders as L

    monkeypatch.setattr(L, "_LOG_PATH", tmp_path / "nope.jsonl")
    assert L.list_log_trace_ids() == []


def test_load_cached_run_none_when_no_report_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ui.data.loaders as L

    monkeypatch.setattr(L, "_LOG_PATH", tmp_path / "llm.jsonl")
    monkeypatch.setattr(L, "_DATA_CACHE", tmp_path / "cache")
    monkeypatch.setattr(L, "_TMP_O1", tmp_path / "tmp_o1")
    monkeypatch.setattr(L, "_REPO_PIPELINE_RUNS", tmp_path / "runs")
    assert L.load_cached_run("glucose_pos") is None


def test_load_cached_run_finds_tmp_o1_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When only the /tmp/o1 fallback exists, loader still returns a CachedRun."""
    import ui.data.loaders as L

    log = tmp_path / "llm.jsonl"
    log.write_text(
        json.dumps(
            {
                "caller": "orchestrator.naive.identify",
                "trace_id": "o1-part4-glucose_pos",
                "response_cleaned": "hello",
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "usr"},
                ],
                "elapsed_ms": 1000,
                "model": "MiniMax-M2.7",
            }
        )
        + "\n"
    )
    tmp_o1 = tmp_path / "tmp_o1"
    tmp_o1.mkdir()
    (tmp_o1 / "glucose_pos.json").write_text(
        json.dumps(
            {
                "experimental_spectrum": {
                    "mz": [100.0],
                    "intensity": [1.0],
                    "precursor_mz": 181.0707,
                    "adduct": "[M+H]+",
                    "ionization_mode": "positive",
                },
                "preprocess_quality_flag": "good",
                "neutral_mass_computed": 180.0634,
                "n_prefilter_candidates": 5,
                "n_library_candidates": 1,
                "n_generated_candidates": 0,
                "candidates": [],
                "pipeline_version": "test:1",
                "tool_versions": {},
                "warnings": [],
            }
        )
    )

    monkeypatch.setattr(L, "_LOG_PATH", log)
    monkeypatch.setattr(L, "_DATA_CACHE", tmp_path / "cache_missing")
    monkeypatch.setattr(L, "_TMP_O1", tmp_o1)
    monkeypatch.setattr(L, "_REPO_PIPELINE_RUNS", tmp_path / "runs_missing")

    run = L.load_cached_run("glucose_pos")
    assert run is not None
    assert run.fixture == "glucose_pos"
    assert run.trace_id == "o1-part4-glucose_pos"
    assert run.report["preprocess_quality_flag"] == "good"
    assert run.llm_row["response_cleaned"] == "hello"


def test_load_cached_run_handles_matchms_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live pipeline stdout prefixes a matchms WARNING before the JSON body;
    the loader must strip that gracefully (O1 Part 4 flow)."""
    import ui.data.loaders as L

    raw_json = json.dumps(
        {
            "experimental_spectrum": {
                "mz": [],
                "intensity": [],
                "precursor_mz": 100.0,
                "adduct": "[M+H]+",
                "ionization_mode": "positive",
            },
            "preprocess_quality_flag": "good",
            "neutral_mass_computed": 99.0,
            "n_prefilter_candidates": 0,
            "n_library_candidates": 0,
            "n_generated_candidates": 0,
            "candidates": [],
            "pipeline_version": "test:1",
            "tool_versions": {},
            "warnings": [],
        }
    )
    tmp_o1 = tmp_path / "tmp_o1"
    tmp_o1.mkdir()
    (tmp_o1 / "caffeine_pos.json").write_text(
        "2026-04-23 21:06:22,736:WARNING:matchms:"
        "add_precursor_mz:No precursor_mz found in metadata.\n"
        + raw_json
    )

    monkeypatch.setattr(L, "_LOG_PATH", tmp_path / "nolog.jsonl")
    monkeypatch.setattr(L, "_DATA_CACHE", tmp_path / "cache_missing")
    monkeypatch.setattr(L, "_TMP_O1", tmp_o1)
    monkeypatch.setattr(L, "_REPO_PIPELINE_RUNS", tmp_path / "runs_missing")

    run = L.load_cached_run("caffeine_pos")
    assert run is not None
    assert run.report["preprocess_quality_flag"] == "good"


# ---------------------------------------------------------------------------
# Verifier sidecar loading (UI/V1)
# ---------------------------------------------------------------------------


def _stub_report(precursor: float = 100.0) -> dict:
    return {
        "experimental_spectrum": {
            "mz": [],
            "intensity": [],
            "precursor_mz": precursor,
            "adduct": "[M+H]+",
            "ionization_mode": "positive",
        },
        "preprocess_quality_flag": "good",
        "neutral_mass_computed": precursor - 1.00728,
        "n_prefilter_candidates": 0,
        "n_library_candidates": 0,
        "n_generated_candidates": 0,
        "candidates": [],
        "pipeline_version": "test:1",
        "tool_versions": {},
        "warnings": [],
    }


def _wire_loader(monkeypatch, tmp_path, *, verifier_dir):
    """Point all loader paths at tmp_path + verifier_dir for isolation."""
    import ui.data.loaders as L

    monkeypatch.setattr(L, "_LOG_PATH", tmp_path / "log.jsonl")
    monkeypatch.setattr(L, "_DATA_CACHE", tmp_path / "cache")
    monkeypatch.setattr(L, "_TMP_O1", tmp_path / "tmp_o1")
    monkeypatch.setattr(L, "_REPO_PIPELINE_RUNS", tmp_path / "runs")
    monkeypatch.setattr(L, "_VERIFIER_RUNS", verifier_dir)
    return L


def test_load_verifier_verdict_returns_none_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    L = _wire_loader(monkeypatch, tmp_path, verifier_dir=tmp_path / "verifier")
    assert L.load_verifier_verdict("nonexistent-trace") is None


def test_load_verifier_verdict_returns_none_when_trace_id_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    L = _wire_loader(monkeypatch, tmp_path, verifier_dir=tmp_path / "verifier")
    assert L.load_verifier_verdict("") is None


def test_load_verifier_verdict_reads_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier_dir = tmp_path / "verifier"
    verifier_dir.mkdir()
    payload = {
        "trace_id": "abc_verified",
        "overall_verdict": "partially_verified",
        "claims_v2": [
            {"claim_text": "X", "claim_type": "grounded_claim",
             "verdict": "supported", "evidence": "src", "source_field": "x",
             "correction": None},
        ],
        "llm_call_count": 5,
        "rewritten_output": "rewritten",
        "source_llm_output": "source",
        "verification_warnings": [],
    }
    (verifier_dir / "abc.verifier.json").write_text(json.dumps(payload))

    L = _wire_loader(monkeypatch, tmp_path, verifier_dir=verifier_dir)
    got = L.load_verifier_verdict("abc")
    assert got is not None
    assert got["overall_verdict"] == "partially_verified"
    assert got["llm_call_count"] == 5


def test_load_verifier_verdict_handles_bad_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier_dir = tmp_path / "verifier"
    verifier_dir.mkdir()
    (verifier_dir / "abc.verifier.json").write_text("not json {{{")

    L = _wire_loader(monkeypatch, tmp_path, verifier_dir=verifier_dir)
    assert L.load_verifier_verdict("abc") is None


def test_load_cached_run_attaches_verifier_row_when_sidecar_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: report on disk + log row + verifier sidecar all line up."""
    log = tmp_path / "log.jsonl"
    log.write_text(
        json.dumps({
            "caller": "orchestrator.naive.identify",
            "trace_id": "o1-part4-glucose_pos",
            "response_cleaned": "narrative",
            "messages": [{"role": "system", "content": "s"},
                         {"role": "user", "content": "u"}],
            "elapsed_ms": 1000, "model": "MiniMax-M2.7",
        }) + "\n"
    )
    tmp_o1 = tmp_path / "tmp_o1"; tmp_o1.mkdir()
    (tmp_o1 / "glucose_pos.json").write_text(json.dumps(_stub_report(181.0707)))
    verifier_dir = tmp_path / "verifier"; verifier_dir.mkdir()
    (verifier_dir / "o1-part4-glucose_pos.verifier.json").write_text(json.dumps({
        "trace_id": "o1-part4-glucose_pos_verified",
        "overall_verdict": "verified", "claims_v2": [],
        "llm_call_count": 2, "rewritten_output": "x",
        "source_llm_output": "x", "verification_warnings": [],
    }))

    import ui.data.loaders as L
    monkeypatch.setattr(L, "_LOG_PATH", log)
    monkeypatch.setattr(L, "_DATA_CACHE", tmp_path / "cache_missing")
    monkeypatch.setattr(L, "_TMP_O1", tmp_o1)
    monkeypatch.setattr(L, "_REPO_PIPELINE_RUNS", tmp_path / "runs_missing")
    monkeypatch.setattr(L, "_VERIFIER_RUNS", verifier_dir)

    run = L.load_cached_run("glucose_pos")
    assert run is not None
    assert run.verifier_row is not None
    assert run.verifier_row["overall_verdict"] == "verified"


def test_load_cached_run_verifier_row_none_when_sidecar_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a verifier sidecar, CachedRun.verifier_row is None — does
    not break loading."""
    log = tmp_path / "log.jsonl"
    log.write_text(
        json.dumps({
            "caller": "orchestrator.naive.identify",
            "trace_id": "o1-part4-glucose_pos",
            "response_cleaned": "narrative", "messages": [],
            "elapsed_ms": 0, "model": "MiniMax-M2.7",
        }) + "\n"
    )
    tmp_o1 = tmp_path / "tmp_o1"; tmp_o1.mkdir()
    (tmp_o1 / "glucose_pos.json").write_text(json.dumps(_stub_report(181.0707)))

    import ui.data.loaders as L
    monkeypatch.setattr(L, "_LOG_PATH", log)
    monkeypatch.setattr(L, "_DATA_CACHE", tmp_path / "cache")
    monkeypatch.setattr(L, "_TMP_O1", tmp_o1)
    monkeypatch.setattr(L, "_REPO_PIPELINE_RUNS", tmp_path / "runs")
    monkeypatch.setattr(L, "_VERIFIER_RUNS", tmp_path / "verifier_missing")

    run = L.load_cached_run("glucose_pos")
    assert run is not None
    assert run.verifier_row is None


def test_verifier_sidecar_path_is_predictable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    L = _wire_loader(monkeypatch, tmp_path, verifier_dir=tmp_path / "verifier")
    p = L.verifier_sidecar_path("trace_xyz")
    assert p.name == "trace_xyz.verifier.json"
    assert p.parent == tmp_path / "verifier"
