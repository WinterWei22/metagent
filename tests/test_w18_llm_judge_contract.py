from __future__ import annotations

import os

import pytest

from verifier.helpers.judge_response_parser import parse_judge_response
from verifier.helpers.llm_judge_prompt import build_llm_judge_prompt
from verifier.schemas import ClaimType, ClaimVerdict


def test_prompt_parser_contract_uses_runtime_verdict_labels():
    prompt = build_llm_judge_prompt(
        claim_text="MUMM:tyrosine_metabolism has p = 0.01",
        claim_type=ClaimType.GROUNDED,
        source_report_excerpt={"mummichog_enrichment_result": {"pathways": []}},
    )
    assert "SUPPORTED" in prompt
    assert "CONTRADICTED" in prompt
    assert "UNVERIFIABLE_V0" in prompt
    assert "HEDGED" in prompt
    assert "judge_strict" not in prompt
    assert "judge_uncoverable" not in prompt


def test_parser_accepts_prompt_runtime_verdict_labels():
    labels = {
        "SUPPORTED": ClaimVerdict.SUPPORTED,
        "CONTRADICTED": ClaimVerdict.CONTRADICTED,
        "UNVERIFIABLE_V0": ClaimVerdict.UNVERIFIABLE_V0,
        "HEDGED": ClaimVerdict.NEEDS_HUMAN_REVIEW,
    }
    for raw, expected in labels.items():
        parsed = parse_judge_response({
            "verdict": raw,
            "confidence": 0.9,
            "evidence_pointer": "mummichog_enrichment_result.pathways[0]",
            "rationale": "contract check",
        })
        assert parsed.verdict == expected


@pytest.mark.requires_minimax
def test_real_minimax_prompt_response_is_parseable_when_enabled(tmp_path, monkeypatch):
    if os.environ.get("METAGENT_RUN_MINIMAX_CONTRACT") != "1":
        pytest.skip("Set METAGENT_RUN_MINIMAX_CONTRACT=1 to run the real MiniMax contract test.")
    if not os.environ.get("MINIMAX_API_KEY"):
        pytest.skip("MINIMAX_API_KEY is required for the real MiniMax contract test.")

    from common import llm_client

    monkeypatch.setenv("METAGENT_LLM_LOG_PATH", str(tmp_path / "contract_llm.jsonl"))
    llm_client.set_log_path(tmp_path / "contract_llm.jsonl")
    prompt = build_llm_judge_prompt(
        claim_text="MUMM:tyrosine_metabolism has p = 0.01",
        claim_type=ClaimType.GROUNDED,
        source_report_excerpt={
            "task_id": "contract-test",
            "mummichog_enrichment_result": {
                "pathways": [
                    {"pathway_id": "MUMM:tyrosine_metabolism", "p_value": 0.01}
                ]
            },
        },
    )
    response = llm_client.chat(
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=300,
        caller="tests.w18_llm_judge_contract",
        trace_id="w18.contract.minimax",
        response_format={"type": "json_object"},
    )
    parsed = parse_judge_response(response)
    assert parsed.verdict in {
        ClaimVerdict.SUPPORTED,
        ClaimVerdict.CONTRADICTED,
        ClaimVerdict.UNVERIFIABLE_V0,
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
    }
