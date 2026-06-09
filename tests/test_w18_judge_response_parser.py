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
