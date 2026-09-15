"""Tests for concord.agent.feedback_strategies.weave_narrative.

RED -> GREEN TDD for Task 3 (feedback-redesign plan).

Tests that weave_narrative:
1. Passes all corrected_claims' pathway names into the prompt
2. Returns the LLM's narrative text verbatim
3. Calls llm_call exactly once
4. Formats the prompt correctly with all required fields
"""
from __future__ import annotations

import json
import pytest


def test_weave_narrative_import():
    """weave_narrative must be importable from concord.agent.feedback_strategies."""
    from concord.agent.feedback_strategies import weave_narrative  # noqa: F401


def test_weave_narrative_single_claim():
    """weave_narrative with one claim passes pathway_name to LLM and returns narrative."""
    from concord.agent.feedback_strategies import weave_narrative

    corrected_claims = [
        {
            "grammar": "pathway_membership",
            "claim_text": "Glucose is in Glycolysis.",
            "pathway_name": "Glycolysis",
            "subject": "Glucose",
        }
    ]

    mock_narrative = "Glucose is a key substrate in Glycolysis."
    mock_llm_call = lambda prompt: mock_narrative

    result = weave_narrative(corrected_claims, llm_call=mock_llm_call)

    assert result == mock_narrative


def test_weave_narrative_multiple_claims():
    """weave_narrative passes all pathway names into the prompt."""
    from concord.agent.feedback_strategies import weave_narrative

    corrected_claims = [
        {
            "grammar": "pathway_membership",
            "claim_text": "Glucose is in Glycolysis.",
            "pathway_name": "Glycolysis",
            "subject": "Glucose",
        },
        {
            "grammar": "pathway_membership",
            "claim_text": "Pyruvate is in TCA cycle.",
            "pathway_name": "TCA cycle",
            "subject": "Pyruvate",
        },
        {
            "grammar": "pathway_enrichment",
            "claim_text": "Lipid metabolism is enriched.",
            "pathway_name": "Lipid metabolism",
        },
    ]

    mock_narrative = "Multiple pathways are affected."
    call_log = []

    def mock_llm_call(prompt):
        call_log.append(prompt)
        return mock_narrative

    result = weave_narrative(corrected_claims, llm_call=mock_llm_call)

    assert result == mock_narrative
    assert len(call_log) == 1
    # Verify all pathway names are in the prompt
    prompt = call_log[0]
    assert "Glycolysis" in prompt
    assert "TCA cycle" in prompt
    assert "Lipid metabolism" in prompt


def test_weave_narrative_empty_claims():
    """weave_narrative with empty claims list still calls LLM."""
    from concord.agent.feedback_strategies import weave_narrative

    corrected_claims = []
    mock_narrative = "No claims provided."
    call_log = []

    def mock_llm_call(prompt):
        call_log.append(prompt)
        return mock_narrative

    result = weave_narrative(corrected_claims, llm_call=mock_llm_call)

    assert result == mock_narrative
    assert len(call_log) == 1


def test_weave_narrative_llm_call_receives_structured_prompt():
    """weave_narrative constructs a structured prompt with all required fields."""
    from concord.agent.feedback_strategies import weave_narrative

    corrected_claims = [
        {
            "grammar": "pathway_membership",
            "claim_text": "Glycolysis is active.",
            "pathway_name": "Glycolysis",
            "subject": "Metabolite X",
        }
    ]

    received_prompt = []

    def mock_llm_call(prompt):
        received_prompt.append(prompt)
        return "narrative text"

    weave_narrative(corrected_claims, llm_call=mock_llm_call)

    assert len(received_prompt) == 1
    prompt = received_prompt[0]
    # Prompt should be a string
    assert isinstance(prompt, str)
    # Prompt should mention the pathway and the constraint
    assert "pathway" in prompt.lower() or "Glycolysis" in prompt
    # Prompt should have instructions about narrative
    assert len(prompt) > 50  # non-trivial prompt


def test_weave_narrative_handles_missing_pathway_name():
    """weave_narrative handles claims without pathway_name gracefully."""
    from concord.agent.feedback_strategies import weave_narrative

    corrected_claims = [
        {
            "grammar": "driver_metabolite",
            "claim_text": "Compound A drives X.",
            # No pathway_name, but the claim is valid for this grammar
            "subject": "Compound A",
            "pathway_name": None,
        }
    ]

    mock_narrative = "Compound A is active."
    call_log = []

    def mock_llm_call(prompt):
        call_log.append(prompt)
        return mock_narrative

    result = weave_narrative(corrected_claims, llm_call=mock_llm_call)

    assert result == mock_narrative
    assert len(call_log) == 1


def test_weave_narrative_preserves_llm_output_exactly():
    """weave_narrative returns LLM output verbatim without modification."""
    from concord.agent.feedback_strategies import weave_narrative

    corrected_claims = [
        {
            "grammar": "pathway_membership",
            "claim_text": "Test.",
            "pathway_name": "Test Pathway",
        }
    ]

    # Test with various edge-case outputs
    edge_cases = [
        "Simple narrative.",
        "Multiple sentences. This is the second one. And a third.",
        "Narrative with special chars: @#$%^&*()",
        "Unicode: café, résumé, 中文",
        "\n\nWhitespace\n\n  preserved  \n",
    ]

    for expected_output in edge_cases:
        def mock_llm_call(prompt):
            return expected_output

        result = weave_narrative(corrected_claims, llm_call=mock_llm_call)
        assert result == expected_output


def test_weave_narrative_constructs_prompt_with_all_claims():
    """weave_narrative prompt includes structured info about each claim."""
    from concord.agent.feedback_strategies import weave_narrative

    corrected_claims = [
        {
            "grammar": "pathway_membership",
            "claim_text": "Compound1 is in Pathway1.",
            "pathway_name": "Pathway1",
            "subject": "Compound1",
        },
        {
            "grammar": "metabolite_pathway_link",
            "claim_text": "Compound2 via EnzymeA in Pathway2.",
            "pathway_name": "Pathway2",
            "subject": "Compound2",
            "enzyme_or_reaction": "EnzymeA",
        },
    ]

    received_prompt = []

    def mock_llm_call(prompt):
        received_prompt.append(prompt)
        return "result narrative"

    weave_narrative(corrected_claims, llm_call=mock_llm_call)

    prompt = received_prompt[0]
    # Should reference both pathways
    assert "Pathway1" in prompt
    assert "Pathway2" in prompt
    # Should have instructions
    assert "narrative" in prompt.lower()


def test_weave_narrative_default_llm_call():
    """weave_narrative can use default LLM call if none provided."""
    from concord.agent.feedback_strategies import weave_narrative
    from unittest.mock import patch

    corrected_claims = [
        {
            "grammar": "pathway_membership",
            "claim_text": "Test",
            "pathway_name": "Test Path",
        }
    ]

    # Mock the default LLM call
    mock_response = "Default LLM narrative"
    with patch("common.llm_client.chat") as mock_chat:
        mock_chat.return_value = mock_response
        # Call without llm_call parameter to test default
        result = weave_narrative(corrected_claims)
        # The function should have made a call and returned the response
        assert mock_chat.called
        assert result == mock_response
