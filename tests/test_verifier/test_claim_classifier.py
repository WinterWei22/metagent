"""Unit tests for Stage 2 classifier (``verifier.claim_classifier``)."""
from __future__ import annotations

import pytest

from common import llm_client
from verifier.claim_classifier import _rule_classify, classify_claims
from verifier.schemas import ClaimType, ExtractedClaim


# ---------------------------------------------------------------------------
# Rule-based classification — should cover the 80%+ pattern library
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("D-Gulose has molecular formula C7H14O7", ClaimType.GROUNDED),
        ("D-Gulose evidence_score is 0.771", ClaimType.GROUNDED),
        ("Predicted-spectrum cosine is 0.423", ClaimType.GROUNDED),
        ("B/C is 0.860", ClaimType.GROUNDED),
        ("The mass accuracy is below 1 ppm vs HMDB reference", ClaimType.GROUNDED),
        ("Linked to galactose metabolism", ClaimType.BIOLOGICAL),
        ("Linked to galactosemia", ClaimType.BIOLOGICAL),
        ("Linked to Fabry disease pathways", ClaimType.BIOLOGICAL),
        ("Caffeine maps to KEGG pathway map00232", ClaimType.BIOLOGICAL),
        ("Caffeine has KEGG ID C07481", ClaimType.FACTUAL),
        ("Top candidate has CID:218057", ClaimType.FACTUAL),
        ("Caffeine InChIKey is RYYVLZVUVIJVGH-UHFFFAOYSA-N", ClaimType.FACTUAL),
        ("Caffeine is in HMDB0001847", ClaimType.FACTUAL),
        ("Bare formula C6H19NSi2", ClaimType.GROUNDED),
    ],
)
def test_rule_classify(text, expected):
    assert _rule_classify(text) == expected


def test_rule_classify_returns_none_on_ambiguous():
    assert _rule_classify("D-Gulose is a C-3 epimer of glucose") is None
    assert _rule_classify("The structure is synthetically plausible") is None


# ---------------------------------------------------------------------------
# classify_claims — rule + LLM fallback
# ---------------------------------------------------------------------------


def _ec(text, subj=None):
    return ExtractedClaim(claim_text=text, subject=subj)


def test_all_rule_decided_costs_no_llm_call():
    llm_client.set_mock([])  # would IndexError if called
    claims = [
        _ec("formula C7H14O7", "D-Gulose"),
        _ec("Linked to galactose metabolism", "D-Gulose"),
        _ec("HMDB0250761", None),
    ]
    classified, n_calls = classify_claims(claims, trace_id="t1")
    assert n_calls == 0
    assert all(c.classifier_source == "rule" for c in classified)
    assert [c.claim_type for c in classified] == [
        ClaimType.GROUNDED, ClaimType.BIOLOGICAL, ClaimType.FACTUAL,
    ]


def test_ambiguous_claims_batched_into_single_llm_call():
    llm_client.set_mock(["0: factual_roundtrip_claim\n1: biological_claim"])
    claims = [
        _ec("D-Gulose is a C-3 epimer of glucose", "D-Gulose"),
        _ec("This appears in biological contexts", None),
    ]
    classified, n_calls = classify_claims(claims, trace_id="t2")
    assert n_calls == 1
    assert all(c.classifier_source == "llm" for c in classified)
    assert classified[0].claim_type == ClaimType.FACTUAL
    assert classified[1].claim_type == ClaimType.BIOLOGICAL


def test_llm_malformed_line_defaults_to_fallback():
    llm_client.set_mock(["0: biological_claim\n1: malformed-no-valid-type"])
    claims = [_ec("X?", None), _ec("Y?", None)]
    classified, n_calls = classify_claims(claims, trace_id="t3")
    assert n_calls == 1
    assert classified[0].classifier_source == "llm"
    assert classified[1].classifier_source == "fallback"
    # fallback default is GROUNDED so the downstream layer has *some*
    # plausible route; evaluation can filter on source == "fallback".
    assert classified[1].claim_type == ClaimType.GROUNDED


def test_mixed_rule_and_llm_only_ambiguous_costs_one_call():
    # Only the second claim is ambiguous
    llm_client.set_mock(["0: factual_roundtrip_claim"])
    claims = [
        _ec("formula C7H14O7", "D-Gulose"),            # rule -> GROUNDED
        _ec("D-Gulose is a fancy molecule", "D-Gulose"),  # ambiguous -> LLM
        _ec("Linked to galactose metabolism", None),   # rule -> BIOLOGICAL
    ]
    classified, n_calls = classify_claims(claims, trace_id="t4")
    assert n_calls == 1
    assert [c.classifier_source for c in classified] == ["rule", "llm", "rule"]


def test_empty_input_no_llm_call():
    llm_client.set_mock([])
    classified, n_calls = classify_claims([], trace_id="t5")
    assert classified == [] and n_calls == 0
