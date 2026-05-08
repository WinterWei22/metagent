"""Unit tests for evaluation/sub6/run_sub6b_react.py (Phase A1, D2).

The full ReAct loop is exercised against a mocked LLM via
``llm_client.set_mock_tool_messages`` (Q3 — extended mock protocol). The
underlying tools are mocked at their wrapper boundary so unit tests do
NOT need RaMP / HMDB / KEGG DBs.
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

from common import llm_client
from evaluation.sub6 import run_sub6b_react as runner
from tools.agent_tools import dispatcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_task() -> dict:
    return {
        "task_id": "test_task_1",
        "differential_metabolites": [
            {"name": "Glucose", "kegg_id": "C00031", "hmdb_id": "HMDB0000122"},
            {"name": "Pyruvate", "kegg_id": "C00022", "hmdb_id": "HMDB0000243"},
            {"name": "Lactate", "kegg_id": "C00186", "hmdb_id": "HMDB0000190"},
        ],
        # Decoy ground-truth fields to confirm _strip_ground_truth scrubs them.
        "ground_truth_pathway": "should not leak",
        "ramp_pathway_ids": ["RAMP_P_x"],
    }


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Isolate each test from mock / cache leakage."""
    llm_client.clear_mock_tool_messages()
    dispatcher.reset_call_cache()
    yield
    llm_client.clear_mock_tool_messages()
    dispatcher.reset_call_cache()


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


# ---------------------------------------------------------------------------
# Happy-path: single-tool then narrative
# ---------------------------------------------------------------------------


class TestReactRunnerHappyPath:
    def test_single_tool_then_narrative(self, fake_task):
        # Turn 1: LLM asks for enrichment. Turn 2: LLM emits narrative.
        llm_client.set_mock_tool_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        _tool_call(
                            "call_enrich",
                            "query_ramp_enrichment",
                            {"compound_kegg_ids": ["C00031", "C00022", "C00186"]},
                        ),
                    ],
                },
                {
                    "role": "assistant",
                    "content": (
                        "Glycolysis is clearly affected. Glucose, pyruvate, and "
                        "lactate are all canonical glycolysis nodes. Pyruvate "
                        "sits at the junction with the TCA cycle; lactate is "
                        "the anaerobic fermentation product." * 4
                    ),
                    "tool_calls": None,
                },
            ]
        )
        # Stub the wrapper so we don't touch the RaMP DB.
        with patch.dict(
            dispatcher.WRAPPERS,
            {"query_ramp_enrichment": lambda payload: {
                "n_input": 3, "n_resolved": 3, "background_size": 12000,
                "ramp_snapshot_date": "2024-09-01",
                "top_pathways": [{
                    "name": "Glycolysis",
                    "source": "kegg",
                    "external_id": "hsa00010",
                    "fdr": 1e-4,
                    "fold_enrichment": 18.5,
                    "matched_compounds": ["C00031", "C00022", "C00186"],
                    "pathway_size": 70,
                }],
            }},
        ):
            result = runner.run_sub6b_react(fake_task, max_turns=5)

        assert result.task_id == "test_task_1"
        assert result.error is None
        assert result.n_turns == 2
        assert result.n_tool_calls == 1
        assert result.metabolite_count == 3
        assert "Glycolysis" in result.narrative
        # tool_calls_log is populated and well-formed
        assert len(result.tool_calls_log) == 1
        log = result.tool_calls_log[0]
        assert log["name"] == "query_ramp_enrichment"
        assert log["turn"] == 1
        assert log["cached"] is False
        # Argument string is JSON
        args = json.loads(log["arguments"])
        assert args["compound_kegg_ids"] == ["C00031", "C00022", "C00186"]
        # Result was projected (no internal field leakage)
        assert "top_pathways" in log["result"]


# ---------------------------------------------------------------------------
# Multi-turn / multi-tool flow
# ---------------------------------------------------------------------------


class TestReactRunnerMultiTurn:
    def test_three_turns_two_tools_then_narrative(self, fake_task):
        llm_client.set_mock_tool_messages(
            [
                # Turn 1: enrichment
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        _tool_call("c1", "query_ramp_enrichment",
                                   {"compound_kegg_ids": ["C00031", "C00022"]}),
                    ],
                },
                # Turn 2: KEGG path verification
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        _tool_call("c2", "query_kegg_path",
                                   {"compound_a": "C00031", "compound_b": "C00022"}),
                    ],
                },
                # Turn 3: narrative
                {
                    "role": "assistant",
                    "content": "Glycolysis. Glucose → pyruvate, verified path length 9.",
                    "tool_calls": None,
                },
            ]
        )
        with patch.dict(
            dispatcher.WRAPPERS,
            {
                "query_ramp_enrichment": lambda p: {"top_pathways": []},
                "query_kegg_path": lambda p: {
                    "is_reachable": True, "direction": "forward",
                    "shortest_path": ["cpd:C00031", "cpd:C00084", "cpd:C00022"],
                    "path_length": 2,
                },
            },
        ):
            result = runner.run_sub6b_react(fake_task, max_turns=5)

        assert result.error is None
        assert result.n_turns == 3
        assert result.n_tool_calls == 2
        assert {l["name"] for l in result.tool_calls_log} == {
            "query_ramp_enrichment",
            "query_kegg_path",
        }
        assert "verified" in result.narrative.lower()


class TestReactRunnerParallelToolCalls:
    def test_two_tool_calls_in_one_turn(self, fake_task):
        # Some models may emit multiple tool_calls in one assistant message.
        llm_client.set_mock_tool_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        _tool_call("a", "lookup_compound_info",
                                   {"identifier": "HMDB0000122"}),
                        _tool_call("b", "lookup_compound_info",
                                   {"identifier": "HMDB0000243"}),
                    ],
                },
                {
                    "role": "assistant",
                    "content": "Both compounds are well-characterised intermediates of glycolysis.",
                    "tool_calls": None,
                },
            ]
        )
        with patch.dict(
            dispatcher.WRAPPERS,
            {"lookup_compound_info": lambda p: {"found": True,
                                                "primary_name": p["identifier"]}},
        ):
            result = runner.run_sub6b_react(fake_task, max_turns=5)

        assert result.n_turns == 2
        assert result.n_tool_calls == 2
        # Both calls logged with their respective ids
        ids = {l["tool_call_id"] for l in result.tool_calls_log}
        assert ids == {"a", "b"}


# ---------------------------------------------------------------------------
# Termination / fallback
# ---------------------------------------------------------------------------


class TestReactRunnerFallbacks:
    def test_max_turns_exhausted_triggers_finalise(self, fake_task):
        # 5 turns of tool calls + 1 finalise turn = 6 mock messages
        tool_only = {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call(
                "x", "query_ramp_enrichment",
                {"compound_kegg_ids": ["C00031"]},
            )],
        }
        finalise_msg = {
            "role": "assistant",
            "content": "Forced narrative after max_turns.",
            "tool_calls": None,
        }
        # Make each tool call slightly different so dedup cache doesn't kick in
        # (we want to hit max_turns, not cached dedup).
        msgs = []
        for i in range(5):
            msgs.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [_tool_call(
                    f"call_{i}", "query_ramp_enrichment",
                    {"compound_kegg_ids": ["C00031"], "top_k": i + 1},
                )],
            })
        msgs.append(finalise_msg)
        llm_client.set_mock_tool_messages(msgs)

        with patch.dict(
            dispatcher.WRAPPERS,
            {"query_ramp_enrichment": lambda p: {"top_pathways": []}},
        ):
            result = runner.run_sub6b_react(fake_task, max_turns=5)

        assert result.n_turns == 5
        assert result.n_tool_calls == 5
        assert result.narrative == "Forced narrative after max_turns."
        # No error since finalise succeeded.
        assert result.error is None or result.error == "empty_narrative_after_finalise"
        # A 'finalise' caller appears in the logs is hard to test from here;
        # the fact that narrative came from the 6th mock message is enough.

    def test_timeout_triggers_finalise_with_error_marker(self, fake_task):
        # Force the loop to think 0.5s = timeout by setting total_timeout=0.001.
        # First turn returns immediately with tool_calls; the second iteration
        # will see elapsed > timeout and break, triggering finalise.
        llm_client.set_mock_tool_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [_tool_call(
                        "a", "query_ramp_enrichment",
                        {"compound_kegg_ids": ["C00031"]},
                    )],
                },
                # finalise turn
                {
                    "role": "assistant",
                    "content": "Timeout finalise narrative.",
                    "tool_calls": None,
                },
            ]
        )
        with patch.dict(
            dispatcher.WRAPPERS,
            {"query_ramp_enrichment": lambda p: {"top_pathways": []}},
        ):
            # Simulate the timeout by setting a very small budget. The first
            # turn still runs (we check at the start of the next iteration).
            # Sleep a tiny bit between turns is achieved by total_timeout=0.0
            # which trips at the head of turn 2.
            result = runner.run_sub6b_react(
                fake_task, max_turns=5, total_timeout=0.0,
            )

        # We did exactly 1 turn before the timeout check on turn 2 broke us.
        assert result.n_turns == 1
        assert result.n_tool_calls == 1
        assert result.error == "timeout_fallback_used"
        assert result.narrative == "Timeout finalise narrative."

    def test_llm_exception_recorded_as_error(self, fake_task):
        # No mock messages installed → chat_with_tools raises RuntimeError.
        # (We're not in mock mode, and there's no real API key in test env.)
        def bad_chat(*args, **kwargs):
            raise RuntimeError("simulated 500")

        result = runner.run_sub6b_react(
            fake_task,
            chat_with_tools_fn=bad_chat,
            finalise_chat_fn=bad_chat,
            max_turns=5,
        )
        assert result.n_turns == 1
        assert result.n_tool_calls == 0
        assert result.error and "RuntimeError" in result.error
        assert result.narrative == ""

    def test_dispatcher_validation_error_is_returned_to_llm(self, fake_task):
        # LLM passes invalid arguments → dispatcher returns
        # {"error": "validation_error", ...}; LLM sees it and produces narrative.
        llm_client.set_mock_tool_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [_tool_call(
                        "bad", "query_ramp_enrichment",
                        {"compound_kegg_ids": []},  # empty → ValidationError
                    )],
                },
                {
                    "role": "assistant",
                    "content": "Recovered after validation error.",
                    "tool_calls": None,
                },
            ]
        )
        result = runner.run_sub6b_react(fake_task, max_turns=5)
        assert result.error is None
        assert result.n_tool_calls == 1
        assert result.tool_calls_log[0]["result"]["error"] == "validation_error"
        assert "Recovered" in result.narrative


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


class TestPromptBuilder:
    def test_build_react_messages_has_two_roles(self, fake_task):
        from evaluation.sub6.prompts_agent import build_react_messages

        msgs = build_react_messages(fake_task["differential_metabolites"])
        assert [m["role"] for m in msgs] == ["system", "user"]
        # System mentions all five tool names.
        sys_text = msgs[0]["content"]
        for name in (
            "query_ramp_enrichment",
            "query_pathway_membership",
            "query_kegg_path",
            "lookup_compound_info",
            "search_literature",
        ):
            assert name in sys_text
        # User contains the metabolite block bullets.
        usr_text = msgs[1]["content"]
        assert "Glucose" in usr_text
        assert "C00031" in usr_text
        # Ground-truth fields must NOT leak into the prompt.
        assert "should not leak" not in usr_text
        assert "RAMP_P_x" not in usr_text


# ---------------------------------------------------------------------------
# Ground-truth scrubbing (reusing run_sub6b's helper)
# ---------------------------------------------------------------------------


class TestGroundTruthScrubbing:
    def test_no_ground_truth_in_prompt_or_messages(self, fake_task):
        # Build a runner with mocks that record what messages were ever sent
        # to the LLM.
        sent_messages: list[list[dict]] = []

        def record_chat(messages, **kwargs):
            sent_messages.append([dict(m) for m in messages])
            return {
                "role": "assistant",
                "content": "Final narrative.",
                "tool_calls": None,
            }

        runner.run_sub6b_react(
            fake_task,
            chat_with_tools_fn=record_chat,
            finalise_chat_fn=record_chat,
            max_turns=5,
        )

        full_corpus = json.dumps(sent_messages, ensure_ascii=False)
        assert "should not leak" not in full_corpus
        assert "RAMP_P_x" not in full_corpus
