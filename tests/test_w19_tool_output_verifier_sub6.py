from __future__ import annotations

import importlib

from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim


def _layer():
    return importlib.import_module("verifier.layers.tool_output_sub6")


def _claim(text: str, claim_type: ClaimType = ClaimType.GROUNDED) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_id="claim-1",
        claim_text=text,
        claim_type=claim_type,
        classifier_source="rule",
    )


def _source_report() -> dict:
    return {
        "task_id": "task-1",
        "ramp_enrichment_result": {
            "top_pathways": [
                {"pathway_name": "Galactosemia", "rank": 1, "fdr": 1.65e-12}
            ]
        },
        "mummichog_enrichment_result": {
            "pathways": [
                {
                    "pathway_id": "MUMM:galactose_metabolism",
                    "pathway_name": "Galactose metabolism",
                    "rank": 0,
                    "score": 5.88e-4,
                    "score_type": "p_value",
                    "auxiliary_scores": {"overlap_size": 10, "pathway_size": 11},
                }
            ]
        },
    }


def test_supported_for_exact_tool_output_match():
    verified = _layer().verify_tool_output_sub6(
        _claim("mummichog produces a p-value of 5.88e-4"),
        _source_report(),
    )
    assert verified.verdict == ClaimVerdict.SUPPORTED
    assert verified.verifier_layer == "tool_output_sub6"
    assert verified.source_field == "mummichog_enrichment_result.pathways[0].score"


def test_contradicted_for_direct_numeric_mismatch():
    verified = _layer().verify_tool_output_sub6(
        _claim("mummichog produces a p-value of 0.99"),
        _source_report(),
    )
    assert verified.verdict == ClaimVerdict.CONTRADICTED
    assert "5.88e-04" in verified.correction or "0.000588" in verified.correction


def test_unverifiable_for_missing_carrier():
    verified = _layer().verify_tool_output_sub6(
        _claim("mummichog produces a p-value of 5.88e-4"),
        {"ramp_enrichment_result": {"top_pathways": []}},
    )
    assert verified.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_unverifiable_for_interpretive_claim():
    verified = _layer().verify_tool_output_sub6(
        _claim("Mummichog provides orthogonal empirical-compound confirmation"),
        _source_report(),
    )
    assert verified.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_unverifiable_for_multi_tool_convergence():
    verified = _layer().verify_tool_output_sub6(
        _claim("RaMP and Mummichog converged on two interconnected modules", ClaimType.BIOLOGICAL),
        _source_report(),
    )
    assert verified.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_prior_non_uv_prevents_tool_output_verification():
    prior = _layer().verify_post_uv_only(
        ClaimVerdict.SUPPORTED,
        _claim("mummichog produces a p-value of 0.99"),
        _source_report(),
    )
    assert prior.verdict == ClaimVerdict.SUPPORTED


def test_claim_type_without_tool_output_scope_stays_uv():
    verified = _layer().verify_tool_output_sub6(
        _claim("mummichog produces a p-value of 5.88e-4", ClaimType.DRIVER_METABOLITE),
        _source_report(),
    )
    assert verified.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_does_not_introduce_new_claim_verdict_values():
    verdicts = {member.name for member in ClaimVerdict}
    assert "TOOL_HEDGED" not in verdicts
    assert "PARTIAL_SUPPORTED" not in verdicts
