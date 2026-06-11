"""Tests for claim-level verifier metrics."""
from __future__ import annotations

from verifier.metrics import compute_claim_metrics
from verifier.schemas import ClaimSubtype, ClaimType, ClaimVerdict, VerifiedClaim


def _vc(verdict, *, ctype=ClaimType.GROUNDED, subtype=ClaimSubtype.UNKNOWN, tool=None):
    return VerifiedClaim(
        claim_text=f"{ctype.value}:{verdict.value}",
        claim_type=ctype,
        claim_subtype=subtype,
        verdict=verdict,
        evidence="ev",
        tool_called=tool,
    )


def test_mixed_verdict_metrics_use_claims_v2():
    claims_v1 = [_vc(ClaimVerdict.CONTRADICTED)]
    claims_v2 = [
        _vc(ClaimVerdict.SUPPORTED, subtype=ClaimSubtype.FORMULA),
        _vc(ClaimVerdict.CONTRADICTED, subtype=ClaimSubtype.FORMULA),
        _vc(ClaimVerdict.UNSUPPORTED, ctype=ClaimType.BIOLOGICAL),
        _vc(ClaimVerdict.UNVERIFIABLE_V0, ctype=ClaimType.FACTUAL, tool="classyfire"),
        _vc(ClaimVerdict.ERROR, ctype=ClaimType.LITERATURE, tool="literature_search"),
    ]

    metrics = compute_claim_metrics(claims_v1=claims_v1, claims_v2=claims_v2)

    assert metrics.total_claims == 5
    assert metrics.supported_claims == 1
    assert metrics.contradicted_claims == 1
    assert metrics.unsupported_claims == 1
    assert metrics.unverifiable_claims == 1
    assert metrics.error_claims == 1
    assert metrics.supported_ratio == 0.2
    assert metrics.contradiction_rate == 0.2
    assert metrics.unverifiable_rate == 0.2
    assert metrics.claim_precision == 1 / 3
    assert metrics.per_type_verdict_counts["grounded_claim"]["supported"] == 1
    assert metrics.per_type_verdict_counts["biological_claim"]["unsupported"] == 1
    assert metrics.per_subtype_verdict_counts["formula"]["supported"] == 1
    assert metrics.tool_call_counts == {
        "classyfire": 1,
        "literature_search": 1,
    }


def test_metrics_fallback_to_v1_when_v2_empty():
    metrics = compute_claim_metrics(
        claims_v1=[_vc(ClaimVerdict.SUPPORTED)],
        claims_v2=[],
    )
    assert metrics.total_claims == 1
    assert metrics.supported_claims == 1


def test_all_supported_confidence_is_one():
    metrics = compute_claim_metrics(
        claims_v1=[],
        claims_v2=[_vc(ClaimVerdict.SUPPORTED), _vc(ClaimVerdict.SUPPORTED)],
    )
    assert metrics.verification_confidence == 1.0
    assert metrics.confidence_components["claim_precision"] == 1.0


def test_contradiction_lowers_confidence():
    clean = compute_claim_metrics(
        claims_v1=[],
        claims_v2=[_vc(ClaimVerdict.SUPPORTED), _vc(ClaimVerdict.SUPPORTED)],
    )
    mixed = compute_claim_metrics(
        claims_v1=[],
        claims_v2=[_vc(ClaimVerdict.SUPPORTED), _vc(ClaimVerdict.CONTRADICTED)],
    )
    assert mixed.verification_confidence < clean.verification_confidence


def test_all_unverifiable_confidence_is_low():
    metrics = compute_claim_metrics(
        claims_v1=[],
        claims_v2=[
            _vc(ClaimVerdict.UNVERIFIABLE_V0),
            _vc(ClaimVerdict.UNVERIFIABLE_V0),
        ],
    )
    assert metrics.claim_precision == 0.0
    assert metrics.verification_confidence == 0.2


def test_needs_human_review_is_separate_non_uv_bucket():
    metrics = compute_claim_metrics(
        claims_v1=[],
        claims_v2=[
            _vc(ClaimVerdict.SUPPORTED),
            _vc(ClaimVerdict.NEEDS_HUMAN_REVIEW),
            _vc(ClaimVerdict.UNVERIFIABLE_V0),
        ],
    )

    assert metrics.total_claims == 3
    assert metrics.supported_claims == 1
    assert metrics.unverifiable_claims == 1
    assert metrics.supported_ratio == 1 / 3
    assert metrics.unverifiable_rate == 1 / 3
    assert (
        metrics.per_type_verdict_counts["grounded_claim"]["needs_human_review"]
        == 1
    )


def test_empty_claims_confidence_is_none():
    metrics = compute_claim_metrics(claims_v1=[], claims_v2=[])
    assert metrics.verification_confidence is None
    assert metrics.confidence_components == {}
