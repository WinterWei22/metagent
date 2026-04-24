"""Unit tests for Layer D — consistency sweep (Type 4)."""
from __future__ import annotations

from common import llm_client
from verifier.layers.consistency import detect_consistency_contradictions
from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim


def _cc(text):
    return ClassifiedClaim(
        claim_text=text, subject=None,
        claim_type=ClaimType.GROUNDED, classifier_source="rule",
    )


def test_contradiction_pair_surfaced_as_consistency_claim():
    claims = [
        _cc("D-Gulose has molecular formula C7H14O7"),
        _cc("D-Gulose maps to galactose metabolism"),
        _cc("Glucose has molecular formula C6H12O6"),
        _cc("Gulose refers to C6H12O6 hexose form"),
    ]
    llm_client.set_mock([
        '[{"claim_indices": [0, 3], "reason": "D-Gulose given two formulas"}]'
    ])
    contradictions, n_calls, warns = detect_consistency_contradictions(
        claims, trace_id="t1",
    )
    assert n_calls == 1
    assert warns == []
    assert len(contradictions) == 1
    c = contradictions[0]
    assert c.claim_type == ClaimType.CONSISTENCY
    assert c.verdict == ClaimVerdict.CONTRADICTED
    assert "[0]" in c.claim_text and "[3]" in c.claim_text


def test_empty_list_is_legitimate_no_contradictions():
    claims = [_cc("claim A"), _cc("claim B")]
    llm_client.set_mock(["[]"])
    contradictions, n_calls, warns = detect_consistency_contradictions(
        claims, trace_id="t2",
    )
    assert n_calls == 1 and contradictions == [] and warns == []


def test_skip_when_fewer_than_two_claims():
    llm_client.set_mock([])  # would IndexError if called
    contradictions, n_calls, warns = detect_consistency_contradictions(
        [_cc("only one")], trace_id="t3",
    )
    assert n_calls == 0 and contradictions == [] and warns == []


def test_parse_failure_emits_warning_without_contradictions():
    claims = [_cc("A"), _cc("B")]
    llm_client.set_mock(["I am not JSON"])
    contradictions, n_calls, warns = detect_consistency_contradictions(
        claims, trace_id="t4",
    )
    assert n_calls == 1
    assert contradictions == []
    assert len(warns) == 1
    assert "VERIFICATION_PARSE_FAILED" in warns[0]


def test_out_of_range_index_is_skipped():
    claims = [_cc("A"), _cc("B"), _cc("C")]
    llm_client.set_mock([
        '[{"claim_indices": [0, 99], "reason": "bogus"},'
        ' {"claim_indices": [1, 2], "reason": "valid"}]'
    ])
    contradictions, n_calls, warns = detect_consistency_contradictions(
        claims, trace_id="t5",
    )
    assert n_calls == 1
    assert len(contradictions) == 1
    assert len(warns) == 1  # the bogus one logged


def test_single_index_item_is_skipped():
    claims = [_cc("A"), _cc("B")]
    llm_client.set_mock([
        '[{"claim_indices": [0], "reason": "self?"}]'
    ])
    contradictions, n_calls, warns = detect_consistency_contradictions(
        claims, trace_id="t6",
    )
    assert contradictions == []
    assert len(warns) == 1
