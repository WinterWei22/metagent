"""Smoke tests for ui.data.runners — no subprocess, no real LLM."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_GOOD_PAYLOAD = {
    "precursor_mz": 181.0707,
    "adduct": "[M+H]+",
    "ionization_mode": "positive",
    "peaks": [[163.06, 1000.0], [145.05, 420.0]],
}


def test_parse_accepts_minimal_valid_payload() -> None:
    from ui.data.runners import parse_custom_spectrum_json

    data = parse_custom_spectrum_json(json.dumps(_GOOD_PAYLOAD))
    assert data["precursor_mz"] == 181.0707
    assert len(data["peaks"]) == 2


def test_parse_rejects_non_json() -> None:
    from ui.data.runners import LiveRunError, parse_custom_spectrum_json

    with pytest.raises(LiveRunError, match="Not valid JSON"):
        parse_custom_spectrum_json("not json at all")


def test_parse_rejects_top_level_list() -> None:
    from ui.data.runners import LiveRunError, parse_custom_spectrum_json

    with pytest.raises(LiveRunError, match="must be an object"):
        parse_custom_spectrum_json("[1, 2, 3]")


def test_parse_rejects_missing_field() -> None:
    from ui.data.runners import LiveRunError, parse_custom_spectrum_json

    payload = dict(_GOOD_PAYLOAD)
    del payload["adduct"]
    with pytest.raises(LiveRunError, match="Missing required field"):
        parse_custom_spectrum_json(json.dumps(payload))


def test_parse_rejects_empty_peaks() -> None:
    from ui.data.runners import LiveRunError, parse_custom_spectrum_json

    payload = dict(_GOOD_PAYLOAD, peaks=[])
    with pytest.raises(LiveRunError, match="non-empty list"):
        parse_custom_spectrum_json(json.dumps(payload))


def test_parse_rejects_malformed_peak() -> None:
    from ui.data.runners import LiveRunError, parse_custom_spectrum_json

    payload = dict(_GOOD_PAYLOAD, peaks=[[1.0]])
    with pytest.raises(LiveRunError, match="two-element list"):
        parse_custom_spectrum_json(json.dumps(payload))


def test_parse_rejects_invalid_ionization_mode() -> None:
    from ui.data.runners import LiveRunError, parse_custom_spectrum_json

    payload = dict(_GOOD_PAYLOAD, ionization_mode="other")
    with pytest.raises(LiveRunError, match="ionization_mode"):
        parse_custom_spectrum_json(json.dumps(payload))


def test_make_live_trace_id_shape() -> None:
    from ui.data.runners import make_live_trace_id

    trace_id = make_live_trace_id(_GOOD_PAYLOAD)
    assert trace_id.startswith("live_")
    # live_<8hex>_<14digits>
    _, short, ts = trace_id.split("_")
    assert len(short) == 8 and all(c in "0123456789abcdef" for c in short)
    assert len(ts) == 14 and ts.isdigit()


def test_make_live_trace_id_deterministic_hash_component() -> None:
    from ui.data.runners import make_live_trace_id

    a = make_live_trace_id(_GOOD_PAYLOAD)
    b = make_live_trace_id(_GOOD_PAYLOAD)
    # Timestamp suffix can differ if a second ticks between calls; hash part must match.
    assert a.split("_")[1] == b.split("_")[1]


# ---------------------------------------------------------------------------
# run_live_verifier (UI/V1) — mocked, no MiniMax network
# ---------------------------------------------------------------------------


_VALID_REPORT = {
    "experimental_spectrum": {
        "mz": [100.0, 150.0], "intensity": [0.5, 1.0],
        "precursor_mz": 181.07, "adduct": "[M+H]+",
        "ionization_mode": "positive", "collision_energy": 20.0,
    },
    "preprocess_quality_flag": "good",
    "neutral_mass_computed": 180.06,
    "n_prefilter_candidates": 0, "n_library_candidates": 0,
    "n_generated_candidates": 0,
    "candidates": [], "pipeline_version": "test:1",
    "tool_versions": {}, "warnings": [],
}


def test_run_live_verifier_skips_when_llm_output_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import ui.data.runners as R
    dump, err = R.run_live_verifier(_VALID_REPORT, "", trace_id="t-empty")
    assert dump is None
    assert err and "no LLM output" in err


def test_run_live_verifier_invalid_report_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import ui.data.runners as R
    dump, err = R.run_live_verifier(
        {"not_a_real": "report"}, "narrative", trace_id="t-bad",
    )
    assert dump is None
    assert err and "source_report invalid" in err


def test_run_live_verifier_persists_sidecar_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import ui.data.runners as R
    import ui.data.loaders as L

    monkeypatch.setattr(L, "_VERIFIER_RUNS", tmp_path / "verifier")

    from datetime import datetime, timezone

    class StubVI:
        def model_dump(self, mode=None):
            return {
                "trace_id": "t-good_verified",
                "source_llm_output": "src",
                "rewritten_output": "src",
                "claims_v1": [], "claims_v2": [],
                "overall_verdict": "verified",
                "verification_warnings": [],
                "llm_call_count": 2,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

    def fake_verify(llm_output, source_report, *, trace_id):
        assert trace_id.endswith("_verified")
        return StubVI()

    import verifier.agent as VA
    monkeypatch.setattr(VA, "verify", fake_verify)

    dump, err = R.run_live_verifier(_VALID_REPORT, "narrative", trace_id="t-good")
    assert err is None
    assert dump is not None
    assert dump["overall_verdict"] == "verified"

    sidecar = (tmp_path / "verifier" / "t-good.verifier.json")
    assert sidecar.is_file()
    persisted = json.loads(sidecar.read_text())
    assert persisted["overall_verdict"] == "verified"


def test_run_live_verifier_propagates_verifier_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import ui.data.runners as R

    def boom(*a, **kw):
        raise RuntimeError("MiniMax timeout")

    import verifier.agent as VA
    monkeypatch.setattr(VA, "verify", boom)

    dump, err = R.run_live_verifier(_VALID_REPORT, "narrative", trace_id="t-crash")
    assert dump is None
    assert err and "verifier crashed" in err
    assert "RuntimeError" in err
