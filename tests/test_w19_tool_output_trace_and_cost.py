from __future__ import annotations

import importlib
import json


def _trace():
    return importlib.import_module("verifier.helpers.tool_output_trace")


def test_write_tool_output_trace_jsonl_contains_required_fields(tmp_path):
    path = tmp_path / "tool_output_trace.jsonl"
    _trace().write_tool_output_trace(
        path=path,
        task_id="task-1",
        iteration=1,
        claim_id="claim-1",
        claim_type="grounded_claim",
        method="mummichog",
        status="match",
        verdict="SUPPORTED",
        source_field="mummichog_enrichment_result.pathways[0].score",
    )
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows == [
        {
            "task_id": "task-1",
            "iteration": 1,
            "claim_id": "claim-1",
            "claim_type": "grounded_claim",
            "method": "mummichog",
            "status": "match",
            "verdict": "SUPPORTED",
            "source_field": "mummichog_enrichment_result.pathways[0].score",
            "cost_usd": 0.0,
        }
    ]


def test_request_tracker_caps_fanout_and_resets_per_run():
    tracker = _trace().ToolOutputRequestTracker(max_requests_per_run=2)
    assert tracker.can_call()
    tracker.record()
    tracker.record()
    assert not tracker.can_call()
    tracker.reset_for_run("run-2")
    assert tracker.can_call()
    assert tracker.run_id == "run-2"
