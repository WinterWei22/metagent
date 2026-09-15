"""W8 D4 sub-task 2 — `ConcordReactRunner.verify_with_b1()` strict-TDD tests.

The method wires B1 `verifier.agent.verify_sub6()` into the runner: it
adapts a ConcordReactResult + sub6b-v3 task → narrative string +
SubsixSourceReport, calls verify_sub6, and returns a typed
`VerificationOutcome` envelope.

Tests use a fake `verifier_fn` injection to avoid real B1 LLM calls
(verify_sub6 normally makes 1-7 LLM calls of its own).
"""
from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock

import pytest

from concord.agent.react_runner import (
    ConcordIterationRecord,
    ConcordReactResult,
    ConcordReactRunner,
)


# ---------------------------------------------------------------------------
# Fixtures (mirrors test_verifier_adapter.py so the integration is
# end-to-end exerciseable)
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
        "ground_truth_signal_compounds": ["C00219", "C00909"],
        "ground_truth_noise_compounds": ["C00116"],
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
                iter_idx=0, narrative_json="{...}", n_turns=8, n_tool_calls=26,
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


def _make_fake_verifier_result(
    *,
    n_supported: int = 1,
    n_unsupported: int = 0,
    n_contradicted: int = 0,
    n_unverifiable_v0: int = 0,
) -> Any:
    """Return an object that quacks like B1 `VerifiedIdentification`.

    Real VerifiedIdentification is a pydantic model with a `claims_v1`
    list, a `verdicts_total` dict, and a few metadata fields. The
    verify_with_b1 method should only read `verdicts_total` (or compute
    counts from `claims_v1`); the test fixture provides both for
    flexibility.
    """
    return MagicMock(
        verdicts_total={
            "supported": n_supported,
            "unsupported": n_unsupported,
            "contradicted": n_contradicted,
            "unverifiable_v0": n_unverifiable_v0,
        },
        claims_v1=[],
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_verify_with_b1_happy_path_counts_verdicts(fake_concord_result, fake_v3_task):
    """verify_with_b1 wires verifier_fn, returns VerificationOutcome with quality."""
    fake_verifier = MagicMock(return_value=_make_fake_verifier_result(
        n_supported=3, n_unsupported=1, n_contradicted=2, n_unverifiable_v0=1,
    ))
    runner = ConcordReactRunner(verifier_fn=fake_verifier)
    outcome = runner.verify_with_b1(fake_concord_result, fake_v3_task)

    assert outcome.ok is True
    assert outcome.error is None
    assert outcome.n_supported == 3
    assert outcome.n_unsupported == 1
    assert outcome.n_contradicted == 2
    assert outcome.n_unverifiable_v0 == 1
    assert outcome.quality == 3  # unsupported + contradicted (B1 D4 def)
    # The verifier_fn was called with the prose narrative (not the JSON)
    call_args = fake_verifier.call_args
    narrative_arg, *_ = call_args.args if call_args.args else (None,)
    assert "arachidonic acid metabolism" in (narrative_arg or "").lower()


def test_verify_with_b1_structured_eval_flag_passes_json_payload(fake_concord_result, fake_v3_task, monkeypatch):
    """W22: eval can opt into structured claims without changing default behavior."""
    fake_concord_result.final_claims = [
        {
            "claim_type": "PATHWAY_ENRICHMENT",
            "pathway_id": "KEGG:map00260",
            "pathway_name": "Glycine, serine and threonine metabolism",
            "evidence_method": "run_ramp_enrichment",
            "rank": 1,
            "score": 1e-6,
            "score_type": "fdr",
        }
    ]
    monkeypatch.setenv("METAGENT_VERIFY_STRUCTURED_CLAIMS", "1")
    fake_verifier = MagicMock(return_value=_make_fake_verifier_result())
    runner = ConcordReactRunner(verifier_fn=fake_verifier)

    outcome = runner.verify_with_b1(fake_concord_result, fake_v3_task)

    assert outcome.ok is True
    narrative_arg = fake_verifier.call_args.args[0]
    parsed = json.loads(narrative_arg)
    assert parsed["claims"][0]["grammar"] == "pathway_enrichment"
    assert parsed["claims"][0]["evidence_method"] == "run_ramp_enrichment"


def test_verify_with_b1_sets_verifier_llm_env_from_runner_and_restores(fake_concord_result, fake_v3_task, monkeypatch):
    """W22 D6: verifier-internal LLM calls must follow the eval provider/model."""
    monkeypatch.setenv("METAGENT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("METAGENT_OPENAI_MODEL", "gpt-5.5")
    monkeypatch.setenv("METAGENT_VERIFY_STRUCTURED_CLAIMS", "1")
    seen = {}

    def _recording_verifier(*_args, **_kwargs):
        import os

        seen["provider"] = os.environ.get("METAGENT_LLM_PROVIDER")
        seen["minimax_model"] = os.environ.get("METAGENT_MINIMAX_MODEL")
        seen["openai_model"] = os.environ.get("METAGENT_OPENAI_MODEL")
        return _make_fake_verifier_result()

    runner = ConcordReactRunner(
        verifier_fn=_recording_verifier,
        llm_provider="minimax",
        llm_model="MiniMax-M2.7-highspeed",
    )

    outcome = runner.verify_with_b1(fake_concord_result, fake_v3_task)

    assert outcome.ok is True
    assert seen == {
        "provider": "minimax",
        "minimax_model": "MiniMax-M2.7-highspeed",
        "openai_model": "gpt-5.5",
    }
    assert os.environ["METAGENT_LLM_PROVIDER"] == "openai"
    assert os.environ["METAGENT_OPENAI_MODEL"] == "gpt-5.5"
    assert os.environ.get("METAGENT_MINIMAX_MODEL") is None


def test_verify_with_b1_passes_final_iteration_flag(fake_concord_result, fake_v3_task):
    """W18 D3.5: non-final verifier passes must not run LLM judge."""
    fake_verifier = MagicMock(return_value=_make_fake_verifier_result())
    runner = ConcordReactRunner(verifier_fn=fake_verifier)

    runner.verify_with_b1(
        fake_concord_result,
        fake_v3_task,
        is_final_iteration=False,
    )

    assert fake_verifier.call_args.kwargs["is_final_iteration"] is False


def test_verify_with_b1_no_verifier_fn_raises(fake_concord_result, fake_v3_task):
    """Calling verify_with_b1 without injecting a verifier_fn must fail loudly —
    the default (None) means D4 wiring is incomplete."""
    runner = ConcordReactRunner(verifier_fn=None)
    with pytest.raises(RuntimeError, match=(
        "verifier_fn"
    )):
        runner.verify_with_b1(fake_concord_result, fake_v3_task)


def test_verify_with_b1_verifier_raises_returns_error_envelope(fake_concord_result, fake_v3_task):
    """If B1 verify_sub6 raises (verifier internal bug), the method does NOT
    propagate the exception — it returns VerificationOutcome with ok=False,
    error populated, and quality=0 (so a downstream feedback loop short-
    circuits gracefully rather than crashing)."""
    def _exploding_verifier(*_args, **_kwargs):
        raise ValueError("simulated layer 6a crash")

    runner = ConcordReactRunner(verifier_fn=_exploding_verifier)
    outcome = runner.verify_with_b1(fake_concord_result, fake_v3_task)

    assert outcome.ok is False
    assert outcome.error is not None
    assert "layer 6a crash" in outcome.error.lower()
    assert outcome.verdict is None
    assert outcome.quality == 0


def test_verify_with_b1_empty_narrative_does_not_call_verifier(fake_v3_task):
    """When ConcordReactResult has empty narrative_text (empty_system_failure
    outcome), verify_with_b1 short-circuits — calling B1 verify_sub6 on ""
    produces a vacuous claims list and wastes ~1-7 LLM calls."""
    empty_result = ConcordReactResult(
        task_id="x",
        final_narrative_text="",
        task_outcome="empty_system_failure",
        error="task_timeout",
    )
    fake_verifier = MagicMock(return_value=_make_fake_verifier_result())
    runner = ConcordReactRunner(verifier_fn=fake_verifier)
    outcome = runner.verify_with_b1(empty_result, fake_v3_task)

    # Verifier was NOT called
    fake_verifier.assert_not_called()
    assert outcome.ok is True  # short-circuit is not a failure
    assert outcome.n_supported == 0
    assert outcome.quality == 0


def test_verify_with_b1_extracts_counts_from_real_claim_metrics_shape(fake_concord_result, fake_v3_task):
    """D4 hotfix regression: real B1 VerifiedIdentification has no
    `verdicts_total` field — it exposes counts via `claim_metrics`
    (ClaimMetrics) using field names `supported_claims` / `unsupported_claims`
    / `contradicted_claims` / `unverifiable_claims`. The extractor must
    read those fields, not assume `n_supported` etc. (which is what the
    str-Enum-based fallback would land on)."""

    class _ClaimMetricsLike:
        supported_claims = 0
        unsupported_claims = 7
        contradicted_claims = 1
        unverifiable_claims = 26
        total_claims = 34

    class _VerdictLike:
        claim_metrics = _ClaimMetricsLike()
        verdicts_total = None  # B1 actually omits this entirely
        claims_v1 = []

    fake_verifier = MagicMock(return_value=_VerdictLike())
    runner = ConcordReactRunner(verifier_fn=fake_verifier)
    outcome = runner.verify_with_b1(fake_concord_result, fake_v3_task)

    assert outcome.ok is True
    assert outcome.n_supported == 0
    assert outcome.n_unsupported == 7
    assert outcome.n_contradicted == 1
    assert outcome.n_unverifiable_v0 == 26
    assert outcome.quality == 8  # n_unsupported + n_contradicted


def test_verify_with_b1_task_missing_required_field_returns_error(fake_concord_result):
    """A v3 task missing ground_truth_pathway (benchmark corruption) →
    VerificationOutcome with ok=False, error mentioning the validation
    failure. No crash."""
    bad_task = {"task_id": "x", "task_type": "compound_only_enrichment",
                "differential_metabolites": []}
    fake_verifier = MagicMock(return_value=_make_fake_verifier_result())
    runner = ConcordReactRunner(verifier_fn=fake_verifier)
    outcome = runner.verify_with_b1(fake_concord_result, bad_task)

    assert outcome.ok is False
    assert outcome.error is not None
    # Verifier was NOT called (adapter failed before reaching it)
    fake_verifier.assert_not_called()
