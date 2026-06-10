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


def test_run_level_tracker_is_shared_until_reset():
    mod = _cost_module()
    tracker_a = mod.reset_run_level_tracker(run_id="path-x", cap_usd=0.5)
    tracker_a.record(0.25)

    tracker_b = mod.get_run_level_tracker()
    assert tracker_b is tracker_a
    assert tracker_b.spent_usd == 0.25
    assert tracker_b.can_call(estimated_increment_usd=0.25) is True
    assert tracker_b.can_call(estimated_increment_usd=0.26) is False

    tracker_c = mod.reset_run_level_tracker(run_id="path-x-next", cap_usd=0.5)
    assert tracker_c is tracker_a
    assert tracker_c.run_id == "path-x-next"
    assert tracker_c.spent_usd == 0.0
