"""Phase B1 D2 wire-up guard: every Sub-6 LLM call that *produces* a
narrative-to-be-extracted MUST pass ``response_format={"type":
"json_object"}`` so the downstream extractor sees structured JSON
matching ``verifier.grammar.ClaimV2``.

The wire is split:

* **single-call / finalise** paths: response_format IS REQUIRED.
* **ReAct intermediate turns** (tool_choice="auto"): response_format
  is INTENTIONALLY OMITTED. ``json_object`` mode and OpenAI-style
  ``tool_calls`` interact poorly across providers (verified empirically
  for MiniMax M2.7); intermediate turns must keep the tool path
  available. If the LLM emits ``content`` in an intermediate turn it
  falls through the legacy extractor fallback path.

Tests use ``unittest.mock`` to intercept the chat function rather than
``llm_client.set_mock`` because we want to inspect *kwargs*, not just
return canned strings.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chat_str(return_value: str = '{"narrative_text":"x","claims":[]}') -> MagicMock:
    """Stand-in for ``llm_client.chat`` (string return)."""
    m = MagicMock(return_value=return_value)
    return m


def _make_chat_with_tools(
    intermediate_msgs: list[dict] | None = None,
    final_msg: dict | None = None,
) -> MagicMock:
    """Stand-in for ``llm_client.chat_with_tools`` (dict return).

    Each call pops the next msg from ``intermediate_msgs`` until that
    list is exhausted, then returns ``final_msg`` forever. This lets a
    test simulate a ReAct loop that produces tool_calls in turn 1 and
    final content in turn 2.
    """
    msgs = list(intermediate_msgs or [])
    fin = final_msg or {"role": "assistant", "content": '{"narrative_text":"x","claims":[]}', "tool_calls": []}

    def _side(*args: Any, **kwargs: Any) -> dict:
        if msgs:
            return msgs.pop(0)
        return fin

    return MagicMock(side_effect=_side)


_SAMPLE_SUB6B_TASK = {
    "task_id": "test_b1d2_runner_wire",
    "differential_metabolites": [
        {"name": "L-Methionine", "kegg_id": "C00073"},
        {"name": "L-Cysteine", "kegg_id": "C00097"},
    ],
}


# ---------------------------------------------------------------------------
# Single-call paths
# ---------------------------------------------------------------------------


def test_run_sub6b_singlecall_passes_response_format() -> None:
    from evaluation.sub6 import run_sub6b

    chat = _make_chat_str()
    run_sub6b.run_sub6b(_SAMPLE_SUB6B_TASK, chat_fn=chat)
    assert chat.call_count == 1
    kwargs = chat.call_args.kwargs
    assert kwargs.get("response_format") == {"type": "json_object"}, (
        f"run_sub6b.run_sub6b must request json_object response_format; "
        f"got kwargs={kwargs}"
    )


def test_run_sub6a_singlecall_passes_response_format() -> None:
    """Sub-6A reuses the same single-call narrative shape — D0 §1
    decision: 4-class grammar shared with Sub-6B, no 5th class."""
    from evaluation.sub6 import run_sub6a

    # Run Sub-6A's narrative LLM call directly by stubbing identification.
    # The narrative-producing call is the same ``chat(...)`` invocation
    # that takes a metabolite list — feed it via the chat_fn injection
    # used by the production runner.
    chat = _make_chat_str()

    # Sub-6A's entry surface is richer; we don't need to drive the full
    # identification pipeline, only confirm that the chat() inside the
    # narrative branch (around run_sub6a.py:226) passes response_format.
    # Approach: monkey-patch the function used inline.
    import evaluation.sub6.run_sub6a as r6a

    # Build a minimal task with identified metabolites stub so the
    # narrative branch fires (line 221 ``elif metabolites``).
    task = {
        "task_id": "test_b1d2_sub6a_wire",
        "spectra": [],  # ID stage skipped via stub
    }
    # Stage 1: bypass identification entirely. Mimic the post-id state by
    # patching the function that produces ``metabolites`` from spectra.
    # The simplest reachable code path: call ``run_sub6a.run_sub6a(task,
    # chat_fn=chat, skip_narrative=False)`` after monkeypatching
    # ``identify_spectrum`` to return a tiny synthetic result. Rather
    # than constructing that, we run a direct call: invoke the same
    # chat invocation with the same kwargs the production code uses.
    #
    # Instead of replicating Sub-6A's identification pipeline in a
    # test, assert the call site itself by grep-checking the source —
    # that is what the runner_response_format wire-up commit must
    # protect.
    import inspect

    src = inspect.getsource(r6a)
    # The exact call signature lives around line 226 (Phase B1 D2 wire).
    needle = 'response_format={"type": "json_object"}'
    assert needle in src, (
        f"run_sub6a.py must contain {needle!r} in its narrative chat() "
        "call — Sub-6A narratives feed the same verifier extractor."
    )


# ---------------------------------------------------------------------------
# ReAct paths — finalise turn gets response_format, intermediate does NOT
# ---------------------------------------------------------------------------


def test_run_sub6b_react_finalise_passes_response_format_but_not_intermediate() -> None:
    """ReAct loop: turn 1 produces a tool_call (intermediate); the
    finalise pass after the loop receives response_format=json_object."""
    from evaluation.sub6 import run_sub6b_react

    # Build a 2-turn flow: turn 1 emits a tool_call, no content; the
    # forced-finalise pass emits the final JSON content.
    turn1 = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "query_ramp_enrichment",
                          "arguments": '{"compound_ids": ["C00073"]}'}}
        ],
    }
    # After tool_call dispatches we ALSO need a turn-2 LLM call that
    # the run_sub6b_react loop will see as empty tool_calls so it
    # breaks out of the loop with a narrative; then the finalise
    # branch will NOT fire (narrative already set). To exercise the
    # finalise branch we instead simulate the loop never producing
    # narrative — return tool_calls forever, then the finalise call
    # fires with tool_choice="none".
    chat_react = _make_chat_with_tools(intermediate_msgs=[turn1, turn1, turn1])
    chat_final = _make_chat_with_tools(
        final_msg={"role": "assistant",
                   "content": '{"narrative_text":"x","claims":[]}',
                   "tool_calls": []},
    )

    # The dispatcher for the tool call would normally hit a real tool.
    # We patch ``dispatch`` to return a benign envelope so the loop
    # advances.
    # The runner imports ``dispatch`` from ``tools.agent_tools`` and
    # uses the module-local binding at call time. Patch the binding
    # inside the runner module.
    real_dispatch = run_sub6b_react.dispatch

    def _stub_dispatch(tool_call: dict) -> dict:
        return {
            "name": tool_call["function"]["name"],
            "tool_call_id": tool_call.get("id"),
            "result": {"ok": True, "rows": []},
            "cached": False,
        }

    run_sub6b_react.dispatch = _stub_dispatch  # type: ignore[assignment]
    try:
        run_sub6b_react.run_sub6b_react(
            _SAMPLE_SUB6B_TASK,
            max_turns=3,
            total_timeout=5.0,
            chat_with_tools_fn=chat_react,
            finalise_chat_fn=chat_final,
        )
    finally:
        run_sub6b_react.dispatch = real_dispatch  # type: ignore[assignment]

    # Intermediate turns must NOT pass response_format
    for call in chat_react.call_args_list:
        rf = call.kwargs.get("response_format")
        assert rf is None, (
            f"ReAct intermediate turn must NOT pass response_format "
            f"(breaks tool_calls); got {rf}"
        )

    # The finalise pass MUST pass response_format=json_object
    assert chat_final.call_count == 1
    fin_rf = chat_final.call_args.kwargs.get("response_format")
    assert fin_rf == {"type": "json_object"}, (
        f"ReAct finalise turn must pass response_format=json_object; "
        f"got {fin_rf}"
    )


def test_run_sub6b_react_feedback_finalise_passes_response_format() -> None:
    """Feedback variant of the same contract — finalise pass requires
    response_format, intermediate turns do not."""
    import inspect
    from evaluation.sub6 import run_sub6b_react_feedback

    src = inspect.getsource(run_sub6b_react_feedback)
    # The wire-up lives at the finalise_chat_fn invocation around line 422.
    needle = 'response_format={"type": "json_object"}'
    assert needle in src, (
        f"run_sub6b_react_feedback.py must contain {needle!r} on its "
        "finalise_chat_fn invocation."
    )

    # And the intermediate chat_with_tools_fn invocation must NOT
    # contain the same kwarg.
    intermediate_block = src[src.find("for turn_idx in range(max_turns):") :]
    intermediate_block = intermediate_block[: intermediate_block.find("# Finalise pass")]
    assert needle not in intermediate_block, (
        "ReAct feedback intermediate turn must NOT pass "
        "response_format=json_object (breaks tool_calls)."
    )


# ---------------------------------------------------------------------------
# Llm_client passthrough sanity (regression for D0 commit)
# ---------------------------------------------------------------------------


def test_llm_client_chat_accepts_response_format_kwarg() -> None:
    """The Phase B1 D0 passthrough must still exist."""
    import inspect
    from common import llm_client

    for fn_name in ("chat", "chat_raw", "chat_with_tools"):
        fn = getattr(llm_client, fn_name)
        sig = inspect.signature(fn)
        assert "response_format" in sig.parameters, (
            f"llm_client.{fn_name} lost its response_format parameter "
            "(D0 regression)."
        )
