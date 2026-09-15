"""W8 D5 Path Z — RaMP-only baseline (strict TDD).

Path Z is the simplest quad-report baseline: feed sub6b-v3 tasks through
`concord.wrappers.ramp_wrapper.run_ramp_enrichment` (no LLM, no other
PA tools, no consensus), then check whether the task's ground-truth
pathway appears in the RaMP top-10.

The runner output shape::

    {"task_id": ..., "ramp_top_pathways": [{...}, ...], "gt_pathway_name": ...,
     "gt_external_id": ..., "strict_hit": bool, "fuzzy_hit": bool,
     "fuzzy_rank": int | None, "n_input": int, "n_input_resolved": int,
     "wall_seconds": float, "error": str | None}

Tests use a mocked ramp wrapper to lock the precision@10 math without
spinning up the real sqlite (which the D5 run will exercise end-to-end).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


class _FakeEnrichmentResult:
    def __init__(self, pathway_id: str, pathway_name: str,
                  pathway_external_id: str | None = None,
                  pathway_source: str = "wikipathways",
                  p_value: float = 0.001, fdr: float = 0.01):
        self.pathway_id = pathway_id
        self.pathway_name = pathway_name
        self.pathway_external_id = pathway_external_id
        self.pathway_source = pathway_source
        self.p_value = p_value
        self.fdr = fdr
        self.fold_enrichment = 1.0
        self.matched_compounds = []
        self.total_pathway_compounds = 10


def _fake_ramp_report(pathways: list[_FakeEnrichmentResult]) -> Any:
    return {
        "report": MagicMock(
            top_pathways=pathways,
            input_compounds=["C00219"],
            resolved_compounds=["C00219"],
            unresolved_compounds=[],
            n_input_resolved=1,
            ramp_snapshot_date="2026-05",
        ),
        "wall_time_sec": 0.1,
        "n_input": 1,
        "n_input_resolved": 1,
    }


@pytest.fixture
def fake_task() -> dict[str, Any]:
    return {
        "task_id": "compound_only_enrich_mammalian_lm_pathway_WP167_seed3",
        "differential_metabolites": [
            {"name": "arachidonic acid", "kegg_id": "C00219"},
        ],
        "ground_truth_pathway": {
            "pathway_id": "lm_pathway:WP167",
            "pathway_name": "Eicosanoid synthesis",
            "pathway_source": "lipidmaps",
            "external_id": "WP167",
        },
        "ground_truth_signal_compounds": ["C00219"],
        "ground_truth_noise_compounds": [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_path_z_strict_hit_external_id_match(monkeypatch, fake_task):
    """RaMP returns a pathway whose external_id == task gt external_id →
    strict_hit=True."""
    from concord.wrappers import ramp_wrapper
    monkeypatch.setattr(
        ramp_wrapper, "run_ramp_enrichment",
        lambda *_a, **_kw: _fake_ramp_report([
            _FakeEnrichmentResult(
                pathway_id="RAMP_P_999999",
                pathway_name="Eicosanoid synthesis",
                pathway_external_id="WP167",
                pathway_source="wikipathways",
            ),
        ]),
    )
    from evaluation.concord.path_z import run_path_z_for_task

    rec = run_path_z_for_task(fake_task)
    assert rec["task_id"] == fake_task["task_id"]
    assert rec["strict_hit"] is True
    assert rec["fuzzy_hit"] is True  # name match too
    assert rec["fuzzy_rank"] == 0
    assert rec["error"] is None


def test_path_z_fuzzy_hit_token_jaccard(monkeypatch, fake_task):
    """RaMP returns a pathway with similar name but different external_id
    → fuzzy_hit=True via token-Jaccard ≥ 0.5, strict_hit=False."""
    from concord.wrappers import ramp_wrapper
    monkeypatch.setattr(
        ramp_wrapper, "run_ramp_enrichment",
        lambda *_a, **_kw: _fake_ramp_report([
            _FakeEnrichmentResult(
                pathway_id="RAMP_P_999998",
                pathway_name="Eicosanoid synthesis",  # exact name match
                pathway_external_id="R-HSA-2142753",  # but reactome id
                pathway_source="reactome",
            ),
        ]),
    )
    from evaluation.concord.path_z import run_path_z_for_task

    rec = run_path_z_for_task(fake_task)
    assert rec["strict_hit"] is False
    assert rec["fuzzy_hit"] is True


def test_path_z_no_hit_unrelated_pathway(monkeypatch, fake_task):
    """RaMP returns an unrelated pathway → both strict and fuzzy False."""
    from concord.wrappers import ramp_wrapper
    monkeypatch.setattr(
        ramp_wrapper, "run_ramp_enrichment",
        lambda *_a, **_kw: _fake_ramp_report([
            _FakeEnrichmentResult(
                pathway_id="RAMP_P_111111",
                pathway_name="Glycolysis / Gluconeogenesis",
                pathway_external_id="hsa00010",
                pathway_source="kegg",
            ),
        ]),
    )
    from evaluation.concord.path_z import run_path_z_for_task

    rec = run_path_z_for_task(fake_task)
    assert rec["strict_hit"] is False
    assert rec["fuzzy_hit"] is False
    assert rec["fuzzy_rank"] is None


def test_path_z_wrapper_unavailable_returns_error_record(monkeypatch, fake_task):
    """If RaMP wrapper raises ImportError / FileNotFoundError, the task
    record carries an error string but does NOT raise — the batch
    driver must keep going on remaining tasks."""
    from concord.wrappers import ramp_wrapper

    def _boom(*_a, **_kw):
        raise ImportError("ramp wrapper unavailable")
    monkeypatch.setattr(ramp_wrapper, "run_ramp_enrichment", _boom)
    from evaluation.concord.path_z import run_path_z_for_task

    rec = run_path_z_for_task(fake_task)
    assert rec["error"] is not None
    assert "ramp" in rec["error"].lower()
    assert rec["strict_hit"] is False
    assert rec["fuzzy_hit"] is False


def test_path_z_aggregator_computes_precision_at_10(tmp_path, fake_task):
    """Given a list of per-task records, the aggregator computes
    precision@10 (strict / fuzzy) as the fraction of tasks with a hit."""
    from evaluation.concord.path_z import aggregate_path_z

    per_task = [
        {"task_id": "t1", "strict_hit": True, "fuzzy_hit": True, "error": None,
         "fuzzy_rank": 0},
        {"task_id": "t2", "strict_hit": False, "fuzzy_hit": True, "error": None,
         "fuzzy_rank": 3},
        {"task_id": "t3", "strict_hit": False, "fuzzy_hit": False, "error": None,
         "fuzzy_rank": None},
        {"task_id": "t4", "strict_hit": False, "fuzzy_hit": False,
         "error": "ramp unavailable", "fuzzy_rank": None},
    ]
    agg = aggregate_path_z(per_task)
    # 4 tasks; 1 strict hit / 2 fuzzy hits / 1 error
    assert agg["n_tasks"] == 4
    assert agg["n_error_tasks"] == 1
    assert agg["precision_at_10_strict"] == pytest.approx(1 / 4)
    assert agg["precision_at_10_fuzzy"] == pytest.approx(2 / 4)
