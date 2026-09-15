"""W16 D2 RED - Sub-6 dispatcher catch-all for signal_sub6."""
from __future__ import annotations

import pytest

from schemas.sub6_report import SubsixSourceReport
from verifier.agent import _verify_per_claim_sub6
from verifier.schemas import ClaimExtractedFields, ClaimType, ClaimVerdict, ClassifiedClaim


_DISPATCHER_DISABLED_REASON = (
    "W16 dispatcher disabled 2026-06-08 pending W18 beta rebuild; "
    "see reports/agent/w16_signal_sub6_d4_diagnostic.md"
)


def _claim(text: str, claim_type: ClaimType) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_id="w16:dispatch",
        claim_text=text,
        claim_type=claim_type,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(),
    )


def _task() -> SubsixSourceReport:
    return SubsixSourceReport(
        task_id="w16_signal_dispatch",
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


@pytest.mark.skip(reason=_DISPATCHER_DISABLED_REASON)
def test_dispatcher_routes_signal_like_grounded_claim_to_signal_sub6():
    result = _dispatch_one(_claim("Tyrosine metabolism has p-value 8.40e-5", ClaimType.GROUNDED))
    assert result.verifier_layer == "signal_sub6"
    assert result.verdict == ClaimVerdict.SUPPORTED


@pytest.mark.skip(reason=_DISPATCHER_DISABLED_REASON)
def test_dispatcher_routes_signal_like_factual_claim_to_signal_sub6_after_factual_sub6_miss():
    result = _dispatch_one(_claim("Tyrosine metabolism has FDR < 1e-8", ClaimType.FACTUAL))
    assert result.verifier_layer == "signal_sub6"
    assert result.verdict == ClaimVerdict.SUPPORTED


@pytest.mark.skip(reason=_DISPATCHER_DISABLED_REASON)
def test_dispatcher_routes_signal_like_other_claim_to_signal_sub6_before_fallback():
    result = _dispatch_one(_claim("Tyrosine metabolism has p-value 8.40e-5", ClaimType.OTHER))
    assert result.verifier_layer == "signal_sub6"
    assert result.verdict == ClaimVerdict.SUPPORTED


def test_dispatcher_preserves_factual_sub6_for_identifier_claims():
    result = _dispatch_one(_claim("L-tyrosine has KEGG ID C00082", ClaimType.FACTUAL))
    assert result.verifier_layer == "factual_sub6"
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_dispatcher_preserves_non_signal_other_fallback():
    result = _dispatch_one(_claim("Tyrosine metabolism is biologically relevant", ClaimType.OTHER))
    assert result.verifier_layer == "verify_sub6"
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0
