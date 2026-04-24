"""Unit tests for Stage 1 extractor (``verifier.claim_extractor``)."""
from __future__ import annotations

import pytest

from common import llm_client
from verifier.claim_extractor import ClaimExtractionError, extract_claims


def test_extract_happy_path():
    llm_client.set_mock([
        '[{"claim_text": "D-Gulose has C7H14O7", "subject": "D-Gulose"},'
        ' {"claim_text": "score is 0.771", "subject": null}]'
    ])
    claims = extract_claims("dummy report", trace_id="t1")
    assert len(claims) == 2
    assert claims[0].claim_text == "D-Gulose has C7H14O7"
    assert claims[0].subject == "D-Gulose"
    assert claims[1].subject is None


def test_extract_empty_list_is_legitimate_zero_claims():
    llm_client.set_mock(["[]"])
    claims = extract_claims("dummy report", trace_id="t2")
    assert claims == []


def test_extract_empty_input_short_circuits_without_llm_call():
    # No responses queued — if a call is made, IndexError would surface
    llm_client.set_mock([])
    assert extract_claims("", trace_id="t3") == []
    assert extract_claims("   \n  ", trace_id="t3b") == []


def test_extract_raises_on_unparseable_response():
    # Text must NOT end in the literal '[]' — the extractor treats that
    # suffix as a legitimate zero-claim response from the model.
    llm_client.set_mock(["I am not JSON"])
    with pytest.raises(ClaimExtractionError):
        extract_claims("dummy report", trace_id="t4")


def test_extract_raises_when_claim_text_missing():
    llm_client.set_mock(['[{"subject": "X"}]'])
    with pytest.raises(ClaimExtractionError):
        extract_claims("dummy report", trace_id="t5")


def test_extract_raises_when_item_is_not_object():
    llm_client.set_mock(['["just a string"]'])
    with pytest.raises(ClaimExtractionError):
        extract_claims("dummy report", trace_id="t6")


def test_extract_tolerates_prose_around_json_list():
    llm_client.set_mock([
        'Sure! Here are the claims: [{"claim_text": "X", "subject": "Y"}]'
    ])
    claims = extract_claims("dummy report", trace_id="t7")
    assert len(claims) == 1
    assert claims[0].claim_text == "X"


def test_extract_coerces_non_string_subject_to_none():
    llm_client.set_mock(['[{"claim_text": "X", "subject": 42}]'])
    claims = extract_claims("dummy report", trace_id="t8")
    assert claims[0].subject is None
