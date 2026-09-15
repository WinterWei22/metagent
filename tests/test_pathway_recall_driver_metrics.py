from __future__ import annotations

import pytest

from concord.agent.pathway_prediction import pathway_recall_metrics, driver_pr_metrics


def test_recall_hit_mrr_basic():
    pred = ["Tyrosine metabolism", "Glutathione metabolism", "Aspirin"]
    rel = {"tyrosine metabolism", "catecholamine biosynthesis"}
    m = pathway_recall_metrics(pred, rel, k=3)
    assert m["hit_at_k"] is True
    assert m["recall_at_k"] == pytest.approx(0.5)   # 1 of 2 relevant retrieved
    assert m["mrr"] == pytest.approx(1.0)            # relevant at rank 1
    assert m["n_relevant"] == 2


def test_recall_rank2_mrr_half_and_k_truncates():
    pred = ["Wrong", "Right pathway", "Right pathway too"]
    rel = {"right pathway", "right pathway too"}
    assert pathway_recall_metrics(pred, rel, k=1)["hit_at_k"] is False
    m2 = pathway_recall_metrics(pred, rel, k=3)
    assert m2["mrr"] == pytest.approx(0.5)
    assert m2["recall_at_k"] == pytest.approx(1.0)


def test_recall_empty_relevant_is_zero():
    m = pathway_recall_metrics(["X"], set(), k=3)
    assert m["hit_at_k"] is False
    assert m["recall_at_k"] == 0.0
    assert m["mrr"] == 0.0


def test_driver_pr_none_when_gold_na():
    assert driver_pr_metrics({"RAMP_C_1"}, None) is None


def test_driver_pr_basic():
    m = driver_pr_metrics({"RAMP_C_1", "RAMP_C_9"}, {"RAMP_C_1", "RAMP_C_2"})
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["n_hit"] == 1


def test_driver_pr_empty_predicted():
    m = driver_pr_metrics(set(), {"RAMP_C_1"})
    assert m["precision"] == 0.0
    assert m["recall"] == 0.0
