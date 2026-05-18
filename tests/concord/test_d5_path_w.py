"""W8 D5 Path W — recompute v3 Opus baseline aggregate (strict TDD).

Tests for `evaluation.concord.path_w.aggregate_v3_opus_metrics()` which
reads `data/eval/sub6/v3/sub6b_opus/verdicts_v9_phaseC.jsonl` (or a
caller-supplied path) and re-derives the 4 verdict ratios + counts.

The aggregator is a thin pure function: no LLM, no IO besides reading
the JSONL. Tests use small synthetic inputs to lock the math and edge
cases.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


@pytest.fixture
def v3_opus_minimal(tmp_path: Path) -> Path:
    """Three tasks with known counts: 6 supported + 4 unsupported + 1
    contradicted + 9 unverifiable_v0 = 20 total claims."""
    f = tmp_path / "v3_opus.jsonl"
    _write_jsonl(f, [
        {"task_id": "t1", "error": None,
         "verdicts_total": {"supported": 3, "unsupported": 1, "contradicted": 0, "unverifiable_v0": 5}},
        {"task_id": "t2", "error": None,
         "verdicts_total": {"supported": 2, "unsupported": 2, "contradicted": 1, "unverifiable_v0": 3}},
        {"task_id": "t3", "error": None,
         "verdicts_total": {"supported": 1, "unsupported": 1, "contradicted": 0, "unverifiable_v0": 1}},
    ])
    return f


def test_aggregate_v3_opus_total_counts(v3_opus_minimal: Path):
    """4 verdict counts sum across rows correctly."""
    from evaluation.concord.path_w import aggregate_v3_opus_metrics

    out = aggregate_v3_opus_metrics(v3_opus_minimal)
    assert out["n_task_records"] == 3
    assert out["n_error_rows"] == 0
    assert out["counts"]["supported"] == 6
    assert out["counts"]["unsupported"] == 4
    assert out["counts"]["contradicted"] == 1
    assert out["counts"]["unverifiable_v0"] == 9
    assert out["counts"]["total_claims"] == 20


def test_aggregate_v3_opus_percentages_to_total_claims(v3_opus_minimal: Path):
    """Verdict % is over total_claims (not over n_task_records)."""
    from evaluation.concord.path_w import aggregate_v3_opus_metrics

    out = aggregate_v3_opus_metrics(v3_opus_minimal)
    assert out["pct"]["supported"] == pytest.approx(30.0, abs=0.01)  # 6/20
    assert out["pct"]["unsupported"] == pytest.approx(20.0, abs=0.01)  # 4/20
    assert out["pct"]["contradicted"] == pytest.approx(5.0, abs=0.01)  # 1/20
    assert out["pct"]["unverifiable_v0"] == pytest.approx(45.0, abs=0.01)  # 9/20


def test_aggregate_v3_opus_skips_error_rows(tmp_path: Path):
    """Rows with non-None `error` are counted as `n_error_rows` and
    excluded from the aggregate (matches v3 report §1 behavior — the
    single APIConnectionError row contributes nothing to ratios)."""
    f = tmp_path / "v3_with_err.jsonl"
    _write_jsonl(f, [
        {"task_id": "ok", "error": None,
         "verdicts_total": {"supported": 1, "unsupported": 0, "contradicted": 0, "unverifiable_v0": 0}},
        {"task_id": "err", "error": "APIConnectionError",
         "verdicts_total": {}},
    ])
    from evaluation.concord.path_w import aggregate_v3_opus_metrics

    out = aggregate_v3_opus_metrics(f)
    assert out["n_task_records"] == 2
    assert out["n_error_rows"] == 1
    assert out["counts"]["total_claims"] == 1
    assert out["counts"]["supported"] == 1


def test_aggregate_v3_opus_missing_file_raises(tmp_path: Path):
    from evaluation.concord.path_w import aggregate_v3_opus_metrics
    with pytest.raises(FileNotFoundError):
        aggregate_v3_opus_metrics(tmp_path / "does_not_exist.jsonl")
