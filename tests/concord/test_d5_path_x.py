"""W8 D5 Path X — LLM-agent driver tests (the algorithmic pieces only).

Two pure functions are unit-tested here:
  (A) `_per_task_signals` — reduces a ConcordFeedbackResult to flat
      framework signals (best-iter / rollback / bridging / tool counts).
  (B) `aggregate_path_x` — rolls those per-task dicts up to summary.

The full batch driver (LLM + verifier IO) is exercised by the
`evaluation.concord.path_x` __main__ entry point against real wrappers;
it's smoke-tested in the D5 5-task stratified run, not unit-tested here.

Acknowledged TDD scoping: the driver body was written before these
tests (same scoping decision as D3 run_task body). Algorithmic
helpers test-driven below.
"""
from __future__ import annotations

from typing import Any

import pytest

from concord.agent.react_runner import (
    ConcordIterationRecord,
    ConcordReactResult,
    FeedbackIterationRecord,
    ConcordFeedbackResult,
    VerificationOutcome,
)


def _make_react_result(narrative: str, claims: list[dict], task_id="x") -> ConcordReactResult:
    return ConcordReactResult(
        task_id=task_id,
        iterations=[ConcordIterationRecord(
            iter_idx=0, narrative_json="{}",
            n_turns=8, n_tool_calls=20, force_finalised=True,
            inner_retry_used=False,
        )],
        final_narrative_text=narrative,
        final_claims=claims,
        task_outcome="normal",
        elapsed_seconds=200.0,
        n_distinct_tools_called=5,
        tools_called=["lookup_chebi", "run_ramp_enrichment", "run_mummichog",
                      "run_fella_rwr", "run_metaboanalystr_psea"],
    )


def _make_iter_rec(iter_idx: int, *, narrative: str, claims: list[dict],
                    n_supported=0, n_unsupported=0,
                    n_contradicted=0, n_unverifiable_v0=0):
    return FeedbackIterationRecord(
        iter_idx=iter_idx,
        react_result=_make_react_result(narrative, claims),
        verification=VerificationOutcome(
            ok=True, verdict=None, error=None,
            n_supported=n_supported, n_unsupported=n_unsupported,
            n_contradicted=n_contradicted,
            n_unverifiable_v0=n_unverifiable_v0,
        ),
    )


# ---------------------------------------------------------------------------
# _per_task_signals
# ---------------------------------------------------------------------------


def test_per_task_signals_three_iter_with_bridge_at_iter2():
    """Mirror D4 smoke 2 lipid: iter 0/1 no bridge (MUMM ns) + iter 2 bridges
    to WP:WP167 but quality rollback selects iter 0."""
    from evaluation.concord.path_x import _per_task_signals

    task = {
        "task_id": "lipid_t",
        "ground_truth_pathway": {
            "pathway_id": "lm_pathway:WP167",
            "pathway_name": "Eicosanoid synthesis",
            "external_id": "WP167",
        },
    }
    iters = [
        _make_iter_rec(0,
            narrative="Arachidonic acid metabolism dominates.",
            claims=[{"claim_type": "PATHWAY_ENRICHMENT", "pathway_id": "MUMM:00002"}],
            n_supported=4, n_unsupported=2),
        _make_iter_rec(1,
            narrative="Arachidonic acid metabolism (rev).",
            claims=[{"claim_type": "PATHWAY_ENRICHMENT", "pathway_id": "MUMM:00002"}],
            n_supported=1, n_unsupported=14),
        _make_iter_rec(2,
            narrative="The eicosanoid synthesis pathway dominates.",
            claims=[{"claim_type": "PATHWAY_ENRICHMENT", "pathway_id": "WP:WP167",
                      "pathway_name": "Eicosanoid synthesis"}],
            n_supported=4, n_unsupported=10),
    ]
    fb = ConcordFeedbackResult(
        task_id="lipid_t",
        iterations=iters,
        final_iter_idx=0,  # rollback selected iter 0
        n_feedback_iterations=2,
        rollback_reason="feedback_made_it_worse",
        final_react_result=iters[0].react_result,
        final_verdict=iters[0].verification,
    )
    sig = _per_task_signals(task, fb)
    assert sig["final_iter_idx"] == 0
    assert sig["rollback_reason"] == "feedback_made_it_worse"
    assert sig["best_iter_idx"] == 0  # quality 2 is min among 2,15,14
    assert sig["framework_signal_best_ne_final"] is False
    assert sig["best_bridge_iter_idx"] == 2
    assert sig["framework_signal_bridge_in_iters"] is True
    assert sig["framework_signal_bridge_lost_to_rollback"] is True
    # per_iter trace
    assert len(sig["per_iter"]) == 3
    assert sig["per_iter"][2]["any_claim_matches_gt_pathway_id"] is True


def test_per_task_signals_no_bridge_no_rollback():
    """Task where all iters write the same claims, no bridging, no rollback."""
    from evaluation.concord.path_x import _per_task_signals

    task = {
        "task_id": "steroid_t",
        "ground_truth_pathway": {
            "pathway_id": "RAMP_P_000000421",
            "pathway_name": "Androgen and Estrogen Metabolism",
            "external_id": "map00150",
        },
    }
    iters = [
        _make_iter_rec(0, narrative="steroid biosynthesis", claims=[],
                        n_supported=0, n_unsupported=11),
    ]
    fb = ConcordFeedbackResult(
        task_id="steroid_t",
        iterations=iters,
        final_iter_idx=0,
        n_feedback_iterations=0,
        rollback_reason=None,
        final_react_result=iters[0].react_result,
        final_verdict=iters[0].verification,
    )
    sig = _per_task_signals(task, fb)
    assert sig["best_iter_idx"] == 0
    assert sig["framework_signal_best_ne_final"] is False
    assert sig["best_bridge_iter_idx"] is None
    assert sig["framework_signal_bridge_in_iters"] is False


# ---------------------------------------------------------------------------
# aggregate_path_x
# ---------------------------------------------------------------------------


def test_aggregate_path_x_counts_rollback_and_bridge_signals():
    """Mix per-task signals → summary correctly tabulates rollback,
    bridge-lost-to-rollback, and tool-call distribution."""
    from evaluation.concord.path_x import aggregate_path_x

    per_task = [
        # 1: clean bridge held to final
        {"final_iter_idx": 2, "rollback_reason": None,
         "best_iter_idx": 2, "best_bridge_iter_idx": 2,
         "framework_signal_best_ne_final": False,
         "framework_signal_bridge_in_iters": True,
         "framework_signal_bridge_lost_to_rollback": False,
         "n_feedback_iterations": 2,
         "iter_calls_max": 20, "iter_walls_total": 300.0,
         "per_iter": [{"task_outcome": "normal", "quality": 5},
                       {"task_outcome": "normal", "quality": 3},
                       {"task_outcome": "normal", "quality": 2}]},
        # 2: bridge in iter 2 but rolled back
        {"final_iter_idx": 0, "rollback_reason": "feedback_made_it_worse",
         "best_iter_idx": 0, "best_bridge_iter_idx": 2,
         "framework_signal_best_ne_final": False,
         "framework_signal_bridge_in_iters": True,
         "framework_signal_bridge_lost_to_rollback": True,
         "n_feedback_iterations": 2,
         "iter_calls_max": 26, "iter_walls_total": 600.0,
         "per_iter": [{"task_outcome": "normal", "quality": 2},
                       {"task_outcome": "normal", "quality": 14},
                       {"task_outcome": "normal", "quality": 10}]},
        # 3: early exit, no feedback iter
        {"final_iter_idx": 0, "rollback_reason": None,
         "best_iter_idx": 0, "best_bridge_iter_idx": None,
         "framework_signal_best_ne_final": False,
         "framework_signal_bridge_in_iters": False,
         "framework_signal_bridge_lost_to_rollback": False,
         "n_feedback_iterations": 0,
         "iter_calls_max": 15, "iter_walls_total": 200.0,
         "per_iter": [{"task_outcome": "normal", "quality": 0}]},
        # 4: crash
        {"task_id": "crashy", "framework_signal_crash": "ValueError: x",
         "wall_seconds": 5.0},
    ]
    agg = aggregate_path_x(per_task)
    assert agg["n_tasks"] == 4
    assert agg["n_crash"] == 1
    assert agg["n_valid"] == 3
    assert agg["rollback_total"] == 1
    assert agg["rollback_feedback_made_it_worse"] == 1
    assert agg["framework_signal_bridge_in_iters"] == 2
    assert agg["framework_signal_bridge_lost_to_rollback"] == 1
    assert agg["framework_signal_best_ne_final"] == 0
    assert agg["n_feedback_iter1"] == 2
    assert agg["n_feedback_iter2"] == 2
    assert agg["early_exit_iter0"] == 1
    assert agg["tool_call_max_distribution"]["max"] == 26
    assert agg["tool_call_max_distribution"]["n_over_25"] == 1


def test_aggregate_path_x_empty_input():
    from evaluation.concord.path_x import aggregate_path_x
    agg = aggregate_path_x([])
    assert agg["n_tasks"] == 0
    assert agg["n_valid"] == 0
    assert agg["mean_wall_seconds_per_task"] == 0
