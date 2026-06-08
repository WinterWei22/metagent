from __future__ import annotations

import json

from scripts.metagent.w17_d4_path_x_metrics import (
    compute_metrics,
    compute_minimax_cost,
    serialization_round_trip,
)


def test_compute_metrics_uses_final_iteration_counts():
    rows = [
        {
            "framework_signal_bridge_in_iters": True,
            "final_iter_idx": 1,
            "per_iter": [
                {"n_supported": 1, "n_unsupported": 9, "n_contradicted": 0, "n_unverifiable_v0": 9},
                {"n_supported": 3, "n_unsupported": 2, "n_contradicted": 1, "n_unverifiable_v0": 4},
            ],
        },
        {
            "framework_signal_bridge_in_iters": False,
            "final_iter_idx": 0,
            "per_iter": [
                {"n_supported": 1, "n_unsupported": 1, "n_contradicted": 0, "n_unverifiable_v0": 0},
            ],
        },
    ]

    metrics = compute_metrics(rows, {"n_feedback_iter2": 0, "rollback_iter2_degraded": 0})

    assert metrics["uv_count"] == 4
    assert metrics["claim_denominator"] == 12
    assert metrics["uv_rate_pct"] == 33.33
    assert metrics["pathway_bridge_count"] == 1
    assert metrics["pathway_accuracy_pct"] == 50.0
    assert metrics["iter2_trigger_count"] == 0
    assert metrics["iter2_degraded_count"] == 0


def test_compute_minimax_cost_uses_prompt_and_completion_rates():
    assert compute_minimax_cost(prompt_tokens=1_000_000, completion_tokens=2_000_000) == 2.7


def test_serialization_round_trip_reports_carrier_keys(tmp_path):
    payload = {
        "final_react_result": {
            "enrichment_carriers": {
                "mummichog_enrichment_result": {"pathways": []},
                "metaboanalystr_enrichment_result": {"psea": {"pathways": []}},
            }
        }
    }
    path = tmp_path / "task.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    check = serialization_round_trip(path)

    assert check["present"] is True
    assert check["round_trip_ok"] is True
    assert check["carrier_keys"] == [
        "metaboanalystr_enrichment_result",
        "mummichog_enrichment_result",
    ]
