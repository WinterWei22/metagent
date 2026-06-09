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
