from __future__ import annotations

import importlib

from verifier.schemas import ClaimVerdict


def _parser_module():
    return importlib.import_module("verifier.helpers.judge_response_parser")


def test_valid_json_response_parses_verdict_confidence_and_pointer():
    mod = _parser_module()
    parsed = mod.parse_judge_response('{"verdict":"SUPPORTED","confidence":0.91,"evidence_pointer":"ramp_enrichment_result.top_pathways[0]","rationale":"match"}')
    assert parsed.verdict == ClaimVerdict.SUPPORTED
    assert parsed.confidence == 0.91
    assert parsed.evidence_pointer == "ramp_enrichment_result.top_pathways[0]"


def test_missing_required_fields_falls_back_to_uv():
    mod = _parser_module()
    parsed = mod.parse_judge_response('{"verdict":"SUPPORTED"}')
    assert parsed.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_confidence_boundary_values_are_normalized():
    mod = _parser_module()
    assert mod.confidence_bucket(0.49) == "uv"
    assert mod.confidence_bucket(0.50) == "hedged"
    assert mod.confidence_bucket(0.85) == "strong"
    assert mod.confidence_bucket(0.90) == "contradicted_strong"


def test_evidence_pointer_field_is_preserved_for_validator():
    mod = _parser_module()
    parsed = mod.parse_judge_response({"verdict": "CONTRADICTED", "confidence": 0.92, "evidence_pointer": "mummichog_enrichment_result.pathways[0].p_value", "rationale": "mismatch"})
    assert parsed.evidence_pointer == "mummichog_enrichment_result.pathways[0].p_value"


def test_think_block_prefix_is_stripped_before_json_parse():
    mod = _parser_module()
    parsed = mod.parse_judge_response(
        '<think>reasoning that MiniMax may emit</think>\n'
        '{"verdict":"SUPPORTED","confidence":0.91,'
        '"evidence_pointer":"mummichog_enrichment_result.pathways[0]",'
        '"rationale":"carrier supports claim"}'
    )
    assert parsed.verdict == ClaimVerdict.SUPPORTED
    assert parsed.confidence == 0.91


def test_unclosed_think_prefix_still_extracts_first_json_object():
    mod = _parser_module()
    parsed = mod.parse_judge_response(
        '<think>reasoning was truncated before the closing tag '
        '{"verdict":"CONTRADICTED","confidence":0.94,'
        '"evidence_pointer":"mummichog_enrichment_result.pathways[0].p_value",'
        '"rationale":"claim mismatches p-value"}'
    )
    assert parsed.verdict == ClaimVerdict.CONTRADICTED


def test_fenced_json_response_is_accepted():
    mod = _parser_module()
    parsed = mod.parse_judge_response(
        '```json\n'
        '{"verdict":"UNVERIFIABLE_V0","confidence":0.95,'
        '"evidence_pointer":"source_report_excerpt",'
        '"rationale":"required evidence absent"}\n'
        '```'
    )
    assert parsed.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert parsed.confidence == 0.95


def test_prose_wrapped_json_response_is_accepted():
    mod = _parser_module()
    parsed = mod.parse_judge_response(
        'Here is my answer: '
        '{"verdict":"HEDGED","confidence":0.72,'
        '"evidence_pointer":"ramp_enrichment_result.top_pathways[0]",'
        '"rationale":"partial source support"}'
    )
    assert parsed.verdict == ClaimVerdict.NEEDS_HUMAN_REVIEW


def test_plain_prose_without_json_still_falls_back_to_uv():
    mod = _parser_module()
    parsed = mod.parse_judge_response("The claim is probably supported, but no JSON follows.")
    assert parsed.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_unknown_verdict_label_still_falls_back_to_uv():
    mod = _parser_module()
    parsed = mod.parse_judge_response(
        '{"verdict":"judge_strict","confidence":0.91,'
        '"evidence_pointer":"x","rationale":"old audit label"}'
    )
    assert parsed.verdict == ClaimVerdict.UNVERIFIABLE_V0
