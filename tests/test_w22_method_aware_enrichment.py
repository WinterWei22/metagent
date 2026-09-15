from __future__ import annotations

from schemas.sub6_report import SubsixSourceReport
from verifier.helpers.method_aware_enrichment import verify_method_aware_enrichment
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
)


def _claim(
    text: str,
    *,
    pathway_id: str | None = None,
    pathway_name: str | None = None,
    evidence_method: str | None = None,
    rank: int | None = None,
    score_value: float | None = None,
) -> ClassifiedClaim:
    fields = ClaimExtractedFields(
        pathway_id=pathway_id,
        pathway_name=pathway_name,
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


def _source_report() -> SubsixSourceReport:
    return SubsixSourceReport(
        task_id="w22_method_spike",
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
                    "pathway_id_native": "Tyrosine metabolism",
                    "pathway_name": "Tyrosine metabolism",
                    "rank": 0,
                    "score": 2.52e-4,
                    "score_type": "p_value",
                }
            ]
        },
        metaboanalystr_enrichment_result={
            "psea": {
                "pathways": [
                    {
                        "pathway_id": "KEGG:hsa00260",
                        "pathway_id_native": "hsa00260",
                        "pathway_name": "hsa00260",
                        "rank": 1,
                        "score": 3.3281e-7,
                        "score_type": "p_value",
                    }
                ]
            }
        },
    )


def test_mummichog_method_reads_mummichog_carrier_not_ramp() -> None:
    result = verify_method_aware_enrichment(
        _claim(
            "Mummichog returns MUMM:tyrosine_metabolism at rank 1 with p=2.52e-04.",
            pathway_id="MUMM:tyrosine_metabolism",
            evidence_method="mummichog",
            rank=1,
            score_value=2.52e-4,
        ),
        _source_report(),
    )

    assert result.verdict == ClaimVerdict.SUPPORTED
    assert result.tool_called == "mummichog_enrichment_result"
    assert result.source_field == "mummichog_enrichment_result.pathways[0]"


def test_missing_method_carrier_returns_uv_without_ramp_fallback() -> None:
    report = _source_report().model_copy(update={"mummichog_enrichment_result": None})
    result = verify_method_aware_enrichment(
        _claim(
            "Mummichog returns MUMM:tyrosine_metabolism at rank 1.",
            pathway_id="MUMM:tyrosine_metabolism",
            evidence_method="mummichog",
        ),
        report,
    )

    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert "not populated" in result.evidence
    assert result.tool_called == "mummichog_enrichment_result"


def test_no_method_returns_none_so_legacy_ramp_layer_can_handle_claim() -> None:
    assert (
        verify_method_aware_enrichment(
            _claim("These metabolites are enriched in Tyrosine metabolism."),
            _source_report(),
        )
        is None
    )


def test_namespace_equivalent_ids_require_rank_and_score_match() -> None:
    supported = verify_method_aware_enrichment(
        _claim(
            "MetaboAnalystR PSEA ranks KEGG:map00260 at rank 2 with p_value 3.3281e-07.",
            pathway_id="KEGG:map00260",
            evidence_method="metaboanalystr",
            rank=2,
            score_value=3.3281e-7,
        ),
        _source_report(),
    )
    contradicted = verify_method_aware_enrichment(
        _claim(
            "MetaboAnalystR PSEA ranks KEGG:map00260 at rank 1 with p_value 0.2.",
            pathway_id="KEGG:map00260",
            evidence_method="metaboanalystr",
            rank=1,
            score_value=0.2,
        ),
        _source_report(),
    )

    assert supported is not None
    assert supported.verdict == ClaimVerdict.SUPPORTED
    assert contradicted is not None
    assert contradicted.verdict == ClaimVerdict.CONTRADICTED

