from __future__ import annotations

import importlib

from verifier.schemas import ClaimType, ClaimVerdict


def _layer():
    return importlib.import_module("verifier.layers.llm_judge_sub6")


def test_supported_high_confidence_returns_supported_layer_verdict():
    layer = _layer()
    verdict = layer.verify_llm_judge_sub6(
        claim={"claim_text": "MUMM:tyrosine_metabolism has p = 0.01", "claim_type": ClaimType.GROUNDED},
        source_report={"mummichog_enrichment_result": {"pathways": [{"pathway_id": "MUMM:tyrosine_metabolism", "p_value": 0.01}]}},
        judge_call=lambda *_args, **_kwargs: {"verdict": "SUPPORTED", "confidence": 0.91, "evidence_pointer": "mummichog_enrichment_result.pathways[0].p_value", "rationale": "matches p-value"},
    )
    assert verdict.verdict == ClaimVerdict.SUPPORTED
    assert verdict.verifier_layer == "llm_judge_sub6"


def test_contradicted_high_confidence_with_valid_pointer_returns_contradicted():
    layer = _layer()
    verdict = layer.verify_llm_judge_sub6(
        claim={"claim_text": "MUMM:tyrosine_metabolism has p = 0.02", "claim_type": ClaimType.GROUNDED},
        source_report={"mummichog_enrichment_result": {"pathways": [{"pathway_id": "MUMM:tyrosine_metabolism", "p_value": 0.01}]}},
        judge_call=lambda *_args, **_kwargs: {"verdict": "CONTRADICTED", "confidence": 0.94, "evidence_pointer": "mummichog_enrichment_result.pathways[0].p_value", "rationale": "claim says 0.02 but carrier says 0.01"},
    )
    assert verdict.verdict == ClaimVerdict.CONTRADICTED


def test_contradicted_high_confidence_with_invalid_pointer_degrades_to_hedged():
    layer = _layer()
    verdict = layer.verify_llm_judge_sub6(
        claim={"claim_text": "MUMM:tyrosine_metabolism has p = 0.02", "claim_type": ClaimType.GROUNDED},
        source_report={"mummichog_enrichment_result": {"pathways": []}},
        judge_call=lambda *_args, **_kwargs: {"verdict": "CONTRADICTED", "confidence": 0.95, "evidence_pointer": "mummichog_enrichment_result.pathways[99].p_value", "rationale": "missing pointer"},
    )
    assert verdict.verdict == ClaimVerdict.NEEDS_HUMAN_REVIEW


def test_mid_confidence_supported_returns_hedged_with_feedback_hint():
    layer = _layer()
    verdict = layer.verify_llm_judge_sub6(
        claim={"claim_text": "Tyrosine metabolism is a hit", "claim_type": ClaimType.BIOLOGICAL},
        source_report={},
        judge_call=lambda *_args, **_kwargs: {"verdict": "SUPPORTED", "confidence": 0.72, "evidence_pointer": "ramp_enrichment_result.top_pathways[0]", "rationale": "weak match"},
    )
    assert verdict.verdict == ClaimVerdict.NEEDS_HUMAN_REVIEW
    assert verdict.feedback_hint


def test_low_confidence_returns_unverifiable():
    layer = _layer()
    verdict = layer.verify_llm_judge_sub6(
        claim={"claim_text": "Tyrosine metabolism is a hit", "claim_type": ClaimType.BIOLOGICAL},
        source_report={},
        judge_call=lambda *_args, **_kwargs: {"verdict": "SUPPORTED", "confidence": 0.49, "evidence_pointer": "", "rationale": "too uncertain"},
    )
    assert verdict.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_ineligible_claim_type_returns_uv_without_calling_judge():
    layer = _layer()
    calls = []
    verdict = layer.verify_llm_judge_sub6(
        claim={"claim_text": "driver metabolite claim", "claim_type": ClaimType.DRIVER_METABOLITE},
        source_report={},
        judge_call=lambda *_args, **_kwargs: calls.append("called"),
    )
    assert verdict.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert calls == []


def test_cost_cap_exceeded_returns_uv_without_calling_judge():
    layer = _layer()
    calls = []
    verdict = layer.verify_llm_judge_sub6(
        claim={"claim_text": "MUMM:tyrosine_metabolism has p = 0.01", "claim_type": ClaimType.GROUNDED},
        source_report={},
        judge_call=lambda *_args, **_kwargs: calls.append("called"),
        cost_tracker=layer.JudgeCostTracker(cap_usd=2.0, spent_usd=2.0),
    )
    assert verdict.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert calls == []


def test_successful_judge_call_records_estimated_cost():
    layer = _layer()
    tracker = layer.JudgeCostTracker(cap_usd=2.0, spent_usd=0.0)
    layer.verify_llm_judge_sub6(
        claim={"claim_text": "MUMM:tyrosine_metabolism has p = 0.01", "claim_type": ClaimType.GROUNDED},
        source_report={"mummichog_enrichment_result": {"pathways": [{"pathway_id": "MUMM:tyrosine_metabolism", "p_value": 0.01}]}},
        judge_call=lambda *_args, **_kwargs: {"verdict": "SUPPORTED", "confidence": 0.91, "evidence_pointer": "mummichog_enrichment_result.pathways[0].p_value", "rationale": "matches p-value"},
        cost_tracker=tracker,
    )
    assert tracker.spent_usd > 0.0


def test_successful_judge_call_writes_trace(tmp_path):
    layer = _layer()
    trace_path = tmp_path / "judge_trace.jsonl"

    verdict = layer.verify_llm_judge_sub6(
        claim={
            "claim_id": "claim-1",
            "claim_text": "MUMM:tyrosine_metabolism has p = 0.01",
            "claim_type": ClaimType.GROUNDED,
        },
        source_report={"task_id": "task-1"},
        judge_call=lambda *_args, **_kwargs: {
            "verdict": "SUPPORTED",
            "confidence": 0.91,
            "evidence_pointer": "mummichog_enrichment_result.pathways[0].p_value",
            "rationale": "matches p-value",
        },
        trace_path=trace_path,
        iteration=1,
    )

    import json

    row = json.loads(trace_path.read_text(encoding="utf-8").strip())
    assert verdict.verdict == ClaimVerdict.SUPPORTED
    assert row["task_id"] == "task-1"
    assert row["iteration"] == 1
    assert row["claim_id"] == "claim-1"
    assert row["verdict"] == "SUPPORTED"
    assert row["parser_success"] is True
    assert row["cost_usd"] > 0.0


def test_malformed_judge_response_returns_uv():
    layer = _layer()
    verdict = layer.verify_llm_judge_sub6(
        claim={"claim_text": "MUMM:tyrosine_metabolism has p = 0.01", "claim_type": ClaimType.GROUNDED},
        source_report={},
        judge_call=lambda *_args, **_kwargs: "not-json",
    )
    assert verdict.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_successful_paths_stamp_layer_label():
    layer = _layer()
    verdict = layer.verify_llm_judge_sub6(
        claim={"claim_text": "MUMM:tyrosine_metabolism has p = 0.01", "claim_type": ClaimType.GROUNDED},
        source_report={"mummichog_enrichment_result": {"pathways": [{"pathway_id": "MUMM:tyrosine_metabolism", "p_value": 0.01}]}},
        judge_call=lambda *_args, **_kwargs: {"verdict": "SUPPORTED", "confidence": 0.9, "evidence_pointer": "mummichog_enrichment_result.pathways[0].p_value", "rationale": "match"},
    )
    assert verdict.verifier_layer == "llm_judge_sub6"


def test_quality_scores_match_verdict_policy():
    layer = _layer()
    assert layer.quality_score_for_verdict(ClaimVerdict.SUPPORTED) == 1.0
    assert layer.quality_score_for_verdict(ClaimVerdict.NEEDS_HUMAN_REVIEW) == 0.6
    assert layer.quality_score_for_verdict(ClaimVerdict.CONTRADICTED) == 0.0
    assert layer.quality_score_for_verdict(ClaimVerdict.UNVERIFIABLE_V0) == 0.0
