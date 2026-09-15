"""W16 D2 RED - signal_sub6 verifier layer."""
from __future__ import annotations

import pytest

from schemas.sub6_report import SubsixSourceReport
from verifier.schemas import ClaimExtractedFields, ClaimType, ClaimVerdict, ClassifiedClaim


def _verify_signal_sub6(claim: ClassifiedClaim, task: SubsixSourceReport):
    try:
        from verifier.layers.signal_sub6 import verify_signal_sub6
    except ImportError as exc:
        pytest.fail(f"signal_sub6 layer not implemented: {exc}")
    return verify_signal_sub6(claim, task)


def _claim(text: str, *, claim_type: ClaimType = ClaimType.GROUNDED) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_id="w16:c1",
        claim_text=text,
        claim_type=claim_type,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(),
    )


def _task() -> SubsixSourceReport:
    return SubsixSourceReport(
        task_id="w16_signal_layer",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "RAMP_P_1", "pathway_name": "Tyrosine metabolism"},
        ground_truth_signal_compounds=["C00082"],
        ground_truth_noise_compounds=[],
        differential_metabolites=[],
        ramp_enrichment_result={
            "top_pathways": [
                {
                    "pathway_id": "RAMP_P_1",
                    "pathway_name": "Tyrosine metabolism",
                    "pathway_source": "kegg",
                    "pathway_external_id": "map00350",
                    "p_value": 8.40e-5,
                    "fdr": 1.12e-9,
                    "matched_compounds": ["C00082", "C00400", "C00079", "C00166", "C00355"],
                    "total_pathway_compounds": 27,
                }
            ],
        },
    )


def test_signal_sub6_supports_exact_p_value_lookup():
    result = _verify_signal_sub6(
        _claim("Mummichog m/z-direct activity for Tyrosine metabolism has p-value 8.40e-5"),
        _task(),
    )
    assert result.verdict == ClaimVerdict.SUPPORTED
    assert result.verifier_layer == "signal_sub6"
    assert result.tool_called == "ramp_enrichment_result"
    assert result.enrichment_context is not None
    assert result.enrichment_context.tool_evidence["metric"] == "p_value"
    assert result.enrichment_context.tool_evidence["actual_value"] == 8.40e-5


def test_signal_sub6_supports_threshold_lookup():
    result = _verify_signal_sub6(
        _claim("Tyrosine metabolism has FDR < 1e-8"),
        _task(),
    )
    assert result.verdict == ClaimVerdict.SUPPORTED


def test_signal_sub6_contradicts_wrong_numeric_value():
    result = _verify_signal_sub6(
        _claim("Tyrosine metabolism has p-value 0.05"),
        _task(),
    )
    assert result.verdict == ClaimVerdict.CONTRADICTED
    assert result.correction == "8.4e-05"


def test_signal_sub6_unverifiable_when_no_signal_mention():
    result = _verify_signal_sub6(
        _claim("Tyrosine metabolism is strongly enriched"),
        _task(),
    )
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert result.verifier_layer == "signal_sub6"


def test_signal_sub6_unverifiable_when_lookup_misses():
    result = _verify_signal_sub6(
        _claim("Missing pathway has p-value 0.05"),
        _task(),
    )
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_signal_sub6_does_not_treat_formula_as_signal():
    result = _verify_signal_sub6(
        _claim("N-carbamoyl-beta-alanine has molecular formula C4H8N2O3"),
        _task(),
    )
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_signal_sub6_supports_overlap_count_lookup():
    result = _verify_signal_sub6(
        _claim("Five metabolites overlapped the 27-member roster of Tyrosine metabolism"),
        _task(),
    )
    assert result.verdict == ClaimVerdict.SUPPORTED
    assert result.enrichment_context.tool_evidence["metric"] == "overlap_count"
