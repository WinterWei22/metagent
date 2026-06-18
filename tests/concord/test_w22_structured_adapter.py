from __future__ import annotations

import json

from concord.agent.react_runner import ConcordReactResult
from concord.agent.verifier_adapter import (
    concord_result_to_b1_narrative,
    concord_result_to_b1_structured_payload,
)
from verifier.agent import _extract_classify


def _result() -> ConcordReactResult:
    return ConcordReactResult(
        task_id="w22_adapter_spike",
        final_narrative_text="Tyrosine metabolism is supported by the tool output.",
        final_claims=[
            {
                "claim_type": "PATHWAY_ENRICHMENT",
                "claim_text": "run_mummichog ranks MUMM:tyrosine_metabolism at rank 1 with p_value 0.000252.",
                "pathway_id": "MUMM:tyrosine_metabolism",
                "pathway_name": "Tyrosine metabolism",
                "rank": 1,
                "score": 0.000252,
                "score_type": "p_value",
                "evidence_method": "mummichog",
            },
            {
                "claim_type": "PATHWAY_MEMBERSHIP",
                "claim_text": "Tyrosine is a member of Tyrosine metabolism.",
                "compound_name": "Tyrosine",
                "pathway_name": "Tyrosine metabolism",
            },
            {
                "claim_type": "DRIVER_METABOLITE",
                "claim_text": "Tyrosine drives Tyrosine metabolism.",
                "compound_name": "Tyrosine",
                "pathway_name": "Tyrosine metabolism",
                "signal_compound_ids": ["C00082"],
            },
            {
                "claim_type": "METABOLITE_PATHWAY_LINK",
                "claim_text": "Tyrosine participates in Tyrosine metabolism via R00001.",
                "compound_name": "Tyrosine",
                "pathway_name": "Tyrosine metabolism",
                "enzyme_or_reaction": "R00001",
            },
        ],
    )


def test_legacy_narrative_adapter_is_unchanged() -> None:
    result = _result()

    assert concord_result_to_b1_narrative(result, {}) == result.final_narrative_text


def test_structured_payload_adapter_includes_narrative_and_claims() -> None:
    payload = concord_result_to_b1_structured_payload(_result(), {})
    parsed = json.loads(payload)

    assert parsed["narrative_text"] == "Tyrosine metabolism is supported by the tool output."
    assert parsed["claims"][0]["claim_text"].startswith("run_mummichog")
    assert parsed["claims"][0]["grammar"] == "pathway_enrichment"
    assert parsed["claims"][0]["term_id"] == "MUMM:tyrosine_metabolism"
    assert parsed["claims"][0]["evidence_method"] == "mummichog"
    assert parsed["claims"][0]["rank"] == 1
    assert [claim["grammar"] for claim in parsed["claims"]] == [
        "pathway_enrichment",
        "pathway_membership",
        "driver_metabolite",
        "metabolite_pathway_link",
    ]


def test_structured_payload_preserves_zero_llm_json_extract_path() -> None:
    payload = concord_result_to_b1_structured_payload(_result(), {})
    classified, llm_calls, _warnings, _dropped = _extract_classify(
        payload,
        trace_id="w22.structured_adapter.zero_llm",
    )

    assert llm_calls == 0
    assert classified is not None
    assert len(classified) == 4
