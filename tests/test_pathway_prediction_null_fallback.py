"""RED test: generate_pathway_prediction_second_pass must return a legal
abstain fallback dict instead of None when the LLM response is unparseable.

Motivation: 3 tasks in v4_bench_eval_sub6hmdb_secondpass_20260624 had
pathway_prediction=None because the second-pass LLM returned something that
failed parse_pathway_prediction_contract. The fix should produce:
    {"primary": None, "alternatives": [], "abstain": True,
     "abstain_reason": "second_pass_failed"}
instead of None.
"""
from __future__ import annotations

import json
import pytest
from concord.agent.pathway_prediction import generate_pathway_prediction_second_pass


_SAMPLE_CLAIMS = [
    {
        "claim_type": "PATHWAY_ENRICHMENT",
        "pathway_id": "KEGG:map00250",
        "pathway_name": "Alanine, aspartate and glutamate metabolism",
        "evidence_method": "run_ramp_enrichment",
        "rank": 1,
        "score": 0.127,
    }
]

_SAMPLE_NARRATIVE = (
    "Three complementary pathway-enrichment paradigms converge on a single "
    "biological core: disruption of nitrogen and carbon flow through the "
    "glutamate-aspartate axis."
)


def _make_chat_fn(response: str):
    """Return a chat_fn that always returns the given string."""
    def chat_fn(messages, **kwargs):
        return response
    return chat_fn


def _assert_abstain_fallback(result):
    """result must be a dict with abstain=True, not None."""
    assert result is not None, (
        "generate_pathway_prediction_second_pass returned None instead of "
        "abstain fallback dict"
    )
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert result.get("abstain") is True, (
        f"Expected abstain=True in fallback, got: {result}"
    )
    assert result.get("primary") is None, (
        f"Expected primary=None in abstain fallback, got: {result.get('primary')}"
    )
    assert result.get("alternatives") == [], (
        f"Expected alternatives=[] in abstain fallback, got: {result.get('alternatives')}"
    )
    assert result.get("abstain_reason"), (
        "Expected non-empty abstain_reason in fallback"
    )


class TestSecondPassNullFallback:
    """When second-pass LLM returns unparseable content, must return abstain dict."""

    def test_invalid_json_returns_abstain(self):
        """LLM returns garbage text → abstain fallback, not None."""
        chat_fn = _make_chat_fn("This is not JSON at all!!!")
        result = generate_pathway_prediction_second_pass(
            claims=_SAMPLE_CLAIMS,
            narrative_text=_SAMPLE_NARRATIVE,
            chat_fn=chat_fn,
            model="test-model",
            provider="test-provider",
        )
        _assert_abstain_fallback(result)

    def test_empty_response_returns_abstain(self):
        """LLM returns empty string → abstain fallback, not None."""
        chat_fn = _make_chat_fn("")
        result = generate_pathway_prediction_second_pass(
            claims=_SAMPLE_CLAIMS,
            narrative_text=_SAMPLE_NARRATIVE,
            chat_fn=chat_fn,
            model="test-model",
            provider="test-provider",
        )
        _assert_abstain_fallback(result)

    def test_json_missing_pathway_prediction_key_returns_abstain(self):
        """LLM returns JSON without required pathway_prediction structure."""
        # LLM returns a bare dict without 'primary' key — parse fails
        bad_json = json.dumps({"something": "unexpected"})
        chat_fn = _make_chat_fn(bad_json)
        result = generate_pathway_prediction_second_pass(
            claims=_SAMPLE_CLAIMS,
            narrative_text=_SAMPLE_NARRATIVE,
            chat_fn=chat_fn,
            model="test-model",
            provider="test-provider",
        )
        _assert_abstain_fallback(result)

    def test_malformed_primary_returns_abstain(self):
        """LLM returns JSON where primary is malformed (missing name+id)."""
        bad_json = json.dumps({
            "primary": {"confidence": 0.9},  # no pathway_name or pathway_id
            "alternatives": [],
            "abstain": False,
            "abstain_reason": None,
        })
        chat_fn = _make_chat_fn(bad_json)
        result = generate_pathway_prediction_second_pass(
            claims=_SAMPLE_CLAIMS,
            narrative_text=_SAMPLE_NARRATIVE,
            chat_fn=chat_fn,
            model="test-model",
            provider="test-provider",
        )
        _assert_abstain_fallback(result)

    def test_exception_in_chat_fn_returns_abstain(self):
        """LLM call throws exception → abstain fallback, not None."""
        def failing_chat_fn(messages, **kwargs):
            raise RuntimeError("network timeout")

        result = generate_pathway_prediction_second_pass(
            claims=_SAMPLE_CLAIMS,
            narrative_text=_SAMPLE_NARRATIVE,
            chat_fn=failing_chat_fn,
            model="test-model",
            provider="test-provider",
        )
        _assert_abstain_fallback(result)

    def test_valid_response_still_works(self):
        """Sanity: a valid LLM response must still parse correctly (non-regression)."""
        valid_json = json.dumps({
            "primary": {
                "pathway_id": "KEGG:map00250",
                "pathway_name": "Alanine, aspartate and glutamate metabolism",
                "pathway_source": "KEGG",
                "confidence": 0.9,
                "evidence_methods": ["run_ramp_enrichment"],
                "supporting_claim_indices": [0],
                "rationale": "Top-ranked pathway.",
            },
            "alternatives": [],
            "abstain": False,
            "abstain_reason": None,
        })
        chat_fn = _make_chat_fn(valid_json)
        result = generate_pathway_prediction_second_pass(
            claims=_SAMPLE_CLAIMS,
            narrative_text=_SAMPLE_NARRATIVE,
            chat_fn=chat_fn,
            model="test-model",
            provider="test-provider",
        )
        assert result is not None
        assert result.get("abstain") is False
        assert result.get("primary") is not None
        assert result["primary"]["pathway_name"] == "Alanine, aspartate and glutamate metabolism"
