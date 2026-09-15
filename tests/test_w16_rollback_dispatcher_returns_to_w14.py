"""W16 rollback RED - dispatcher returns to pre-signal_sub6 routing."""
from __future__ import annotations

from schemas.sub6_report import SubsixSourceReport
from verifier.agent import _verify_per_claim_sub6
from verifier.schemas import ClaimExtractedFields, ClaimType, ClaimVerdict, ClassifiedClaim


def _claim(text: str, claim_type: ClaimType) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_id="w16:rollback",
        claim_text=text,
        claim_type=claim_type,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(),
    )


def _task() -> SubsixSourceReport:
    return SubsixSourceReport(
        task_id="w16_rollback_dispatch",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "RAMP_P_141", "pathway_name": "Tryptophan metabolism"},
        ground_truth_signal_compounds=["C00078"],
        ground_truth_noise_compounds=[],
        differential_metabolites=[],
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_141",
                    "pathway_name": "Tryptophan metabolism",
                    "pathway_source": "kegg",
                    "pathway_external_id": "map00380",
                    "p_value": 1.5634557931188294e-16,
                    "fdr": 2.0877858435428257e-17,
                    "matched_compounds": ["C00078", "C00328", "C00463"],
                    "total_pathway_compounds": 27,
                }
            ],
        },
    )


def _dispatch_one(claim: ClassifiedClaim):
    out = _verify_per_claim_sub6(
        [claim],
        _task(),
        ramp_db_path=None,
        ramp_conn=None,
        driver_lookup=None,
    )
    assert len(out) == 1
    return out[0]


def test_signal_like_factual_claim_returns_factual_sub6_uv_not_signal_contradiction():
    result = _dispatch_one(
        _claim("MUMM:tryptophan_metabolism has p-value 8.40e-05", ClaimType.FACTUAL)
    )

    assert result.verifier_layer == "factual_sub6"
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_signal_like_grounded_claim_returns_factual_sub6_uv_not_signal_contradiction():
    result = _dispatch_one(
        _claim("MUMM:tryptophan_metabolism has p-value 8.40e-05", ClaimType.GROUNDED)
    )

    assert result.verifier_layer == "factual_sub6"
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_signal_like_other_claim_falls_through_to_verify_sub6_uv():
    result = _dispatch_one(
        _claim("MUMM:tryptophan_metabolism has p-value 8.40e-05", ClaimType.OTHER)
    )

    assert result.verifier_layer == "verify_sub6"
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0
