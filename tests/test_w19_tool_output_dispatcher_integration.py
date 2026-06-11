from __future__ import annotations

from verifier.agent import _verify_per_claim_sub6
from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim, VerifiedClaim


def _claim(text: str, claim_type: ClaimType = ClaimType.GROUNDED) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_id="claim-1",
        claim_text=text,
        claim_type=claim_type,
        classifier_source="rule",
    )


def _source_report() -> dict:
    return {
        "task_id": "task-1",
        "ramp_enrichment_result": {
            "top_pathways": [
                {"pathway_name": "Galactosemia", "rank": 1, "fdr": 1.65e-12}
            ]
        },
    }


def test_tool_output_fires_after_existing_layers_leave_uv(monkeypatch):
    calls = []

    def fake_existing_uv(claim, source_report):
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            verdict=ClaimVerdict.UNVERIFIABLE_V0,
            evidence="existing layer uv",
            verifier_layer="factual_sub6",
        )

    def fake_tool_output(claim, source_report):
        calls.append(claim.claim_id)
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            verdict=ClaimVerdict.SUPPORTED,
            evidence="tool output match",
            verifier_layer="tool_output_sub6",
        )

    monkeypatch.setattr("verifier.layers.factual_sub6.verify_factual_sub6", fake_existing_uv)
    monkeypatch.setattr("verifier.agent.verify_tool_output_sub6", fake_tool_output, raising=False)
    verified = _verify_per_claim_sub6(
        [_claim("RaMP ORA produces an FDR of 1.65e-12")],
        _source_report(),
        ramp_db_path=None,
        ramp_conn=None,
        driver_lookup=None,
        is_final_iteration=True,
        iteration=1,
    )
    assert calls == ["claim-1"]
    assert verified[0].verdict == ClaimVerdict.SUPPORTED
    assert verified[0].verifier_layer == "tool_output_sub6"


def test_tool_output_does_not_fire_when_existing_layer_supported(monkeypatch):
    calls = []

    def fake_existing_supported(claim, source_report):
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            verdict=ClaimVerdict.SUPPORTED,
            evidence="existing support",
            verifier_layer="set_enrichment",
        )

    def fake_tool_output(claim, source_report):
        calls.append(claim.claim_id)
        raise AssertionError("tool_output_sub6 should not fire")

    monkeypatch.setattr("verifier.layers.set_enrichment.verify_set_enrichment", fake_existing_supported)
    monkeypatch.setattr("verifier.agent.verify_tool_output_sub6", fake_tool_output, raising=False)
    verified = _verify_per_claim_sub6(
        [_claim("Galactosemia is enriched", ClaimType.SET_ENRICHMENT)],
        _source_report(),
        ramp_db_path=None,
        ramp_conn=None,
        driver_lookup=None,
        is_final_iteration=True,
        iteration=1,
    )
    assert calls == []
    assert verified[0].verdict != ClaimVerdict.ERROR


def test_tool_output_respects_final_iteration_guard(monkeypatch):
    calls = []

    def fake_existing_uv(claim, source_report):
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            verdict=ClaimVerdict.UNVERIFIABLE_V0,
            evidence="existing layer uv",
            verifier_layer="factual_sub6",
        )

    def fake_tool_output(claim, source_report):
        calls.append(claim.claim_id)
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            verdict=ClaimVerdict.SUPPORTED,
            evidence="tool output match",
            verifier_layer="tool_output_sub6",
        )

    monkeypatch.setattr("verifier.layers.factual_sub6.verify_factual_sub6", fake_existing_uv)
    monkeypatch.setattr("verifier.agent.verify_tool_output_sub6", fake_tool_output, raising=False)
    verified = _verify_per_claim_sub6(
        [_claim("RaMP ORA produces an FDR of 1.65e-12")],
        _source_report(),
        ramp_db_path=None,
        ramp_conn=None,
        driver_lookup=None,
        is_final_iteration=False,
        iteration=0,
    )
    assert calls == []
    assert verified[0].verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_signal_sub6_catch_all_remains_disabled():
    from verifier.layers.llm_judge_sub6 import SIGNAL_SUB6_CATCH_ALL_ENABLED

    assert SIGNAL_SUB6_CATCH_ALL_ENABLED is False
