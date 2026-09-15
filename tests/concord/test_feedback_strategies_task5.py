"""Tests for Task 5: FeedbackResult dataclass + apply_feedback_strategy dispatch.

TDD RED → GREEN per feedback-redesign plan Task 5 brief.

Assertions:
  cascade  → kind="cascade", payload=valid JSON with 'claims' key, corrected_claims is list
  anchored → kind="rewrite", payload is str containing supported anchor text, corrected_claims=None
  gated    → kind="rewrite", payload non-None when contradicted present
           → kind="rewrite", payload=None when only supported (no trigger)
  unknown  → raises ValueError
"""
from __future__ import annotations

import json
import pytest

from verifier.grammar import ClaimGrammar
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    SubjectKind,
    VerifiedClaim,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claim(
    *,
    verdict: ClaimVerdict,
    claim_text: str = "Glycolysis is enriched in the metabolite set.",
    grammar: ClaimGrammar | None = ClaimGrammar.PATHWAY_MEMBERSHIP,
    pathway_name: str | None = "Glycolysis",
    subject: str | None = "Glucose",
    correction: str | None = None,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_text=claim_text,
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.ENRICHMENT_PATHWAY,
        subject=subject,
        subject_kind=SubjectKind.UNKNOWN,
        verdict=verdict,
        evidence="test evidence",
        correction=correction,
        extracted_fields=ClaimExtractedFields(
            pathway_name=pathway_name,
        ),
        grammar=grammar,
    )


def _mock_llm_call(prompt: str) -> str:
    """Mock LLM call that returns a predictable narrative."""
    return "Glycolysis plays a central role in cellular metabolism."


def _make_source_report():
    """Minimal source_report stub (just needs to exist)."""
    from types import SimpleNamespace
    return SimpleNamespace(narrative="original narrative")


# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------


def test_feedback_result_importable():
    from concord.agent.feedback_strategies import FeedbackResult  # noqa: F401


def test_apply_feedback_strategy_importable():
    from concord.agent.feedback_strategies import apply_feedback_strategy  # noqa: F401


# ---------------------------------------------------------------------------
# FeedbackResult dataclass shape
# ---------------------------------------------------------------------------


def test_feedback_result_fields():
    """FeedbackResult must have strategy, kind, payload, corrected_claims."""
    from concord.agent.feedback_strategies import FeedbackResult

    fr = FeedbackResult(
        strategy="cascade",
        kind="cascade",
        payload='{"narrative_text": "x", "claims": []}',
        corrected_claims=[],
    )
    assert fr.strategy == "cascade"
    assert fr.kind == "cascade"
    assert fr.payload is not None
    assert fr.corrected_claims is not None


def test_feedback_result_none_fields():
    """FeedbackResult must accept None payload and corrected_claims."""
    from concord.agent.feedback_strategies import FeedbackResult

    fr = FeedbackResult(
        strategy="gated",
        kind="rewrite",
        payload=None,
        corrected_claims=None,
    )
    assert fr.payload is None
    assert fr.corrected_claims is None


# ---------------------------------------------------------------------------
# cascade strategy
# ---------------------------------------------------------------------------


def test_cascade_returns_kind_cascade():
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED),
        _make_claim(verdict=ClaimVerdict.CONTRADICTED, correction="TCA cycle"),
    ]
    result = apply_feedback_strategy(
        "cascade", claims, _make_source_report(), _mock_llm_call
    )
    assert result.kind == "cascade"
    assert result.strategy == "cascade"


def test_cascade_payload_is_valid_json_with_claims():
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [_make_claim(verdict=ClaimVerdict.SUPPORTED)]
    result = apply_feedback_strategy(
        "cascade", claims, _make_source_report(), _mock_llm_call
    )
    assert result.payload is not None
    parsed = json.loads(result.payload)
    assert "claims" in parsed
    assert isinstance(parsed["claims"], list)
    assert len(parsed["claims"]) >= 1


def test_cascade_corrected_claims_is_list():
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED),
        _make_claim(verdict=ClaimVerdict.UNSUPPORTED),  # dropped
    ]
    result = apply_feedback_strategy(
        "cascade", claims, _make_source_report(), _mock_llm_call
    )
    assert result.corrected_claims is not None
    assert isinstance(result.corrected_claims, list)
    # UNSUPPORTED is dropped; only SUPPORTED survives
    assert len(result.corrected_claims) == 1


def test_cascade_narrative_in_payload():
    """The mock LLM returns a predictable string; it should appear in payload."""
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [_make_claim(verdict=ClaimVerdict.SUPPORTED)]
    result = apply_feedback_strategy(
        "cascade", claims, _make_source_report(), _mock_llm_call
    )
    parsed = json.loads(result.payload)
    assert "narrative_text" in parsed
    assert "Glycolysis" in parsed["narrative_text"]  # from mock LLM


# ---------------------------------------------------------------------------
# anchored strategy
# ---------------------------------------------------------------------------


def test_anchored_returns_kind_rewrite():
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED),
        _make_claim(verdict=ClaimVerdict.CONTRADICTED, correction="TCA cycle"),
    ]
    result = apply_feedback_strategy(
        "anchored", claims, _make_source_report(), _mock_llm_call
    )
    assert result.kind == "rewrite"
    assert result.strategy == "anchored"


def test_anchored_payload_is_non_empty_str():
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [_make_claim(verdict=ClaimVerdict.SUPPORTED)]
    result = apply_feedback_strategy(
        "anchored", claims, _make_source_report(), _mock_llm_call
    )
    assert result.payload is not None
    assert isinstance(result.payload, str)
    assert len(result.payload) > 0


def test_anchored_corrected_claims_is_none():
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [_make_claim(verdict=ClaimVerdict.SUPPORTED)]
    result = apply_feedback_strategy(
        "anchored", claims, _make_source_report(), _mock_llm_call
    )
    assert result.corrected_claims is None


def test_anchored_payload_contains_supported_anchor():
    """Anchored feedback prompt must reference the SUPPORTED claim text."""
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claim_text = "Glycolysis is enriched in the metabolite set."
    claims = [_make_claim(verdict=ClaimVerdict.SUPPORTED, claim_text=claim_text)]
    result = apply_feedback_strategy(
        "anchored", claims, _make_source_report(), _mock_llm_call
    )
    assert claim_text in result.payload


# ---------------------------------------------------------------------------
# gated strategy
# ---------------------------------------------------------------------------


def test_gated_triggers_when_contradicted():
    """gated strategy: payload is non-None when CONTRADICTED present."""
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [
        _make_claim(verdict=ClaimVerdict.SUPPORTED),
        _make_claim(verdict=ClaimVerdict.CONTRADICTED, correction="TCA cycle"),
    ]
    result = apply_feedback_strategy(
        "gated", claims, _make_source_report(), _mock_llm_call
    )
    assert result.kind == "rewrite"
    assert result.strategy == "gated"
    assert result.payload is not None
    assert isinstance(result.payload, str)
    assert len(result.payload) > 0


def test_gated_no_trigger_when_only_supported():
    """gated strategy: payload=None when only SUPPORTED claims (no actionable issues)."""
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [_make_claim(verdict=ClaimVerdict.SUPPORTED)]
    result = apply_feedback_strategy(
        "gated", claims, _make_source_report(), _mock_llm_call
    )
    assert result.kind == "rewrite"
    assert result.strategy == "gated"
    assert result.payload is None


def test_gated_triggers_when_unsupported():
    """gated strategy: payload is non-None when UNSUPPORTED present."""
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [
        _make_claim(verdict=ClaimVerdict.UNSUPPORTED),
    ]
    result = apply_feedback_strategy(
        "gated", claims, _make_source_report(), _mock_llm_call
    )
    assert result.payload is not None


def test_gated_corrected_claims_is_none():
    """gated strategy never sets corrected_claims."""
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [_make_claim(verdict=ClaimVerdict.CONTRADICTED, correction="TCA cycle")]
    result = apply_feedback_strategy(
        "gated", claims, _make_source_report(), _mock_llm_call
    )
    assert result.corrected_claims is None


# ---------------------------------------------------------------------------
# unknown strategy → ValueError
# ---------------------------------------------------------------------------


def test_unknown_strategy_raises():
    from concord.agent.feedback_strategies import apply_feedback_strategy

    claims = [_make_claim(verdict=ClaimVerdict.SUPPORTED)]
    with pytest.raises(ValueError, match="unknown strategy"):
        apply_feedback_strategy(
            "bogus_strategy", claims, _make_source_report(), _mock_llm_call
        )
