"""W8 D5 Path Y — V3 rank-weighted soft union baseline (strict TDD).

Path Y feeds sub6b-v3 tasks through ALL FIVE PA wrappers in driver mode
(no LLM), normalises each wrapper's per-task output to a V3-ready row
dict (with method keys: sspa_ora / ramp / PSEA / mummichog / FELLA),
then applies `concord.analyze.gate2_variants._weighted_top_v3` to get
top-10 consensus pathway names, and matches against the task's
ground-truth pathway.

D5 minimum-viable scope (per "framework health, not paper data"):
- ramp + mummichog normalisers are implemented (their native outputs
  carry pathway_name lists directly).
- sspa / PSEA / FELLA normalisation is BEST-EFFORT for D5: if the
  wrapper raises (env unavailable) or its output shape is opaque, the
  row carries an `error` block for that method and V3 just sees empty
  for that method. This is correctly handled by `_weighted_top_v3`
  (it scores absent methods as 0 contribution).

These tests lock the row-building, the V3 driver call, and the
hit/miss logic. The 63-task run is exercised separately as a CLI
smoke (see run_path_y_batch).
"""
from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def fake_task() -> dict[str, Any]:
    return {
        "task_id": "compound_only_enrich_mammalian_RAMP_P_000000421_seed1",
        "differential_metabolites": [
            {"name": "DHEA", "kegg_id": "C01227"},
        ],
        "ground_truth_pathway": {
            "pathway_id": "RAMP_P_000000421",
            "pathway_name": "Androgen and Estrogen Metabolism",
            "pathway_source": "kegg",
            "external_id": "map00150",
        },
        "ground_truth_signal_compounds": ["C01227"],
        "ground_truth_noise_compounds": [],
    }


def test_path_y_v3_row_construction_method_keys(fake_task, monkeypatch):
    """build_v3_row produces a dict with the 5 method keys V3 expects."""
    from evaluation.concord.path_y import build_v3_row

    # Patch wrappers to return canned dict shapes; build_v3_row should
    # call them all and produce a `_weighted_top_v3`-ready row.
    from concord.wrappers import ramp_wrapper, mummichog_wrapper
    from unittest.mock import MagicMock

    monkeypatch.setattr(ramp_wrapper, "run_ramp_enrichment", lambda *_a, **_kw: {
        "report": MagicMock(top_pathways=[
            MagicMock(pathway_name="Androgen and Estrogen Metabolism",
                       pathway_id="RAMP_P_000000421",
                       pathway_external_id="map00150",
                       pathway_source="kegg"),
        ], n_input_resolved=1),
        "n_input_resolved": 1, "wall_time_sec": 0.1,
    })
    monkeypatch.setattr(mummichog_wrapper, "run_mummichog_for_compound_set",
                        lambda *_a, **_kw: {
                            "pathways": [{"pathway_name": "Steroid biosynthesis", "pathway_id": "Steroid biosynthesis"}],
                            "wall_time_sec": 0.5,
                        })

    row = build_v3_row(fake_task)
    assert "task_id" in row
    assert "ground_truth_pathway_name" in row
    for method_key in ("sspa_ora", "ramp", "PSEA", "mummichog", "FELLA"):
        assert method_key in row, f"missing method key {method_key}"
        block = row[method_key]
        # Every block must be a dict (V3 algorithm tolerates `error` /
        # `pathways=[]` blocks for unavailable methods)
        assert isinstance(block, dict)


def test_path_y_v3_top_pathway_names_match_ground_truth(fake_task, monkeypatch):
    """When a method ranks the ground-truth pathway, V3 picks it up."""
    from evaluation.concord.path_y import run_path_y_for_task

    from concord.wrappers import ramp_wrapper, mummichog_wrapper
    from unittest.mock import MagicMock

    monkeypatch.setattr(ramp_wrapper, "run_ramp_enrichment", lambda *_a, **_kw: {
        "report": MagicMock(top_pathways=[
            MagicMock(pathway_name="Androgen and Estrogen Metabolism",
                       pathway_id="RAMP_P_000000421",
                       pathway_external_id="map00150",
                       pathway_source="kegg"),
        ], n_input_resolved=1),
        "n_input_resolved": 1, "wall_time_sec": 0.1,
    })
    monkeypatch.setattr(mummichog_wrapper, "run_mummichog_for_compound_set",
                        lambda *_a, **_kw: {"pathways": []})

    rec = run_path_y_for_task(fake_task)
    assert rec["task_id"] == fake_task["task_id"]
    assert rec["fuzzy_hit"] is True
    assert rec["strict_hit"] is True  # ramp pathway external_id == gt external_id
    assert "Androgen and Estrogen Metabolism" in rec["v3_top_pathways"]


def test_path_y_handles_wrapper_unavailable_with_per_method_error(fake_task, monkeypatch):
    """Wrapper raising ImportError lands as `{"error": "..."}` in its
    row block; V3 algorithm sees empty pathways for that method but
    other methods' results still contribute."""
    from evaluation.concord.path_y import run_path_y_for_task

    from concord.wrappers import ramp_wrapper, mummichog_wrapper

    def _ramp_ok(*_a, **_kw):
        from unittest.mock import MagicMock
        return {
            "report": MagicMock(top_pathways=[
                MagicMock(pathway_name="Androgen and Estrogen Metabolism",
                          pathway_id="RAMP_P_000000421",
                          pathway_external_id="map00150",
                          pathway_source="kegg"),
            ], n_input_resolved=1),
            "n_input_resolved": 1, "wall_time_sec": 0.1,
        }

    def _mummichog_unavailable(*_a, **_kw):
        raise FileNotFoundError("mummichog venv missing in test env")

    monkeypatch.setattr(ramp_wrapper, "run_ramp_enrichment", _ramp_ok)
    monkeypatch.setattr(mummichog_wrapper, "run_mummichog_for_compound_set",
                        _mummichog_unavailable)
    rec = run_path_y_for_task(fake_task)

    # Per-method error blocks recorded
    assert rec["per_method_status"]["mummichog"].startswith("error")
    assert rec["per_method_status"]["ramp"] == "ok"
    # ramp ground-truth hit still surfaces
    assert rec["fuzzy_hit"] is True


def test_path_y_aggregate_precision_at_10(tmp_path):
    """Aggregator computes precision@10 strict + fuzzy."""
    from evaluation.concord.path_y import aggregate_path_y
    per_task = [
        {"strict_hit": True, "fuzzy_hit": True, "error": None},
        {"strict_hit": False, "fuzzy_hit": True, "error": None},
        {"strict_hit": False, "fuzzy_hit": False, "error": None},
    ]
    agg = aggregate_path_y(per_task)
    assert agg["n_tasks"] == 3
    assert agg["precision_at_10_strict"] == pytest.approx(1 / 3)
    assert agg["precision_at_10_fuzzy"] == pytest.approx(2 / 3)
