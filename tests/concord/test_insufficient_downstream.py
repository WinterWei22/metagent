"""Task 7 RED→GREEN: downstream recognition of INSUFFICIENT_EVIDENCE in react_runner.

Tests verify:
1. VerificationOutcome has n_insufficient_evidence field.
2. When verifier returns INSUFFICIENT_EVIDENCE claims (via verdicts_total dict),
   they are counted in n_insufficient_evidence — not in n_supported, n_unsupported,
   n_unverifiable_v0, or n_contradicted.
3. When verifier returns INSUFFICIENT_EVIDENCE claims via claims_v1,
   they are counted correctly.
4. quality (n_contradicted + n_unsupported) is NOT affected by INSUFFICIENT_EVIDENCE.
5. ConcordIterationRecord also has n_insufficient_evidence field.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from concord.agent.react_runner import (
    ConcordIterationRecord,
    ConcordReactResult,
    ConcordReactRunner,
    VerificationOutcome,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_v3_task() -> dict[str, Any]:
    return {
        "task_id": "compound_only_enrich_mammalian_lm_pathway_WP167_seed3",
        "task_type": "compound_only_enrichment",
        "domain": "mammalian",
        "differential_metabolites": [
            {"name": "arachidonic acid", "kegg_id": "C00219",
             "inchikey": "YZXBAPSDXZZRGB-DOFZRALJSA-N"},
        ],
        "differential_spectra": None,
        "ground_truth_pathway": {
            "pathway_id": "lm_pathway:WP167",
            "pathway_name": "Eicosanoid synthesis",
            "pathway_source": "lipidmaps",
            "external_id": "WP167",
            "primary_pathway_pre_aggregation": "lm_pathway:WP167",
        },
        "ground_truth_signal_compounds": ["C00219"],
        "ground_truth_noise_compounds": [],
        "ramp_enrichment_result": {
            "input_compounds": ["C00219"],
            "resolved_compounds": ["C00219"],
            "unresolved_compounds": [],
            "background_size": 1000,
            "n_input_resolved": 1,
            "top_pathways": [
                {"pathway_id": "RAMP_P_000050021", "fdr": 0.01,
                 "pathway_name": "Biological oxidations"},
            ],
        },
    }


@pytest.fixture
def fake_concord_result() -> ConcordReactResult:
    return ConcordReactResult(
        task_id="compound_only_enrich_mammalian_lm_pathway_WP167_seed3",
        iterations=[
            ConcordIterationRecord(
                iter_idx=0,
                narrative_json="{...}",
                n_turns=8,
                n_tool_calls=26,
            ),
        ],
        final_iter_idx=0,
        final_narrative_text=(
            "Multi-paradigm pathway analysis identifies arachidonic "
            "acid metabolism as the dominant signal."
        ),
        final_claims=[],
        task_outcome="normal",
        elapsed_seconds=194.2,
        llm_model="MiniMax-M2.7-highspeed",
    )


# ---------------------------------------------------------------------------
# Unit tests on VerificationOutcome dataclass
# ---------------------------------------------------------------------------

def test_verification_outcome_has_n_insufficient_evidence_field():
    """VerificationOutcome must expose n_insufficient_evidence as a field."""
    outcome = VerificationOutcome(ok=True, verdict=None, error=None)
    assert hasattr(outcome, "n_insufficient_evidence"), (
        "VerificationOutcome is missing n_insufficient_evidence field"
    )
    assert outcome.n_insufficient_evidence == 0


def test_concord_iteration_record_has_n_insufficient_evidence_field():
    """ConcordIterationRecord must expose n_insufficient_evidence as a field."""
    record = ConcordIterationRecord(iter_idx=0, narrative_json="{}")
    assert hasattr(record, "n_insufficient_evidence"), (
        "ConcordIterationRecord is missing n_insufficient_evidence field"
    )
    assert record.n_insufficient_evidence == 0


# ---------------------------------------------------------------------------
# verify_with_b1: verdicts_total dict path
# ---------------------------------------------------------------------------

def test_insufficient_evidence_counted_via_verdicts_total(fake_concord_result, fake_v3_task):
    """INSUFFICIENT_EVIDENCE in verdicts_total dict → n_insufficient_evidence, not UV."""
    fake_verdict = MagicMock(
        verdicts_total={
            "supported": 2,
            "unsupported": 1,
            "contradicted": 0,
            "unverifiable_v0": 1,
            "insufficient_evidence": 3,
        },
        claims_v1=[],
        warnings=[],
    )
    runner = ConcordReactRunner(verifier_fn=MagicMock(return_value=fake_verdict))
    outcome = runner.verify_with_b1(fake_concord_result, fake_v3_task)

    assert outcome.ok is True
    assert outcome.n_insufficient_evidence == 3
    # Must NOT bleed into supported or UV
    assert outcome.n_supported == 2
    assert outcome.n_unverifiable_v0 == 1
    # quality = contradicted + unsupported only (INSUFFICIENT does not penalize)
    assert outcome.quality == 1  # 0 contradicted + 1 unsupported


def test_insufficient_evidence_not_counted_as_supported(fake_concord_result, fake_v3_task):
    """INSUFFICIENT_EVIDENCE must be strictly excluded from n_supported."""
    fake_verdict = MagicMock(
        verdicts_total={
            "supported": 0,
            "unsupported": 0,
            "contradicted": 0,
            "unverifiable_v0": 0,
            "insufficient_evidence": 5,
        },
        claims_v1=[],
        warnings=[],
    )
    runner = ConcordReactRunner(verifier_fn=MagicMock(return_value=fake_verdict))
    outcome = runner.verify_with_b1(fake_concord_result, fake_v3_task)

    assert outcome.n_supported == 0, "INSUFFICIENT_EVIDENCE must not inflate n_supported"
    assert outcome.n_insufficient_evidence == 5
    assert outcome.quality == 0  # INSUFFICIENT does not affect quality


# ---------------------------------------------------------------------------
# verify_with_b1: claims_v1 list path (enum matching)
# ---------------------------------------------------------------------------

def test_insufficient_evidence_counted_via_claims_v1(fake_concord_result, fake_v3_task):
    """INSUFFICIENT_EVIDENCE in claims_v1 → counted correctly, not UV."""
    from verifier.schemas import ClaimVerdict

    def _make_claim(verdict_val: ClaimVerdict) -> MagicMock:
        c = MagicMock()
        c.verdict = verdict_val
        return c

    claims = [
        _make_claim(ClaimVerdict.SUPPORTED),
        _make_claim(ClaimVerdict.INSUFFICIENT_EVIDENCE),
        _make_claim(ClaimVerdict.INSUFFICIENT_EVIDENCE),
        _make_claim(ClaimVerdict.UNVERIFIABLE_V0),
    ]
    # Use empty verdicts_total to force claims_v1 path
    fake_verdict = MagicMock(
        verdicts_total={},
        claims_v1=claims,
        claim_metrics=None,
        warnings=[],
    )
    runner = ConcordReactRunner(verifier_fn=MagicMock(return_value=fake_verdict))
    outcome = runner.verify_with_b1(fake_concord_result, fake_v3_task)

    assert outcome.n_supported == 1
    assert outcome.n_insufficient_evidence == 2
    assert outcome.n_unverifiable_v0 == 1
    assert outcome.n_unsupported == 0
    assert outcome.n_contradicted == 0


def test_insufficient_evidence_not_lumped_into_unverifiable(fake_concord_result, fake_v3_task):
    """Regression guard: INSUFFICIENT_EVIDENCE must NOT increment n_unverifiable_v0."""
    from verifier.schemas import ClaimVerdict

    def _make_claim(v: ClaimVerdict) -> MagicMock:
        c = MagicMock()
        c.verdict = v
        return c

    claims = [_make_claim(ClaimVerdict.INSUFFICIENT_EVIDENCE)]
    fake_verdict = MagicMock(
        verdicts_total={},
        claims_v1=claims,
        claim_metrics=None,
        warnings=[],
    )
    runner = ConcordReactRunner(verifier_fn=MagicMock(return_value=fake_verdict))
    outcome = runner.verify_with_b1(fake_concord_result, fake_v3_task)

    assert outcome.n_unverifiable_v0 == 0, (
        "INSUFFICIENT_EVIDENCE must not be lumped into n_unverifiable_v0"
    )
    assert outcome.n_insufficient_evidence == 1
