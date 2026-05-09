"""Unit tests for evaluation/sub6/run_sub6b_react_feedback.py (phase A2 D3).

The full feedback loop is exercised against a mocked chat_with_tools and
a mocked verifier_fn so unit tests do not need MiniMax / RaMP / KEGG.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from evaluation.sub6 import run_sub6b_react_feedback as runner
from evaluation.sub6.persist import TaskPersister
from evaluation.sub6.run_sub6b_react_feedback import (
    IterationRecord,
    VerdictReport,
    _select_final_iteration,
    build_feedback_message,
    run_sub6b_react_feedback,
)
from tools.agent_tools import dispatcher
from verifier.feedback_hints import annotate_claims
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimType,
    ClaimVerdict,
    VerifiedClaim,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_task() -> dict:
    return {
        "task_id": "test_feedback_task",
        "differential_metabolites": [
            {"name": "Glucose", "kegg_id": "C00031"},
            {"name": "Pyruvate", "kegg_id": "C00022"},
            {"name": "Lactate", "kegg_id": "C00186"},
        ],
        # Ground-truth fields the runner must NOT expose.
        "ground_truth_pathway": "do_not_leak",
    }


@pytest.fixture(autouse=True)
def _reset_state():
    dispatcher.reset_call_cache()
    yield
    dispatcher.reset_call_cache()


def _make_claim(
    *,
    claim_id: str | None = None,
    text: str = "claim",
    verdict: ClaimVerdict,
    pathway_name: str | None = None,
    correction: str | None = None,
    claim_type: ClaimType = ClaimType.BIOLOGICAL,
) -> VerifiedClaim:
    c = VerifiedClaim(
        claim_id=claim_id,
        claim_text=text,
        claim_type=claim_type,
        verdict=verdict,
        evidence="stub evidence",
        correction=correction,
        extracted_fields=ClaimExtractedFields(pathway_name=pathway_name),
    )
    # Annotate to populate feedback_hint where applicable.
    return annotate_claims([c], pass_id="v1")[0]


def _verdict_total(*, supported=0, contradicted=0, unsupported=0, unverifiable_v0=0):
    return {
        "supported": supported,
        "contradicted": contradicted,
        "unsupported": unsupported,
        "unverifiable_v0": unverifiable_v0,
    }


def _final_msg(content: str) -> dict:
    return {"role": "assistant", "content": content, "tool_calls": None}


# ---------------------------------------------------------------------------
# _select_final_iteration — pure function
# ---------------------------------------------------------------------------


def _iter(idx, q, *, verifier_failed: bool = False):
    return IterationRecord(
        iter_idx=idx, narrative=f"N{idx}",
        verdict_total={}, quality=q, n_contradicted=0, n_unsupported=0,
        n_supported=0, n_unverifiable_v0=0, n_tool_calls=0, n_turns=0,
        force_finalised=False, feedback_prompt_used=(idx > 0),
        verifier_failed=verifier_failed,
    )


class TestSelectionRule:
    def test_single_iteration_returns_itself(self):
        idx, err = _select_final_iteration([_iter(0, q=5)])
        assert idx == 0 and err is None

    def test_iter1_better_than_iter0_kept(self):
        # q(N1) < q(N0) → N1 better, keep N1
        idx, err = _select_final_iteration([_iter(0, q=5), _iter(1, q=2)])
        assert idx == 1 and err is None

    def test_iter1_worse_rolls_back_to_n0(self):
        idx, err = _select_final_iteration([_iter(0, q=2), _iter(1, q=5)])
        assert idx == 0
        assert err == "feedback_made_it_worse"

    def test_iter1_tie_with_n0_no_rollback(self):
        # q(N1) == q(N0): not strictly worse → keep N1 (latest)
        # (Strict ``>`` rule per docstring; tie keeps last in 2-iter case)
        idx, err = _select_final_iteration([_iter(0, q=3), _iter(1, q=3)])
        assert idx == 1 and err is None

    def test_n2_worse_than_n0_rollback_to_n0(self):
        idx, err = _select_final_iteration([
            _iter(0, q=2), _iter(1, q=3), _iter(2, q=4),
        ])
        assert idx == 0
        assert err == "feedback_made_it_worse"

    def test_n2_worse_than_n1_only_rollback_to_n1(self):
        idx, err = _select_final_iteration([
            _iter(0, q=10), _iter(1, q=2), _iter(2, q=5),
        ])
        # q(N2)=5 not > q(N0)=10, but > q(N1)=2 → rollback to N1
        assert idx == 1
        assert err == "iter2_degraded"

    def test_n2_best_kept(self):
        idx, err = _select_final_iteration([
            _iter(0, q=10), _iter(1, q=5), _iter(2, q=1),
        ])
        assert idx == 2 and err is None

    # -------- D5 fix: verifier_failed iters excluded --------

    def test_verifier_failed_iter_skipped_in_selection(self):
        # iter 2 q=0 looks great but verifier failed → empty verdict.
        # Selection must NOT pick it; iter 0 (q=2) is the only valid result.
        idx, err = _select_final_iteration([
            _iter(0, q=2),
            _iter(2, q=0, verifier_failed=True),
        ])
        assert idx == 0 and err is None

    def test_n2_verifier_failed_picks_n1_when_better(self):
        idx, err = _select_final_iteration([
            _iter(0, q=10),
            _iter(1, q=2),
            _iter(2, q=0, verifier_failed=True),
        ])
        # valid = [N0(q=10), N1(q=2)]. last=N1. q(N1)=2 < q(N0)=10. keep N1.
        assert idx == 1 and err is None

    def test_all_iters_verifier_failed_returns_sentinel(self):
        idx, err = _select_final_iteration([
            _iter(0, q=0, verifier_failed=True),
            _iter(1, q=0, verifier_failed=True),
        ])
        assert idx == 0
        assert err == "all_iters_verifier_failed"

    def test_iter0_failed_iter1_ok_selects_iter1(self):
        idx, err = _select_final_iteration([
            _iter(0, q=0, verifier_failed=True),
            _iter(1, q=2),
        ])
        # Only N1 is valid; selection returns it cleanly.
        assert idx == 1 and err is None


# ---------------------------------------------------------------------------
# build_feedback_message — placeholder substitution + ground-truth safety
# ---------------------------------------------------------------------------


class TestFeedbackMessage:
    def test_empty_inputs_render_clean(self):
        msg = build_feedback_message(
            contradicted=[], unsupported=[], original_narrative="hello",
        )
        assert "0 CONTRADICTED" in msg
        assert "(none)" in msg
        assert "hello" in msg

    def test_contradicted_block_includes_id_text_evidence_hint(self):
        c = _make_claim(
            claim_id="v1:c042",
            text="Methionine drives glycolysis",
            verdict=ClaimVerdict.CONTRADICTED,
            claim_type=ClaimType.PATHWAY_RELATIONSHIP,
        )
        msg = build_feedback_message(
            contradicted=[c], unsupported=[],
            original_narrative="some narrative",
        )
        assert "v1:c042" in msg
        assert "Methionine drives glycolysis" in msg
        assert "Evidence:" in msg
        assert "Hint:" in msg
        assert "KEGG" in msg  # the contradicted-relationship hint mentions KEGG

    def test_long_claim_text_truncated(self):
        long_text = "X" * 500
        c = _make_claim(
            claim_id="v1:c000",
            text=long_text,
            verdict=ClaimVerdict.UNSUPPORTED,
            pathway_name="some pathway",
        )
        msg = build_feedback_message(
            contradicted=[], unsupported=[c],
            original_narrative="orig",
        )
        # 280 chars + "..." = 283 chars max in the bullet
        assert "X" * 280 not in msg or "..." in msg

    def test_no_groundtruth_leak_in_template(self):
        # The template itself should not introduce any field that could
        # come from task.ground_truth_pathway.
        msg = build_feedback_message(
            contradicted=[], unsupported=[], original_narrative="orig",
        )
        assert "ground_truth" not in msg.lower()
        assert "do_not_leak" not in msg


# ---------------------------------------------------------------------------
# Iteration 0 only — no feedback triggered
# ---------------------------------------------------------------------------


class TestIter0NoFeedback:
    def test_clean_narrative_no_feedback_prompt_used(self, fake_task):
        # LLM emits one turn, no tool calls, just narrative.
        chat_responses = iter([_final_msg("Initial narrative is fine.")])

        def fake_chat(*a, **kw):
            return next(chat_responses)

        # Verifier finds 0 actionable claims.
        def fake_verifier(narrative: str) -> VerdictReport:
            return VerdictReport(
                claims=[],
                verdicts_total=_verdict_total(supported=5),
            )

        result = run_sub6b_react_feedback(
            fake_task,
            verifier_fn=fake_verifier,
            chat_with_tools_fn=fake_chat,
            finalise_chat_fn=fake_chat,
            max_react_turns=3,
            max_feedback_iterations=2,
        )

        assert result.error is None
        assert len(result.iterations) == 1
        assert result.iterations[0].iter_idx == 0
        assert result.iterations[0].feedback_prompt_used is False
        assert result.n_feedback_iterations == 0
        assert result.final_iter_idx == 0
        assert result.final_narrative == "Initial narrative is fine."
        assert result.rollback_reason is None


# ---------------------------------------------------------------------------
# One feedback iteration — improvement
# ---------------------------------------------------------------------------


class TestOneFeedbackImproves:
    def test_iter1_reduces_quality(self, fake_task):
        # 2 chat calls: iter 0 narrative, iter 1 narrative.
        chats = iter([
            _final_msg("Initial — Methionine is in pyrimidine metabolism."),
            _final_msg("Revised — retracted Methionine claim."),
        ])

        def fake_chat(*a, **kw):
            return next(chats)

        # Verifier returns 2 contradicted claims on N0, then 0 on N1.
        verdict_calls = {"n": 0}

        def fake_verifier(narrative: str) -> VerdictReport:
            verdict_calls["n"] += 1
            if verdict_calls["n"] == 1:
                bad = [
                    _make_claim(
                        text="Methionine is in pyrimidine metabolism",
                        verdict=ClaimVerdict.CONTRADICTED,
                        claim_type=ClaimType.BIOLOGICAL,
                        pathway_name="pyrimidine metabolism",
                    ),
                    _make_claim(
                        text="Other unsupported",
                        verdict=ClaimVerdict.UNSUPPORTED,
                        pathway_name="some pathway",
                    ),
                ]
                return VerdictReport(claims=bad, verdicts_total=_verdict_total(
                    supported=3, contradicted=1, unsupported=1,
                ))
            return VerdictReport(claims=[], verdicts_total=_verdict_total(supported=4))

        result = run_sub6b_react_feedback(
            fake_task,
            verifier_fn=fake_verifier,
            chat_with_tools_fn=fake_chat,
            finalise_chat_fn=fake_chat,
            max_react_turns=3,
            max_feedback_iterations=2,
        )

        assert result.error is None
        assert len(result.iterations) == 2
        assert result.iterations[0].quality == 2
        assert result.iterations[1].quality == 0
        assert result.iterations[1].feedback_prompt_used is True
        assert result.n_feedback_iterations == 1
        assert result.final_iter_idx == 1
        assert "retracted" in result.final_narrative
        assert result.rollback_reason is None


# ---------------------------------------------------------------------------
# Quality regression — rollback to N0
# ---------------------------------------------------------------------------


class TestRollbackToN0:
    def test_iter1_makes_it_worse(self, fake_task):
        chats = iter([
            _final_msg("Initial narrative."),
            _final_msg("Revised but introduced new bad claims."),
        ])

        def fake_chat(*a, **kw):
            return next(chats)

        verdict_calls = {"n": 0}

        def fake_verifier(narrative: str) -> VerdictReport:
            verdict_calls["n"] += 1
            if verdict_calls["n"] == 1:
                return VerdictReport(
                    claims=[_make_claim(verdict=ClaimVerdict.CONTRADICTED, claim_id="v1:c0")],
                    verdicts_total=_verdict_total(supported=4, contradicted=1),
                )
            # N1 has more bad claims than N0
            return VerdictReport(
                claims=[
                    _make_claim(verdict=ClaimVerdict.CONTRADICTED, claim_id="v1:c0"),
                    _make_claim(verdict=ClaimVerdict.CONTRADICTED, claim_id="v1:c1"),
                    _make_claim(verdict=ClaimVerdict.UNSUPPORTED, claim_id="v1:c2"),
                ],
                verdicts_total=_verdict_total(supported=2, contradicted=2, unsupported=1),
            )

        result = run_sub6b_react_feedback(
            fake_task,
            verifier_fn=fake_verifier,
            chat_with_tools_fn=fake_chat,
            finalise_chat_fn=fake_chat,
            max_react_turns=3,
            max_feedback_iterations=1,
        )

        assert result.iterations[0].quality == 1
        assert result.iterations[1].quality == 3
        assert result.final_iter_idx == 0
        assert result.final_narrative == "Initial narrative."
        assert result.rollback_reason == "feedback_made_it_worse"


# ---------------------------------------------------------------------------
# LLM error on iter 0 — bail without verifier call
# ---------------------------------------------------------------------------


class TestLLMErrorIter0:
    def test_llm_exception_recorded(self, fake_task):
        def bad_chat(*a, **kw):
            raise RuntimeError("network is down")

        verifier_called = {"n": 0}

        def fake_verifier(narrative: str) -> VerdictReport:
            verifier_called["n"] += 1
            return VerdictReport([], _verdict_total())

        result = run_sub6b_react_feedback(
            fake_task,
            verifier_fn=fake_verifier,
            chat_with_tools_fn=bad_chat,
            finalise_chat_fn=bad_chat,
            max_react_turns=3,
            max_feedback_iterations=2,
        )

        assert result.error and "RuntimeError" in result.error
        # Verifier must NOT be called when iter 0 fails on the LLM.
        assert verifier_called["n"] == 0


# ---------------------------------------------------------------------------
# Verifier error on iter 0 — recorded but iteration 0 still kept
# ---------------------------------------------------------------------------


class TestVerifierErrorIter0:
    def test_verifier_exception_does_not_kill_run(self, fake_task):
        chats = iter([_final_msg("Some narrative.")])

        def fake_chat(*a, **kw):
            return next(chats)

        def bad_verifier(narrative: str) -> VerdictReport:
            raise RuntimeError("verifier crashed")

        result = run_sub6b_react_feedback(
            fake_task,
            verifier_fn=bad_verifier,
            chat_with_tools_fn=fake_chat,
            finalise_chat_fn=fake_chat,
            max_react_turns=3,
            max_feedback_iterations=2,
        )

        assert result.error and "verifier_failed_iter0" in result.error
        assert len(result.iterations) == 1
        assert result.iterations[0].quality == 0  # empty verdict ⇒ 0


# ---------------------------------------------------------------------------
# Ground-truth scrubbing
# ---------------------------------------------------------------------------


class TestGroundTruthScrubbing:
    def test_no_ground_truth_in_messages_history(self, fake_task):
        sent: list[list[dict]] = []

        def record(messages, **kw):
            sent.append([dict(m) for m in messages])
            return _final_msg("Narrative.")

        def fake_verifier(narrative: str) -> VerdictReport:
            return VerdictReport([], _verdict_total(supported=1))

        run_sub6b_react_feedback(
            fake_task,
            verifier_fn=fake_verifier,
            chat_with_tools_fn=record,
            finalise_chat_fn=record,
            max_react_turns=3,
            max_feedback_iterations=2,
        )
        assert "do_not_leak" not in json.dumps(sent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Persister wiring
# ---------------------------------------------------------------------------


class TestTerminationReason:
    def test_early_exit_no_revisions(self, fake_task):
        # Iter 0 verifier finds 0 actionable → feedback loop never runs.
        chats = iter([_final_msg("Initial.")])

        def fake_chat(*a, **kw):
            return next(chats)

        def fake_verifier(narrative: str) -> VerdictReport:
            return VerdictReport([], _verdict_total(supported=4))

        result = run_sub6b_react_feedback(
            fake_task,
            verifier_fn=fake_verifier,
            chat_with_tools_fn=fake_chat, finalise_chat_fn=fake_chat,
            max_react_turns=3, max_feedback_iterations=2,
        )
        assert result.termination_reason == "early_exit_no_revisions"
        assert result.n_feedback_iterations == 0

    def test_max_iterations_reached(self, fake_task):
        # Both iterations produce actionable claims; loop exhausts.
        chats = iter([
            _final_msg("N0."), _final_msg("N1."), _final_msg("N2."),
        ])

        def fake_chat(*a, **kw):
            return next(chats)

        def fake_verifier(narrative: str) -> VerdictReport:
            # Always returns 1 contradicted — never converges.
            return VerdictReport(
                claims=[_make_claim(verdict=ClaimVerdict.CONTRADICTED, claim_id="c0")],
                verdicts_total=_verdict_total(contradicted=1, supported=2),
            )

        result = run_sub6b_react_feedback(
            fake_task,
            verifier_fn=fake_verifier,
            chat_with_tools_fn=fake_chat, finalise_chat_fn=fake_chat,
            max_react_turns=3, max_feedback_iterations=2,
        )
        assert result.termination_reason == "max_iterations_reached"
        assert result.n_feedback_iterations == 2

    def test_no_actionable_claims_after_iter1(self, fake_task):
        # Iter 1 converges to 0 actionable.
        chats = iter([_final_msg("N0."), _final_msg("N1.")])

        def fake_chat(*a, **kw):
            return next(chats)

        verdict_calls = {"n": 0}

        def fake_verifier(narrative: str) -> VerdictReport:
            verdict_calls["n"] += 1
            if verdict_calls["n"] == 1:
                return VerdictReport(
                    claims=[_make_claim(verdict=ClaimVerdict.CONTRADICTED, claim_id="c0")],
                    verdicts_total=_verdict_total(contradicted=1, supported=2),
                )
            return VerdictReport([], _verdict_total(supported=4))

        result = run_sub6b_react_feedback(
            fake_task,
            verifier_fn=fake_verifier,
            chat_with_tools_fn=fake_chat, finalise_chat_fn=fake_chat,
            max_react_turns=3, max_feedback_iterations=2,
        )
        assert result.termination_reason == "no_actionable_claims_after_iter"
        assert result.n_feedback_iterations == 1


class TestPersisterIntegration:
    def test_persister_records_turns_and_completes(self, fake_task, tmp_path):
        chats = iter([
            _final_msg("Initial."),
            _final_msg("Revised."),
        ])

        def fake_chat(*a, **kw):
            return next(chats)

        verdict_calls = {"n": 0}

        def fake_verifier(narrative: str) -> VerdictReport:
            verdict_calls["n"] += 1
            if verdict_calls["n"] == 1:
                return VerdictReport(
                    claims=[_make_claim(verdict=ClaimVerdict.CONTRADICTED)],
                    verdicts_total=_verdict_total(contradicted=1, supported=2),
                )
            return VerdictReport([], _verdict_total(supported=3))

        persister = TaskPersister(tmp_path, fake_task["task_id"])
        result = run_sub6b_react_feedback(
            fake_task,
            verifier_fn=fake_verifier,
            chat_with_tools_fn=fake_chat,
            finalise_chat_fn=fake_chat,
            max_react_turns=3,
            max_feedback_iterations=2,
            persister=persister,
        )

        # Final state file written.
        assert (tmp_path / fake_task["task_id"] / "final_state.json").is_file()
        # Turns and iterations recorded.
        turns_path = tmp_path / fake_task["task_id"] / "turns.jsonl"
        iters_path = tmp_path / fake_task["task_id"] / "iterations.jsonl"
        assert turns_path.is_file()
        assert iters_path.is_file()
        iter_lines = iters_path.read_text().splitlines()
        assert len(iter_lines) == 2  # iter 0 + iter 1
        # final_state encodes the rollback reason and qualities
        final = json.loads((tmp_path / fake_task["task_id"] / "final_state.json").read_text())
        assert final["extra"]["qualities"] == [1, 0]
        assert final["extra"]["final_iter_idx"] == 1
