from __future__ import annotations

import importlib


def _cost_module():
    return importlib.import_module("verifier.helpers.judge_cost_cap")


def test_cost_tracker_allows_call_below_cap():
    mod = _cost_module()
    tracker = mod.JudgeCostTracker(cap_usd=2.0, spent_usd=1.5)
    assert tracker.can_call(estimated_increment_usd=0.2) is True


def test_cost_tracker_rejects_call_at_or_above_cap():
    mod = _cost_module()
    tracker = mod.JudgeCostTracker(cap_usd=2.0, spent_usd=2.0)
    assert tracker.can_call(estimated_increment_usd=0.01) is False


def test_cost_tracker_reset_is_per_path_x_run():
    mod = _cost_module()
    tracker = mod.JudgeCostTracker(cap_usd=2.0, spent_usd=1.9)
    tracker.reset_for_run(run_id="task-2")
    assert tracker.spent_usd == 0.0
    assert tracker.run_id == "task-2"
