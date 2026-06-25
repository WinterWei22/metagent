"""TDD: INSUFFICIENT_EVIDENCE verdict must be counted in ClaimMetrics
and must map to 'partially_verified' in _aggregate_verdict.

RED: before fix — insufficient_evidence_claims field missing, aggregate wrong.
GREEN: after fix — field present, counter incremented, aggregate correct.
"""
from __future__ import annotations

import pytest

from verifier.schemas import (
    ClaimMetrics,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    VerifiedClaim,
)
from verifier.metrics import compute_claim_metrics


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_claim(verdict: ClaimVerdict) -> VerifiedClaim:
    return VerifiedClaim(
        claim_text="Test claim.",
        claim_type=ClaimType.SET_ENRICHMENT,
        claim_subtype=ClaimSubtype.UNKNOWN,
        verdict=verdict,
        evidence="test evidence",
    )


# ---------------------------------------------------------------------------
# Test A: ClaimMetrics has insufficient_evidence_claims field
# ---------------------------------------------------------------------------


def test_claim_metrics_has_insufficient_evidence_field():
    """ClaimMetrics must have an insufficient_evidence_claims int field."""
    m = ClaimMetrics()
    assert hasattr(m, "insufficient_evidence_claims"), (
        "ClaimMetrics missing 'insufficient_evidence_claims' field"
    )
    assert isinstance(m.insufficient_evidence_claims, int)
    assert m.insufficient_evidence_claims == 0


# ---------------------------------------------------------------------------
# Test B: compute_claim_metrics counts INSUFFICIENT_EVIDENCE
# ---------------------------------------------------------------------------


def test_compute_claim_metrics_counts_insufficient_evidence():
    """compute_claim_metrics must count INSUFFICIENT_EVIDENCE claims."""
    ie_claim = _make_claim(ClaimVerdict.INSUFFICIENT_EVIDENCE)
    sup_claim = _make_claim(ClaimVerdict.SUPPORTED)

    metrics = compute_claim_metrics([ie_claim, sup_claim], [ie_claim, sup_claim])

    assert metrics.insufficient_evidence_claims >= 1, (
        f"Expected insufficient_evidence_claims >= 1, got {metrics.insufficient_evidence_claims}"
    )
    assert metrics.insufficient_evidence_claims == 1


def test_compute_claim_metrics_no_insufficient_evidence_when_absent():
    """compute_claim_metrics must return 0 when no INSUFFICIENT_EVIDENCE claims."""
    sup_claim = _make_claim(ClaimVerdict.SUPPORTED)
    metrics = compute_claim_metrics([sup_claim], [sup_claim])
    assert metrics.insufficient_evidence_claims == 0


# ---------------------------------------------------------------------------
# Test C: _aggregate_verdict returns partially_verified for INSUFFICIENT_EVIDENCE
# ---------------------------------------------------------------------------


def test_aggregate_verdict_insufficient_evidence_is_partially_verified():
    """_aggregate_verdict must return 'partially_verified' when only non-supported
    claim is INSUFFICIENT_EVIDENCE, not 'verified'."""
    from verifier.agent import _aggregate_verdict

    claims = [
        _make_claim(ClaimVerdict.SUPPORTED),
        _make_claim(ClaimVerdict.INSUFFICIENT_EVIDENCE),
    ]
    verdict = _aggregate_verdict(claims)
    assert verdict == "partially_verified", (
        f"Expected 'partially_verified', got '{verdict}'. "
        "INSUFFICIENT_EVIDENCE should not allow 'verified' aggregate."
    )


def test_aggregate_verdict_all_sufficient_still_verified():
    """All-SUPPORTED list must still return 'verified'."""
    from verifier.agent import _aggregate_verdict

    claims = [_make_claim(ClaimVerdict.SUPPORTED), _make_claim(ClaimVerdict.SUPPORTED)]
    verdict = _aggregate_verdict(claims)
    assert verdict == "verified"


def test_aggregate_verdict_only_insufficient_evidence_is_partially_verified():
    """List with only INSUFFICIENT_EVIDENCE returns 'partially_verified'."""
    from verifier.agent import _aggregate_verdict

    claims = [_make_claim(ClaimVerdict.INSUFFICIENT_EVIDENCE)]
    verdict = _aggregate_verdict(claims)
    assert verdict == "partially_verified", (
        f"Expected 'partially_verified', got '{verdict}'"
    )
