"""Unit tests for the top-level ``verify()`` cascade.

These tests exercise stage stitching with mocked LLM responses. The
hardest, O1-real-output tests live in ``test_agent_real_o1_outputs.py``.
"""
from __future__ import annotations

import json

from common import llm_client
from verifier.agent import verify
from verifier.schemas import ClaimVerdict


def _glucose_mock_sequence_with_contradiction():
    """Return the LLM responses for a glucose cascade where H1 fires."""
    return [
        # Stage 1 v1 — extracts the H1 contradiction + supporting claims
        json.dumps([
            {"claim_text": "D-Gulose has molecular formula C7H14O7",
             "subject": "D-Gulose"},
            {"claim_text": "D-Gulose evidence_score is 0.771",
             "subject": "D-Gulose"},
            {"claim_text": "D-Gulose appears in galactose metabolism",
             "subject": "D-Gulose"},
        ]),
        # Stage 2 — all rule-classifiable, NO LLM call
        # Stage 3 D — no intra-document contradiction (all 3 claims agree)
        "[]",
        # Stage 4 rewrite
        "## Report\n**D-Gulose (C6H12O6)**\nevidence_score 0.771\n"
        "appears in galactose metabolism.",
        # Stage 4 re-extract (v2)
        json.dumps([
            {"claim_text": "D-Gulose has molecular formula C6H12O6",
             "subject": "D-Gulose"},
            {"claim_text": "D-Gulose evidence_score is 0.771",
             "subject": "D-Gulose"},
            {"claim_text": "D-Gulose appears in galactose metabolism",
             "subject": "D-Gulose"},
        ]),
        # Stage 3 D on v2
        "[]",
    ]


def test_full_cascade_catches_H1_and_corrects_it(glucose_report):
    llm_client.set_mock(_glucose_mock_sequence_with_contradiction())
    result = verify(
        "## Report\n**D-Gulose (C7H14O7)**",
        glucose_report,
        trace_id="test-glucose",
    )
    # H1 contradiction in v1
    v1_h1 = next(c for c in result.claims_v1 if "C7H14O7" in c.claim_text)
    assert v1_h1.verdict == ClaimVerdict.CONTRADICTED
    assert v1_h1.correction == "C6H12O6"

    # v2 all supported after rewrite
    assert all(c.verdict == ClaimVerdict.SUPPORTED for c in result.claims_v2)
    assert result.overall_verdict == "verified"

    # Budget: 5 calls (extract v1, consistency v1, rewrite, extract v2,
    # consistency v2). No Stage 2 LLM fallback needed since all claims
    # were rule-classifiable.
    assert result.llm_call_count == 5
    assert [t.pass_id for t in result.claim_tables] == ["v1", "v2"]
    assert result.claim_metrics is not None
    assert result.claim_metrics.total_claims == len(result.claims_v2)


def test_source_llm_output_preserved_verbatim(glucose_report):
    llm_client.set_mock(_glucose_mock_sequence_with_contradiction())
    original = "## Report\n**D-Gulose (C7H14O7)**"
    result = verify(original, glucose_report, trace_id="t2")
    assert result.source_llm_output == original


def test_no_rewrite_when_all_v1_claims_supported(glucose_report):
    # Only 1 LLM call — extract v1. No ambiguity, no contradictions, no
    # Stage 3 D call (need ≥2 claims for a pair, which we do have, so
    # still 2 calls: extract + consistency).
    llm_client.set_mock([
        json.dumps([
            {"claim_text": "Glucose has molecular formula C6H12O6",
             "subject": "Glucose"},
            {"claim_text": "D-Gulose evidence_score is 0.771",
             "subject": "D-Gulose"},
        ]),
        "[]",  # no consistency contradictions
    ])
    result = verify(
        "Glucose has C6H12O6. D-Gulose evidence_score 0.771.",
        glucose_report,
        trace_id="t3",
    )
    assert result.overall_verdict == "verified"
    assert result.rewritten_output == result.source_llm_output
    assert result.llm_call_count == 2
    assert len(result.claims_v2) == len(result.claims_v1)


def test_budget_ceiling_is_seven(glucose_report):
    # Ceiling is 7 LLM calls per verification:
    #   1 extract-v1, 2 classify-v1 (ambiguous), 3 consistency-v1,
    #   4 rewrite,    5 extract-v2, 6 classify-v2 (ambiguous),
    #   7 consistency-v2.
    # The original design doc said 6 — Stage 2 was implicitly
    # double-counted. The first live integration run hit 7 with two
    # ambiguous-claim passes. This test pins the ceiling so any future
    # design change that makes it overflow gets caught.
    llm_client.set_mock([
        json.dumps([
            {"claim_text": "The structure is synthetically plausible",
             "subject": "D-Gulose"},  # ambiguous → Stage 2 LLM
            {"claim_text": "Another ambiguous statement", "subject": None},
        ]),
        "0: grounded_claim\n1: grounded_claim",  # Stage 2 v1
        "[]",                          # Stage 3 D v1
        "REWRITTEN NARRATIVE",         # Stage 4
        json.dumps([
            {"claim_text": "Yet another ambiguous statement", "subject": None},
            {"claim_text": "And one more ambiguous statement", "subject": None},
        ]),
        "0: grounded_claim\n1: grounded_claim",  # Stage 2 v2
        "[]",                          # Stage 3 D v2
    ])
    result = verify("dummy non-empty input", glucose_report, trace_id="t4")
    assert result.llm_call_count == 7


def test_extractor_failure_returns_failed(glucose_report):
    llm_client.set_mock(["I am not JSON"])
    result = verify("dummy", glucose_report, trace_id="t5")
    assert result.overall_verdict == "failed"
    assert result.claims_v1 == [] and result.claims_v2 == []
    assert any("VERIFICATION_PARSE_FAILED" in w
               for w in result.verification_warnings)


def test_empty_input_reports_failed(glucose_report):
    # Empty input → Stage 1 short-circuits with [] claims → failed
    llm_client.set_mock([])
    result = verify("", glucose_report, trace_id="t6")
    assert result.overall_verdict == "failed"
    assert result.llm_call_count == 0
