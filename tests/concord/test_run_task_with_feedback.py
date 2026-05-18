"""W8 D4 sub-task 3 — `ConcordReactRunner.run_task_with_feedback` strict-TDD.

The feedback loop wires:

  1. iter 0: `run_task(task)` produces narrative_N0 → verify_with_b1 →
     verdict_N0 → quality_N0 = n_contradicted + n_unsupported.
  2. If quality_N0 == 0 OR max_feedback_iters == 0 → return early
     with `final_iter_idx=0`, no rollback.
  3. Otherwise build a feedback hint from verdict_N0's
     {contradicted, unsupported} claims, prepend it to the next
     `run_task(task, feedback_user_msg=hint)` → narrative_N1 → verify
     → verdict_N1.
  4. Quality rollback rule (B1 D4 Q6, lower-is-better):
       q(N1) ≥ q(N0) → rollback to N0; rollback_reason="feedback_made_it_worse"
       else (improvement) → continue with N1
  5. iter 2 follows the same pattern. Final comparison vs N0:
       q(N2) > q(N0) → rollback to N0 (feedback_made_it_worse)
       q(N2) > q(N1) → rollback to N1 (iter2_degraded)
       else → keep N2

All four ConcordReactResult / VerificationOutcome objects are
preserved on the returned ConcordFeedbackResult so D4 status / D5
audit can inspect the full trajectory.

Tests inject both `chat_with_tools` (FakeChat) and `verifier_fn` (mock)
to drive deterministic verdict trajectories.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from concord.agent.react_runner import (
    ConcordIterationRecord,
    ConcordReactResult,
    ConcordReactRunner,
)


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_task() -> dict[str, Any]:
    return {
        "task_id": "test_feedback_task",
        "task_type": "compound_only_enrichment",
        "domain": "mammalian",
        "differential_metabolites": [
            {"name": "arachidonic acid", "kegg_id": "C00219"},
        ],
        "differential_spectra": None,
        "ground_truth_pathway": {
            "pathway_id": "lm_pathway:WP167",
            "pathway_name": "Eicosanoid synthesis",
            "pathway_source": "lipidmaps",
            "external_id": "WP167",
            "primary_pathway_pre_aggregation": "lm_pathway:WP167",
        },
        "ground_truth_signal_compounds": ["C00219"],
        "ground_truth_noise_compounds": ["C00116"],
        "ramp_enrichment_result": {
            "input_compounds": ["C00219"],
            "resolved_compounds": ["C00219"],
            "unresolved_compounds": [],
            "background_size": 1000,
            "n_input_resolved": 1,
            "top_pathways": [],
        },
    }


_VALID_FINAL_JSON = json.dumps({
    "narrative_text": "Eicosanoid synthesis (WP:WP167) dominates the signal.",
    "claims": [
        {"claim_type": "PATHWAY_ENRICHMENT", "pathway_id": "WP:WP167",
         "pathway_name": "Eicosanoid synthesis"},
    ],
})


def _fake_chat_factory(n_iterations: int):
    """Returns a callable that emits one finalise-only assistant message
    per LLM invocation. The narrative is the same valid grammar-v2 each
    time — the test cares about iter trajectory & verdict, not LLM
    content variation."""
    n_calls = [0]

    def _chat(_messages, **_kwargs):
        n_calls[0] += 1
        return {
            "role": "assistant",
            "content": f"```json\n{_VALID_FINAL_JSON}\n```",
        }
    _chat.n_calls = n_calls  # type: ignore[attr-defined]
    return _chat


def _verdict_with_quality(supported: int, unsupported: int, contradicted: int = 0):
    """Build a mock VerifiedIdentification-like object with target counts."""
    return MagicMock(
        verdicts_total={
            "supported": supported,
            "unsupported": unsupported,
            "contradicted": contradicted,
            "unverifiable_v0": 0,
        },
        claims_v1=[],
        warnings=[],
    )


def _make_runner(chat_responses, verdict_trajectory, fake_task_id="x"):
    """Build a runner whose chat_with_tools cycles `chat_responses` (one
    dict per turn × N iterations) and whose verifier_fn returns the
    next verdict in `verdict_trajectory`."""
    chat_iter = iter(chat_responses)

    def _chat(_messages, **_kwargs):
        return next(chat_iter)

    verdict_iter = iter(verdict_trajectory)

    def _verifier(_narrative, _source_report, **_kwargs):
        return next(verdict_iter)

    return ConcordReactRunner(
        chat_with_tools=_chat,
        verifier_fn=_verifier,
        llm_model="fake-model",
    )


def _finalise_msg(text: str = _VALID_FINAL_JSON) -> dict:
    return {"role": "assistant", "content": f"```json\n{text}\n```"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_early_exit_when_iter0_quality_is_zero(fake_task):
    """quality_N0 == 0 → no feedback iter runs; final_iter_idx=0."""
    runner = _make_runner(
        chat_responses=[_finalise_msg()],
        verdict_trajectory=[_verdict_with_quality(supported=3, unsupported=0)],
    )
    fb = runner.run_task_with_feedback(fake_task)

    assert fb.final_iter_idx == 0
    assert fb.n_feedback_iterations == 0
    assert fb.rollback_reason is None
    assert fb.iterations[0].quality == 0
    assert len(fb.iterations) == 1  # only iter 0


def test_iter1_improves_quality_keeps_n1(fake_task):
    """q(N0)=4 → q(N1)=1 → keep N1; rollback_reason=None."""
    runner = _make_runner(
        chat_responses=[_finalise_msg(), _finalise_msg()],
        verdict_trajectory=[
            _verdict_with_quality(supported=1, unsupported=3, contradicted=1),  # quality=4
            _verdict_with_quality(supported=4, unsupported=1, contradicted=0),  # quality=1
        ],
    )
    runner.max_feedback_iters = 1
    fb = runner.run_task_with_feedback(
        fake_task,
        feedback_msg_builder=lambda _v: "Please fix unsupported claims.",
    )

    assert fb.final_iter_idx == 1
    assert fb.n_feedback_iterations == 1
    assert fb.rollback_reason is None
    assert len(fb.iterations) == 2
    assert fb.iterations[0].quality == 4
    assert fb.iterations[1].quality == 1


def test_iter1_degrades_rollback_to_n0(fake_task):
    """q(N0)=2 → q(N1)=5 → rollback to N0; rollback_reason mentions
    'feedback_made_it_worse'."""
    runner = _make_runner(
        chat_responses=[_finalise_msg(), _finalise_msg()],
        verdict_trajectory=[
            _verdict_with_quality(supported=3, unsupported=2, contradicted=0),  # quality=2
            _verdict_with_quality(supported=1, unsupported=4, contradicted=1),  # quality=5
        ],
    )
    runner.max_feedback_iters = 1
    fb = runner.run_task_with_feedback(
        fake_task,
        feedback_msg_builder=lambda _v: "hint.",
    )

    assert fb.final_iter_idx == 0
    assert fb.n_feedback_iterations == 1
    assert fb.rollback_reason == "feedback_made_it_worse"
    assert len(fb.iterations) == 2


def test_iter2_budget_keeps_best_monotone(fake_task):
    """q(N0)=4, q(N1)=2, q(N2)=1 → no rollback, final=N2."""
    runner = _make_runner(
        chat_responses=[_finalise_msg(), _finalise_msg(), _finalise_msg()],
        verdict_trajectory=[
            _verdict_with_quality(supported=1, unsupported=3, contradicted=1),  # quality=4
            _verdict_with_quality(supported=3, unsupported=2, contradicted=0),  # quality=2
            _verdict_with_quality(supported=4, unsupported=1, contradicted=0),  # quality=1
        ],
    )
    runner.max_feedback_iters = 2
    fb = runner.run_task_with_feedback(
        fake_task,
        feedback_msg_builder=lambda _v: "hint.",
    )

    assert fb.final_iter_idx == 2
    assert fb.n_feedback_iterations == 2
    assert fb.rollback_reason is None
    assert [it.quality for it in fb.iterations] == [4, 2, 1]


def test_iter2_degrades_rollback_to_n1(fake_task):
    """q(N0)=5, q(N1)=2, q(N2)=4 → rollback to N1; reason='iter2_degraded'."""
    runner = _make_runner(
        chat_responses=[_finalise_msg(), _finalise_msg(), _finalise_msg()],
        verdict_trajectory=[
            _verdict_with_quality(supported=0, unsupported=5, contradicted=0),  # quality=5
            _verdict_with_quality(supported=3, unsupported=2, contradicted=0),  # quality=2
            _verdict_with_quality(supported=1, unsupported=4, contradicted=0),  # quality=4
        ],
    )
    runner.max_feedback_iters = 2
    fb = runner.run_task_with_feedback(
        fake_task,
        feedback_msg_builder=lambda _v: "hint.",
    )

    assert fb.final_iter_idx == 1
    assert fb.n_feedback_iterations == 2
    assert fb.rollback_reason == "iter2_degraded"


def test_run_task_accepts_feedback_user_msg(fake_task):
    """run_task(task, feedback_user_msg=...) appends the hint after the
    initial user prompt — verifies the wiring used by the feedback loop
    to seed iter ≥ 1 with verifier feedback."""
    captured_messages = []

    def _chat(messages, **_kwargs):
        captured_messages.append(list(messages))
        return _finalise_msg()

    runner = ConcordReactRunner(
        chat_with_tools=_chat,
        verifier_fn=lambda *_a, **_kw: _verdict_with_quality(2, 0),
        llm_model="fake-model",
    )
    runner.run_task(fake_task, feedback_user_msg="VERIFIER FEEDBACK: re-emit X")

    # First chat call should see 3 messages: system, user prompt, feedback msg
    msgs = captured_messages[0]
    assert any(m.get("role") == "system" for m in msgs)
    user_msgs = [m for m in msgs if m.get("role") == "user"]
    assert len(user_msgs) >= 2  # original + feedback
    assert "VERIFIER FEEDBACK" in user_msgs[-1]["content"]
