from __future__ import annotations

import importlib

import pytest

from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim, VerifiedClaim


def _module():
    return importlib.import_module("verifier.helpers.tool_output_crash_preservation")


def _claim(idx: int) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_id=f"claim-{idx}",
        claim_text=f"claim text {idx}",
        claim_type=ClaimType.GROUNDED,
        classifier_source="rule",
    )


def _verified(claim: ClassifiedClaim) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence="checked",
        verifier_layer="tool_output_sub6",
    )


def test_partial_claims_are_persisted_before_later_claim_crash(tmp_path):
    state_path = tmp_path / "task_state.json"
    claims = [_claim(1), _claim(2), _claim(3)]

    def verifier(claim):
        if claim.claim_id == "claim-3":
            raise RuntimeError("boom")
        return _verified(claim)

    with pytest.raises(RuntimeError):
        _module().run_with_partial_persistence(
            claims,
            verifier=verifier,
            state_path=state_path,
            task_id="task-1",
        )

    restored = _module().read_persisted_claims(state_path)
    assert [row["claim_id"] for row in restored] == ["claim-1", "claim-2"]


def test_retroactive_aggregate_reads_persisted_claims(tmp_path):
    state_path = tmp_path / "task_state.json"
    _module().write_partial_claims(
        state_path,
        task_id="task-1",
        claims=[
            _verified(_claim(1)),
            VerifiedClaim(
                claim_id="claim-2",
                claim_text="bad value",
                claim_type=ClaimType.GROUNDED,
                verdict=ClaimVerdict.CONTRADICTED,
                evidence="mismatch",
            ),
        ],
    )
    metrics = _module().retroactive_compute_claim_metrics(state_path)
    assert metrics.total_claims == 2
    assert metrics.unverifiable_claims == 1
    assert metrics.contradicted_claims == 1
