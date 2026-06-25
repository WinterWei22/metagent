"""Task 9 — TDD tests: driver_metabolite v4 degradation to INSUFFICIENT_EVIDENCE.

When both ground_truth_signal_compounds and ground_truth_noise_compounds are
empty (v4 task design), the layer must return INSUFFICIENT_EVIDENCE with an
evidence string noting the v4 design trade-off, rather than silently producing
UNSUPPORTED / UNVERIFIABLE_V0.

The v3 path (at least one list non-empty) must remain byte-for-byte unchanged.
"""
from __future__ import annotations

import pytest

from schemas.sub6_report import SubsixSourceReport
from verifier.layers.driver_metabolite import (
    reset_lookup_cache,
    verify_driver_metabolite,
)
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
)


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_lookup_cache()
    yield
    reset_lookup_cache()


@pytest.fixture
def minimal_lookup() -> dict[str, str]:
    """Small lookup so claimed names are resolvable even in v4 scenario."""
    rows = [
        ("Tyrosine", "C00082", "HMDB0000158", "OUYCCCASQSFEME"),
        ("DOPA",     "C00355", "HMDB0000181", "WTDRDQBEARUVNC"),
        ("Caffeine", "C07481", "HMDB0001847", "RYYVLZVUVIJVGH"),
    ]
    out: dict[str, str] = {}
    for name, kegg, hmdb, ik_block in rows:
        for k in (name, kegg, hmdb, ik_block):
            out[k.lower()] = ik_block
    return out


def _claim(text: str, *, candidate_name: str | None = None) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_text=text,
        claim_type=ClaimType.DRIVER_METABOLITE,
        classifier_source="rule",
        extracted_fields=ClaimExtractedFields(candidate_name=candidate_name),
    )


def _v4_report() -> SubsixSourceReport:
    """v4-style task: both ground-truth compound lists are empty."""
    return SubsixSourceReport(
        task_id="v4_task_001",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "map00350", "pathway_name": "Tyrosine metabolism"},
        ground_truth_signal_compounds=[],
        ground_truth_noise_compounds=[],
        ramp_enrichment_result={"top_pathways": []},
    )


def _v3_report_signal_only() -> SubsixSourceReport:
    """v3-style task: signal non-empty, noise empty."""
    return SubsixSourceReport(
        task_id="v3_signal_task",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "map00350", "pathway_name": "Tyrosine metabolism"},
        ground_truth_signal_compounds=["C00082", "C00355"],
        ground_truth_noise_compounds=[],
        ramp_enrichment_result={"top_pathways": []},
    )


def _v3_report_noise_only() -> SubsixSourceReport:
    """v3-style task: noise non-empty, signal empty."""
    return SubsixSourceReport(
        task_id="v3_noise_task",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "map00350", "pathway_name": "Tyrosine metabolism"},
        ground_truth_signal_compounds=[],
        ground_truth_noise_compounds=["C07481"],
        ramp_enrichment_result={"top_pathways": []},
    )


# ---------------------------------------------------------------------------
# RED → GREEN: v4 both-empty guard
# ---------------------------------------------------------------------------


def test_v4_both_empty_returns_insufficient_evidence(minimal_lookup):
    """Core contract: both-empty ground-truth → INSUFFICIENT_EVIDENCE."""
    r = verify_driver_metabolite(
        _claim("Tyrosine and DOPA are key drivers of this enrichment."),
        _v4_report(),
        lookup=minimal_lookup,
    )
    assert r.verdict == ClaimVerdict.INSUFFICIENT_EVIDENCE


def test_v4_evidence_mentions_v4_design_tradeoff(minimal_lookup):
    """Evidence string must communicate the v4 design trade-off clearly."""
    r = verify_driver_metabolite(
        _claim("Tyrosine and DOPA are key drivers of this enrichment."),
        _v4_report(),
        lookup=minimal_lookup,
    )
    assert r.verdict == ClaimVerdict.INSUFFICIENT_EVIDENCE
    ev = r.evidence.lower()
    # Must mention v4 and ground-truth / compounds limitation
    assert "v4" in ev
    assert "ground" in ev or "compound" in ev


def test_v4_layer_attribution_correct(minimal_lookup):
    """VerifiedClaim must carry the correct layer and claim_type."""
    r = verify_driver_metabolite(
        _claim("Tyrosine drives the pathway."),
        _v4_report(),
        lookup=minimal_lookup,
    )
    assert r.verdict == ClaimVerdict.INSUFFICIENT_EVIDENCE
    assert r.verifier_layer == "driver_metabolite"
    assert r.claim_type == ClaimType.DRIVER_METABOLITE


def test_v4_claim_fields_preserved(minimal_lookup):
    """INSUFFICIENT_EVIDENCE result must echo claim_id and claim_text."""
    claim = _claim("Tyrosine and DOPA are key drivers.", candidate_name=None)
    r = verify_driver_metabolite(claim, _v4_report(), lookup=minimal_lookup)
    assert r.verdict == ClaimVerdict.INSUFFICIENT_EVIDENCE
    assert r.claim_text == claim.claim_text


# ---------------------------------------------------------------------------
# Regression: v3 path (at least one list non-empty) → original verdict
# ---------------------------------------------------------------------------


def test_v3_signal_only_supported(minimal_lookup):
    """signal non-empty → v3 path; Tyrosine in signal → SUPPORTED."""
    r = verify_driver_metabolite(
        _claim("Tyrosine and DOPA are key drivers."),
        _v3_report_signal_only(),
        lookup=minimal_lookup,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED


def test_v3_noise_only_contradicted(minimal_lookup):
    """noise non-empty → v3 path; Caffeine is noise → CONTRADICTED."""
    r = verify_driver_metabolite(
        _claim("Caffeine is a key driver of this enrichment."),
        _v3_report_noise_only(),
        lookup=minimal_lookup,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED
