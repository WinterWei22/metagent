"""Tests for verifier claim table construction."""
from __future__ import annotations

from verifier.claim_table import build_claim_table
from verifier.schemas import ClaimType, ClaimVerdict, VerifiedClaim


def test_old_verified_claim_builds_claim_table_with_fallback_id():
    claim = VerifiedClaim(
        claim_text="Caffeine has formula C8H10N4O2",
        claim_type=ClaimType.GROUNDED,
        verdict=ClaimVerdict.SUPPORTED,
        evidence="source formula matches",
        source_field="candidates[0].metabolite_info.molecular_formula",
    )

    table = build_claim_table([claim], pass_id="v1")

    assert table.pass_id == "v1"
    assert len(table.rows) == 1
    row = table.rows[0]
    assert row.claim_id == "v1:c000"
    assert row.claim_text == claim.claim_text
    assert row.verdict == ClaimVerdict.SUPPORTED
    assert row.evidence_summary == "source formula matches"
    assert row.source_field == "candidates[0].metabolite_info.molecular_formula"
    assert row.verifier_layer == "grounded"
    assert row.severity == "info"


def test_claim_table_severity_mapping():
    claims = [
        VerifiedClaim(claim_text="u", claim_type=ClaimType.GROUNDED,
                      verdict=ClaimVerdict.UNVERIFIABLE_V0, evidence="u"),
        VerifiedClaim(claim_text="h", claim_type=ClaimType.GROUNDED,
                      verdict=ClaimVerdict.NEEDS_HUMAN_REVIEW, evidence="h"),
        VerifiedClaim(claim_text="n", claim_type=ClaimType.GROUNDED,
                      verdict=ClaimVerdict.UNSUPPORTED, evidence="n"),
        VerifiedClaim(claim_text="c", claim_type=ClaimType.GROUNDED,
                      verdict=ClaimVerdict.CONTRADICTED, evidence="c"),
        VerifiedClaim(claim_text="e", claim_type=ClaimType.GROUNDED,
                      verdict=ClaimVerdict.ERROR, evidence="e"),
    ]
    table = build_claim_table(claims, pass_id="v2")
    assert [row.severity for row in table.rows] == [
        "minor",
        "minor",
        "major",
        "critical",
        "major",
    ]
