"""W8 D3 — unit tests for `ConcordReactRunner.run_task` body.

The two real smoke runs (steroid + WP167 lipid) live separately under
`evaluation/concord/` and are gated on an LLM API key; here we drive
the loop with a fake `chat_with_tools` so the control-flow is exercised
deterministically and without burning API credit:

  1. Happy path     — 1 turn of tool_calls → 2nd turn finalise with
                      valid grammar-v2 JSON. Verify task_outcome=normal,
                      tool_calls_trace populated, claim parsed.
  2. Inner retry    — 1st finalise emits invalid JSON → 2nd finalise
                      emits valid JSON after retry nudge.
  3. Retry exhausted— Both finalise attempts invalid → task_outcome =
                      empty_system_failure, error informative.
  4. Force-finalise — At turn 8 the runner injects the force-finalise
                      prompt and locks tool_choice="none".

These tests are intentionally light on assertions about message-history
shape (those are B1-pattern details) and heavy on outcome semantics.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from concord.agent.react_runner import (
    ConcordReactRunner,
    GRAMMAR_V2_CLAIM_TYPES,
)


# ---------------------------------------------------------------------------
# Fake LLM client driver
# ---------------------------------------------------------------------------


class FakeChat:
    """Iterates through a scripted response list, one per turn.

    Each scripted item is either:
      - a dict shaped like an OpenAI assistant message
        (e.g. {"role": "assistant", "content": "...", "tool_calls": [...]}),
      - or a callable taking (messages, **kwargs) → dict for tests that
        need to inspect the incoming context.
    """

    def __init__(self, script: list):
        self._script = list(script)
        self._call_count = 0
        self.calls: list[dict[str, Any]] = []

    def __call__(self, messages, **kwargs):
        self.calls.append({
            "messages": list(messages),
            "tool_choice": kwargs.get("tool_choice"),
            "caller": kwargs.get("caller"),
        })
        if self._call_count >= len(self._script):
            raise AssertionError(
                f"FakeChat exhausted after {self._call_count} calls; "
                f"no scripted response for turn {self._call_count + 1}"
            )
        item = self._script[self._call_count]
        self._call_count += 1
        if callable(item):
            return item(messages, **kwargs)
        return dict(item)


def _make_tool_call(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _fake_enrichment_payload() -> dict[str, Any]:
    """A canned PA-tool dispatcher payload the dispatcher would emit
    after monkeypatching the wrapper. For runner tests we monkeypatch
    the dispatcher itself to bypass the wrapper layer entirely."""
    return {
        "ok": True,
        "result": {
            "method": "ora_ramp",
            "pathway_db": "wikipathways",
            "pathways": [
                {
                    "pathway_id": "WP:WP167",
                    "pathway_name": "Eicosanoid synthesis",
                    "rank": 0,
                    "score": 1e-4,
                    "score_type": "p_value",
                    "metabolites_hit": [{"primary_id": "CHEBI:15843", "display_name": "arachidonic acid", "inchikey": "YZXBAPSDXZZRGB-DOFZRALJSA-N"}],
                }
            ],
            "schema_version": "concordmet_v0.3.1",
        },
        "_tool_name": "run_ramp_enrichment",
        "_n_pathways": 1,
        "_n_compound_refs": 1,
    }


def _fake_payload_for_method(method: str, pathway_id: str) -> dict[str, Any]:
    return {
        "ok": True,
        "result": {
            "method": method,
            "pathways": [{"pathway_id": pathway_id, "rank": 1}],
            "schema_version": "concordmet_v0.3.1",
        },
        "_n_pathways": 1,
    }


_VALID_FINAL_JSON = json.dumps({
    "narrative_text": "Eicosanoid synthesis (WP:WP167) dominates the signal.",
    "claims": [
        {
            "claim_type": "PATHWAY_ENRICHMENT",
            "pathway_id": "WP:WP167",
            "pathway_name": "Eicosanoid synthesis",
            "evidence_method": "run_ramp_enrichment",
            "rank": 1,
            "score": 1e-4,
            "score_type": "p_value",
        },
        {
            "claim_type": "PATHWAY_MEMBERSHIP",
            "compound_id": "CHEBI:15843",
            "compound_name": "arachidonic acid",
            "pathway_id": "WP:WP167",
            "pathway_name": "Eicosanoid synthesis",
        },
    ],
})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_task() -> dict[str, Any]:
    """Minimal sub6b-v3 shaped task — only differential_metabolites is
    read by the prompt builder; ground_truth_* must be stripped."""
    return {
        "task_id": "test_smoke_task",
        "differential_metabolites": [
            {"name": "arachidonic acid", "kegg_id": "C00219", "inchikey_first_block": "YZXBAPSDXZZRGB"},
            {"name": "prostaglandin E2", "kegg_id": "C00584", "inchikey_first_block": "XEYBHCRIKKKOJU"},
        ],
        # MUST be stripped by _strip_task_for_llm — verify in test below.
        "ground_truth_pathway": {"pathway_id": "WP:WP167", "pathway_name": "Eicosanoid synthesis"},
        "ground_truth_signal_compounds": ["C00219", "C00584"],
    }


@pytest.fixture(autouse=True)
def _isolate_dispatch_cache():
    from concord.agent.tool_dispatcher import reset_call_cache
    reset_call_cache()
    yield
    reset_call_cache()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_task_happy_path_tool_call_then_finalise(monkeypatch, fake_task):
    """Turn 1: LLM calls run_ramp_enrichment. Turn 2: LLM finalises with
    valid grammar-v2 JSON. Verify outcome=normal + trace shape."""
    # Patch dispatcher to return canned payload without touching wrappers
    from concord.agent import tool_dispatcher as td
    payload = _fake_enrichment_payload()
    monkeypatch.setattr(
        td, "dispatch",
        lambda tc: td.DispatchResult(
            tool_name=tc["function"]["name"],
            tool_call_id=tc["id"],
            payload=payload,
        ),
    )
    # also patch the dispatch reference imported into react_runner module
    from concord.agent import react_runner as rr
    monkeypatch.setattr(rr, "dispatch", td.dispatch)

    chat = FakeChat([
        {  # turn 1 — tool call
            "role": "assistant",
            "content": None,
            "tool_calls": [_make_tool_call(
                "run_ramp_enrichment",
                {"compound_ids": ["C00219", "C00584"]},
                "call_1",
            )],
        },
        {  # turn 2 — finalise
            "role": "assistant",
            "content": f"```json\n{_VALID_FINAL_JSON}\n```",
        },
    ])
    runner = ConcordReactRunner(chat_with_tools=chat, llm_model="fake-model")
    result = runner.run_task(fake_task)

    assert result.task_outcome == "normal", result.error
    assert result.error is None
    assert result.metabolite_count == 2
    assert result.iterations[0].n_turns == 2
    assert result.iterations[0].n_tool_calls == 1
    assert result.iterations[0].inner_retry_used is False
    assert result.tools_called == ["run_ramp_enrichment"]
    assert result.n_distinct_tools_called == 1
    assert len(result.final_claims) == 2
    assert {c["claim_type"] for c in result.final_claims} <= GRAMMAR_V2_CLAIM_TYPES
    assert "Eicosanoid synthesis" in result.final_narrative_text


def test_run_task_preserves_method_keyed_enrichment_carriers(monkeypatch, fake_task):
    """Successful non-RaMP tool payloads stay available for verifier carriers."""
    from concord.agent import tool_dispatcher as td
    from concord.agent import react_runner as rr

    payloads = {
        "run_mummichog": _fake_payload_for_method("mummichog", "MUMM:test"),
        "run_metaboanalystr_psea": _fake_payload_for_method("metaboanalystr_psea", "KEGG:test"),
    }
    monkeypatch.setattr(
        rr, "dispatch",
        lambda tc: td.DispatchResult(
            tool_name=tc["function"]["name"],
            tool_call_id=tc["id"],
            payload=payloads[tc["function"]["name"]],
        ),
    )

    chat = FakeChat([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                _make_tool_call("run_mummichog", {"mz_values": [100.0]}, "call_1"),
                _make_tool_call("run_metaboanalystr_psea", {"compound_ids": ["C00001"]}, "call_2"),
            ],
        },
        {"role": "assistant", "content": f"```json\n{_VALID_FINAL_JSON}\n```"},
    ])
    runner = ConcordReactRunner(chat_with_tools=chat, llm_model="fake-model")
    result = runner.run_task(fake_task)

    assert result.enrichment_carriers["mummichog_enrichment_result"] == payloads["run_mummichog"]["result"]
    assert result.enrichment_carriers["metaboanalystr_enrichment_result"]["psea"] == payloads["run_metaboanalystr_psea"]["result"]


def test_run_task_inner_retry_recovers_from_invalid_finalise(monkeypatch, fake_task):
    """Turn 1: LLM finalises with garbage. Inner retry nudge fires.
    Turn 2: LLM emits valid grammar-v2. Outcome=normal w/ retry used."""
    from concord.agent import react_runner as rr
    # No tool calls at all — short-circuit dispatch
    monkeypatch.setattr(rr, "dispatch", lambda tc: None)  # never called

    chat = FakeChat([
        {  # turn 1 — invalid final
            "role": "assistant",
            "content": "Here's my analysis: lots of free-text but no JSON object.",
        },
        {  # turn 2 — after retry nudge
            "role": "assistant",
            "content": f"```json\n{_VALID_FINAL_JSON}\n```",
        },
    ])
    runner = ConcordReactRunner(chat_with_tools=chat, llm_model="fake-model")
    result = runner.run_task(fake_task)

    assert result.task_outcome == "normal", result.error
    assert result.error is None
    assert result.iterations[0].inner_retry_used is True
    assert result.iterations[0].n_turns == 2


def test_run_task_retry_exhausted_returns_system_failure(monkeypatch, fake_task):
    """Both finalise attempts invalid → empty_system_failure outcome."""
    from concord.agent import react_runner as rr
    monkeypatch.setattr(rr, "dispatch", lambda tc: None)

    chat = FakeChat([
        {"role": "assistant", "content": "no JSON, just prose"},
        {"role": "assistant", "content": "still no JSON, prose again"},
    ])
    runner = ConcordReactRunner(chat_with_tools=chat, llm_model="fake-model")
    result = runner.run_task(fake_task)

    assert result.task_outcome == "empty_system_failure"
    assert result.error is not None and "invalid_final_json" in result.error
    assert result.termination_reason == "invalid_final_json_after_retry"
    assert result.iterations[0].inner_retry_used is True


def test_run_task_force_finalise_at_max_turn(monkeypatch, fake_task):
    """At turn==max_react_turns, the runner injects the force-finalise
    prompt and locks tool_choice='none'."""
    from concord.agent import tool_dispatcher as td
    from concord.agent import react_runner as rr
    payload = _fake_enrichment_payload()
    monkeypatch.setattr(
        rr, "dispatch",
        lambda tc: td.DispatchResult(
            tool_name=tc["function"]["name"],
            tool_call_id=tc["id"],
            payload=payload,
        ),
    )

    # 7 tool-calling turns + 1 forced finalise = 8 turns total
    tool_turn = {
        "role": "assistant",
        "content": None,
        "tool_calls": [_make_tool_call(
            "run_ramp_enrichment",
            {"compound_ids": ["C00219"]},
            "call_X",
        )],
    }
    chat = FakeChat(
        [dict(tool_turn) for _ in range(7)]  # 7 tool-call turns
        + [{
            "role": "assistant",
            "content": f"```json\n{_VALID_FINAL_JSON}\n```",
        }]
    )
    runner = ConcordReactRunner(chat_with_tools=chat, llm_model="fake-model")
    result = runner.run_task(fake_task)

    # On the 8th turn (== max_react_turns) tool_choice flipped to "none"
    assert chat.calls[-1]["tool_choice"] == "none"
    assert result.iterations[0].force_finalised is True
    assert result.task_outcome == "normal"
    assert result.iterations[0].n_turns == 8


def test_run_task_strips_ground_truth_before_prompt(monkeypatch, fake_task):
    """Ground-truth fields must never appear in any LLM message."""
    from concord.agent import react_runner as rr
    monkeypatch.setattr(rr, "dispatch", lambda tc: None)
    chat = FakeChat([
        {"role": "assistant", "content": f"```json\n{_VALID_FINAL_JSON}\n```"},
    ])
    runner = ConcordReactRunner(chat_with_tools=chat, llm_model="fake-model")
    runner.run_task(fake_task)
    # Inspect the first call's messages — none should mention ground truth.
    full_prompt = "\n".join(m.get("content") or "" for m in chat.calls[0]["messages"])
    assert "ground_truth_pathway" not in full_prompt
    assert "ground_truth_signal_compounds" not in full_prompt
    # WP167 happens to be in the system prompt (as the lipid smoking-gun
    # NAMING-BRIDGE example), but never embedded with a value field that
    # would betray ground truth on this task.
