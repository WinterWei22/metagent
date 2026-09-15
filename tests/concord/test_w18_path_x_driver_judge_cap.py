from __future__ import annotations

import json
import sys


def test_path_x_driver_resets_run_level_judge_cost_tracker(monkeypatch, tmp_path):
    from scripts.concord import w10_d4_path_x_full as driver
    from verifier.helpers.judge_cost_cap import get_run_level_tracker

    benchmark = tmp_path / "tasks.jsonl"
    benchmark.write_text(
        json.dumps({"task_id": "task-1"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        driver,
        "_run_one",
        lambda task, runner, out_full_dir, out_jsonl_fh, progress_lock, counter, n_tasks: (
            counter.__setitem__("done", counter["done"] + 1) or {"task_id": task["task_id"]}
        ),
    )
    monkeypatch.setattr(driver, "aggregate_path_x", lambda rows: {"n_rows": len(rows)})
    monkeypatch.setattr(sys, "argv", [
        "w10_d4_path_x_full.py",
        "--benchmark", str(benchmark),
        "--output", str(tmp_path / "out.jsonl"),
        "--summary", str(tmp_path / "summary.json"),
        "--full-dir", str(tmp_path / "full"),
        "--llm-log", str(tmp_path / "llm.jsonl"),
        "--judge-cost-cap-usd", "0.5",
    ])

    tracker = get_run_level_tracker()
    tracker.cap_usd = 2.0
    tracker.spent_usd = 1.75

    assert driver.main() == 0
    assert tracker.cap_usd == 0.5
    assert tracker.spent_usd == 0.0
