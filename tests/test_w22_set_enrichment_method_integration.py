from __future__ import annotations

from schemas.sub6_report import SubsixSourceReport
from verifier.layers.set_enrichment import verify_set_enrichment
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
)


def _claim(
    text: str,
    *,
    evidence_method: str | None = None,
    pathway_id: str | None = None,
    rank: int | None = None,
    score_value: float | None = None,
) -> ClassifiedClaim:
    fields = ClaimExtractedFields(
        pathway_id=pathway_id,
        rank=rank,
        score_value=score_value,
    )
    if evidence_method is not None:
        fields.evidence_method = evidence_method
    return ClassifiedClaim(
        claim_text=text,
        claim_type=ClaimType.SET_ENRICHMENT,
        classifier_source="rule",
        extracted_fields=fields,
    )


def _report() -> SubsixSourceReport:
    return SubsixSourceReport(
        task_id="w22_layer_spike",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "RAMP_P_000000106"},
        ground_truth_signal_compounds=[],
        ground_truth_noise_compounds=[],
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_000000999",
                    "pathway_name": "Wrong RaMP pathway",
                    "pathway_external_id": "map99999",
                    "fdr": 1e-9,
                }
            ]
        },
        mummichog_enrichment_result={
            "pathways": [
                {
                    "pathway_id": "MUMM:tyrosine_metabolism",
                    "pathway_name": "Tyrosine metabolism",
                    "rank": 0,
                    "score": 2.52e-4,
                }
            ]
        },
    )


def test_explicit_method_keeps_legacy_ramp_behavior_when_flag_off() -> None:
    result = verify_set_enrichment(
        _claim(
            "Mummichog returns MUMM:tyrosine_metabolism at rank 1 with p=2.52e-04.",
            evidence_method="mummichog",
            pathway_id="MUMM:tyrosine_metabolism",
            rank=1,
            score_value=2.52e-4,
        ),
        _report(),
    )

    assert result.verdict == ClaimVerdict.CONTRADICTED
    assert result.verifier_layer == "set_enrichment"


def test_explicit_method_routes_to_method_aware_layer_when_flag_on(monkeypatch) -> None:
    monkeypatch.setenv("METAGENT_ENABLE_METHOD_AWARE_ENRICHMENT", "1")
    result = verify_set_enrichment(
        _claim(
            "Mummichog returns MUMM:tyrosine_metabolism at rank 1 with p=2.52e-04.",
            evidence_method="mummichog",
            pathway_id="MUMM:tyrosine_metabolism",
            rank=1,
            score_value=2.52e-4,
        ),
        _report(),
    )

    assert result.verdict == ClaimVerdict.SUPPORTED
    assert result.verifier_layer == "method_aware_enrichment"
    assert result.tool_called == "mummichog_enrichment_result"


def test_no_method_keeps_legacy_ramp_behavior() -> None:
    result = verify_set_enrichment(
        _claim("These metabolites are enriched in Wrong RaMP pathway."),
        _report(),
    )

    assert result.verdict == ClaimVerdict.SUPPORTED
    assert result.verifier_layer == "set_enrichment"
    assert result.tool_called == "ramp_enrichment_result"
