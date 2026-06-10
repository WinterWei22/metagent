from __future__ import annotations

import importlib

from verifier.schemas import ClaimType


def _prompt_module():
    return importlib.import_module("verifier.helpers.llm_judge_prompt")


def test_prompt_contains_claim_text_source_excerpt_and_rubric():
    mod = _prompt_module()
    prompt = mod.build_llm_judge_prompt(
        claim_text="MUMM:tyrosine_metabolism has p = 0.01",
        claim_type=ClaimType.GROUNDED,
        source_report_excerpt={"mummichog_enrichment_result": {"pathways": []}},
    )
    assert "MUMM:tyrosine_metabolism has p = 0.01" in prompt
    assert "mummichog_enrichment_result" in prompt
    assert "SUPPORTED" in prompt


def test_prompt_uses_runtime_verdict_labels_not_audit_labels():
    mod = _prompt_module()
    prompt = mod.build_llm_judge_prompt(
        claim_text="Mummichog ranks tyrosine metabolism first",
        claim_type=ClaimType.GROUNDED,
        source_report_excerpt={"mummichog_enrichment_result": {"pathways": []}},
    )
    assert "SUPPORTED" in prompt
    assert "CONTRADICTED" in prompt
    assert "UNVERIFIABLE_V0" in prompt
    assert "HEDGED" in prompt
    assert "judge_strict" not in prompt
    assert "judge_uncoverable" not in prompt


def test_prompt_uses_medium_scope_enum_member_names():
    mod = _prompt_module()
    prompt = mod.build_llm_judge_prompt(
        claim_text="Tyrosine metabolism is enriched",
        claim_type=ClaimType.BIOLOGICAL,
        source_report_excerpt={},
    )
    assert "GROUNDED" in prompt
    assert "BIOLOGICAL" in prompt
    assert "FACTUAL" in prompt


def test_prompt_contains_v4_edge_case_rules():
    mod = _prompt_module()
    prompt = mod.build_llm_judge_prompt(
        claim_text="Reactome hits are present",
        claim_type=ClaimType.GROUNDED,
        source_report_excerpt={},
    )
    assert "EDGE-1" in prompt
    assert "Reactome" in prompt
    assert "Identifier-as-content" in prompt
    assert "Mummichog rank" in prompt


def test_source_report_excerpt_is_bounded_for_token_budget():
    mod = _prompt_module()
    excerpt = mod.build_source_report_excerpt({"large": "x" * 100_000}, max_chars=12_000)
    assert len(excerpt) <= 12_000
