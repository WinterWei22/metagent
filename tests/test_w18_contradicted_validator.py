from __future__ import annotations

import importlib


def _validator_module():
    return importlib.import_module("verifier.helpers.contradicted_validator")


def test_valid_evidence_pointer_with_existing_carrier_field_passes():
    mod = _validator_module()
    assert mod.validate_contradicted_pointer(
        source_report={"mummichog_enrichment_result": {"pathways": [{"p_value": 0.01}]}},
        evidence_pointer="mummichog_enrichment_result.pathways[0].p_value",
        rationale="claim says 0.02 but carrier says 0.01",
    ) is True


def test_pointer_to_missing_carrier_field_fails():
    mod = _validator_module()
    assert mod.validate_contradicted_pointer(
        source_report={"mummichog_enrichment_result": {"pathways": []}},
        evidence_pointer="mummichog_enrichment_result.pathways[0].p_value",
        rationale="claim says 0.02 but carrier says 0.01",
    ) is False


def test_contradiction_requires_specific_value_mismatch_in_rationale():
    mod = _validator_module()
    assert mod.validate_contradicted_pointer(
        source_report={"mummichog_enrichment_result": {"pathways": [{"p_value": 0.01}]}},
        evidence_pointer="mummichog_enrichment_result.pathways[0].p_value",
        rationale="this seems wrong",
    ) is False
