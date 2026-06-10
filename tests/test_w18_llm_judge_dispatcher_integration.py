from __future__ import annotations

import importlib

from verifier.schemas import ClaimType, ClaimVerdict


def _dispatcher_adapter():
    return importlib.import_module("verifier.layers.llm_judge_sub6")


def test_prior_supported_verdict_skips_llm_judge():
    adapter = _dispatcher_adapter()
    calls = []
    result = adapter.verify_post_uv_only(
        prior_verdict=ClaimVerdict.SUPPORTED,
        claim={"claim_text": "already handled", "claim_type": ClaimType.GROUNDED},
        source_report={},
        judge_call=lambda *_args, **_kwargs: calls.append("called"),
    )
    assert result.verdict == ClaimVerdict.SUPPORTED
    assert calls == []


def test_prior_uv_and_eligible_claim_type_calls_llm_judge():
    adapter = _dispatcher_adapter()
    calls = []
    adapter.verify_post_uv_only(
        prior_verdict=ClaimVerdict.UNVERIFIABLE_V0,
        claim={"claim_text": "MUMM:x has p = 0.01", "claim_type": ClaimType.GROUNDED},
        source_report={},
        judge_call=lambda *_args, **_kwargs: calls.append("called") or {"verdict": "SUPPORTED", "confidence": 0.9, "evidence_pointer": "x", "rationale": "ok"},
    )
    assert calls == ["called"]


def test_prior_uv_and_ineligible_claim_type_leaves_uv_without_call():
    adapter = _dispatcher_adapter()
    calls = []
    result = adapter.verify_post_uv_only(
        prior_verdict=ClaimVerdict.UNVERIFIABLE_V0,
        claim={"claim_text": "driver claim", "claim_type": ClaimType.DRIVER_METABOLITE},
        source_report={},
        judge_call=lambda *_args, **_kwargs: calls.append("called"),
    )
    assert result.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert calls == []


def test_signal_sub6_catch_all_remains_disabled():
    adapter = _dispatcher_adapter()
    assert adapter.SIGNAL_SUB6_CATCH_ALL_ENABLED is False


def test_factual_sub6_route_is_preserved_before_llm_judge():
    adapter = _dispatcher_adapter()
    ordered_layers = adapter.sub6_dispatch_order_for(ClaimType.FACTUAL)
    assert "factual_sub6" in ordered_layers
    assert ordered_layers.index("factual_sub6") < ordered_layers.index("llm_judge_sub6")


def test_verify_per_claim_sub6_calls_llm_judge_after_uv(monkeypatch):
    agent = importlib.import_module("verifier.agent")
    calls = []

    def fake_judge(claim, source_report, **_kwargs):
        calls.append(claim.claim_text)
        return _verified(claim, ClaimVerdict.SUPPORTED, "judge supported")

    monkeypatch.setattr(agent, "verify_llm_judge_sub6", fake_judge, raising=False)
    factual = importlib.import_module("verifier.layers.factual_sub6")
    monkeypatch.setattr(
        factual,
        "verify_factual_sub6",
        lambda claim, source_report: _verified(claim, ClaimVerdict.UNVERIFIABLE_V0, "uv"),
    )

    result = agent._verify_per_claim_sub6(
        [_claim("MUMM:x has p = 0.01", ClaimType.GROUNDED)],
        source_report={},
        ramp_db_path=None,
        ramp_conn=None,
        driver_lookup=None,
    )

    assert calls == ["MUMM:x has p = 0.01"]
    assert result[0].verdict == ClaimVerdict.SUPPORTED


def test_verify_per_claim_sub6_skips_llm_judge_on_non_final_iteration(monkeypatch):
    agent = importlib.import_module("verifier.agent")
    calls = []

    def fake_judge(claim, source_report, **_kwargs):
        calls.append(claim.claim_text)
        return _verified(claim, ClaimVerdict.SUPPORTED, "judge supported")

    monkeypatch.setattr(agent, "verify_llm_judge_sub6", fake_judge, raising=False)
    factual = importlib.import_module("verifier.layers.factual_sub6")
    monkeypatch.setattr(
        factual,
        "verify_factual_sub6",
        lambda claim, source_report: _verified(claim, ClaimVerdict.UNVERIFIABLE_V0, "uv"),
    )

    result = agent._verify_per_claim_sub6(
        [_claim("MUMM:x has p = 0.01", ClaimType.GROUNDED)],
        source_report={},
        ramp_db_path=None,
        ramp_conn=None,
        driver_lookup=None,
        is_final_iteration=False,
    )

    assert calls == []
    assert result[0].verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_verify_per_claim_sub6_reuses_one_judge_cost_tracker(monkeypatch):
    agent = importlib.import_module("verifier.agent")
    cost_cap = importlib.import_module("verifier.helpers.judge_cost_cap")
    cost_cap.reset_run_level_tracker(run_id="test", cap_usd=2.0)
    tracker_ids = []

    def fake_judge(claim, source_report, *, cost_tracker):
        tracker_ids.append(id(cost_tracker))
        cost_tracker.record(0.5)
        return _verified(claim, ClaimVerdict.UNVERIFIABLE_V0, "still uv")

    monkeypatch.setattr(agent, "verify_llm_judge_sub6", fake_judge, raising=False)
    factual = importlib.import_module("verifier.layers.factual_sub6")
    monkeypatch.setattr(
        factual,
        "verify_factual_sub6",
        lambda claim, source_report: _verified(claim, ClaimVerdict.UNVERIFIABLE_V0, "uv"),
    )

    result = agent._verify_per_claim_sub6(
        [
            _claim("MUMM:x has p = 0.01", ClaimType.GROUNDED),
            _claim("MUMM:y has p = 0.02", ClaimType.GROUNDED),
        ],
        source_report={},
        ramp_db_path=None,
        ramp_conn=None,
        driver_lookup=None,
    )

    assert len(result) == 2
    assert len(tracker_ids) == 2
    assert len(set(tracker_ids)) == 1


def _claim(text: str, claim_type: ClaimType):
    from verifier.schemas import ClassifiedClaim

    return ClassifiedClaim(
        claim_id=text,
        claim_text=text,
        claim_type=claim_type,
        classifier_source="rule",
    )


def _verified(claim, verdict: ClaimVerdict, evidence: str):
    from verifier.schemas import VerifiedClaim

    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        verdict=verdict,
        evidence=evidence,
        verifier_layer="llm_judge_sub6",
    )
