"""W16 cascade-as-default RED→GREEN test suite.

Tests that FAIL before the implementation and PASS after:

1. test_feedback_strategy_default_is_cascade — ConcordReactRunner must have
   a `feedback_strategy` dataclass field whose default is "cascade".

2. test_cascade_iteration_does_not_rerun_react — with feedback_strategy="cascade"
   (the default), an iter-1 feedback round must NOT call chat_with_tools again
   (no LLM ReAct re-run); the cascade deterministically rebuilds from iter-0
   verified claims.

3. test_rewrite_strategy_still_reachable — with feedback_strategy="rewrite",
   the old path (chat called twice: iter-0 + iter-1 rewrite) must still work.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from concord.agent.react_runner import (
    ConcordReactRunner,
    ConcordReactResult,
)
from verifier.grammar import ClaimGrammar
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    VerifiedClaim,
    SubjectKind,
)


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

_VALID_FINAL_JSON = json.dumps({
    "narrative_text": "Eicosanoid synthesis (WP:WP167) dominates the signal.",
    "claims": [
        {
            "claim_type": "PATHWAY_ENRICHMENT",
            "pathway_id": "WP:WP167",
            "pathway_name": "Eicosanoid synthesis",
        },
    ],
})


@pytest.fixture
def fake_task() -> dict[str, Any]:
    return {
        "task_id": "test_cascade_task",
        "task_type": "compound_only_enrichment",
        "domain": "mammalian",
        "differential_metabolites": [
            {"name": "arachidonic acid", "kegg_id": "C00219"},
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
            "top_pathways": [],
        },
    }


def _make_verified_claim(
    verdict: ClaimVerdict = ClaimVerdict.SUPPORTED,
    grammar: ClaimGrammar = ClaimGrammar.PATHWAY_MEMBERSHIP,
    claim_text: str = "Arachidonic acid is a member of Eicosanoid synthesis.",
    pathway_name: str = "Eicosanoid synthesis",
) -> VerifiedClaim:
    """Build a minimal but real VerifiedClaim for cascade consumption."""
    return VerifiedClaim(
        claim_text=claim_text,
        claim_type=ClaimType.BIOLOGICAL,
        claim_subtype=ClaimSubtype.UNKNOWN,
        subject="arachidonic acid",
        subject_kind=SubjectKind.COMPOUND,
        candidate_ref=None,
        verdict=verdict,
        evidence="test evidence",
        extracted_fields=ClaimExtractedFields(pathway_name=pathway_name),
        grammar=grammar,
        verifier_layer="test",
        trace_summary="test",
    )


def _make_verdict_mock(supported: int = 1, unsupported: int = 2, claims_v2=None):
    """Build a mock VerifiedIdentification with a quality > 0 (triggers feedback)
    and a non-empty claims_v2 so cascade has claims to process."""
    if claims_v2 is None:
        claims_v2 = [_make_verified_claim(ClaimVerdict.SUPPORTED)]
    return MagicMock(
        verdicts_total={
            "supported": supported,
            "unsupported": unsupported,
            "contradicted": 0,
            "unverifiable_v0": 0,
        },
        claims_v1=claims_v2,
        claims_v2=claims_v2,
        warnings=[],
        dropped_claims=[],
    )


def _finalise_msg(text: str = _VALID_FINAL_JSON) -> dict:
    return {"role": "assistant", "content": f"```json\n{text}\n```"}


# ---------------------------------------------------------------------------
# Test 1: feedback_strategy field default
# ---------------------------------------------------------------------------


def test_feedback_strategy_default_is_cascade():
    """ConcordReactRunner must expose a `feedback_strategy` dataclass field
    whose default value is 'cascade'."""
    fields = ConcordReactRunner.__dataclass_fields__
    assert "feedback_strategy" in fields, (
        "ConcordReactRunner must have a 'feedback_strategy' dataclass field"
    )
    default = fields["feedback_strategy"].default
    assert default == "cascade", (
        f"feedback_strategy default must be 'cascade'; got {default!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: cascade path does NOT re-run the ReAct LLM
# ---------------------------------------------------------------------------


def test_cascade_iteration_does_not_rerun_react(fake_task):
    """With feedback_strategy='cascade' (the default), iter-1 must NOT call
    chat_with_tools again. The cascade rebuilds from iter-0 claims without
    LLM re-run. Chat is only called ONCE (for iter-0)."""
    chat_call_count = [0]

    def _chat(_messages, **_kwargs):
        chat_call_count[0] += 1
        return _finalise_msg()

    # iter-0 verdict has quality > 0 (unsupported=2) so the feedback path triggers.
    iter0_verdict = _make_verdict_mock(supported=1, unsupported=2)

    # iter-1 cascade verdict: improved quality.
    iter1_verdict = _make_verdict_mock(supported=3, unsupported=0)

    verdict_sequence = iter([iter0_verdict, iter1_verdict])

    def _verifier(_narrative, _source_report, **_kwargs):
        return next(verdict_sequence)

    runner = ConcordReactRunner(
        chat_with_tools=_chat,
        verifier_fn=_verifier,
        llm_model="fake-model",
        max_feedback_iters=1,
        # feedback_strategy defaults to "cascade"
    )

    fb = runner.run_task_with_feedback(fake_task)

    # Chat must be called EXACTLY ONCE — iter-0 only.
    # Cascade iter-1 must NOT call run_task/chat.
    assert chat_call_count[0] == 1, (
        f"With feedback_strategy='cascade', chat should be called exactly once "
        f"(iter-0 only). Got {chat_call_count[0]} calls."
    )

    # Two iterations must be recorded: iter-0 (react) + iter-1 (cascade).
    assert len(fb.iterations) == 2, (
        f"Expected 2 iterations (iter-0 + cascade iter-1); got {len(fb.iterations)}"
    )


# ---------------------------------------------------------------------------
# Test 3: rewrite strategy still reachable via explicit flag
# ---------------------------------------------------------------------------


def test_rewrite_strategy_still_reachable(fake_task):
    """With feedback_strategy='rewrite', the legacy path runs: chat is called
    twice (iter-0 + iter-1 LLM rewrite)."""
    chat_call_count = [0]

    def _chat(_messages, **_kwargs):
        chat_call_count[0] += 1
        return _finalise_msg()

    # iter-0 verdict: quality > 0 so feedback triggers.
    iter0_verdict = _make_verdict_mock(supported=1, unsupported=2)
    # iter-1 verdict: improved.
    iter1_verdict = _make_verdict_mock(supported=3, unsupported=0)

    verdict_sequence = iter([iter0_verdict, iter1_verdict])

    def _verifier(_narrative, _source_report, **_kwargs):
        return next(verdict_sequence)

    runner = ConcordReactRunner(
        chat_with_tools=_chat,
        verifier_fn=_verifier,
        llm_model="fake-model",
        max_feedback_iters=1,
        feedback_strategy="rewrite",
    )

    fb = runner.run_task_with_feedback(
        fake_task,
        feedback_msg_builder=lambda _v: "Please fix unsupported claims.",
    )

    # With 'rewrite', chat must be called TWICE (iter-0 + iter-1 rewrite).
    assert chat_call_count[0] == 2, (
        f"With feedback_strategy='rewrite', chat should be called twice "
        f"(iter-0 + iter-1 LLM rewrite). Got {chat_call_count[0]} calls."
    )

    assert len(fb.iterations) == 2, (
        f"Expected 2 iterations; got {len(fb.iterations)}"
    )


# ---------------------------------------------------------------------------
# Test 4: production cascade path == experiment-harness cascade (consistency)
# ---------------------------------------------------------------------------


def test_cascade_production_corrected_claims_match_experiment_harness(fake_task):
    """The production react_runner cascade path and the validated experiment
    harness (`scripts/metagent/feedback_ab_eval.py`) must produce IDENTICAL
    corrected claims from the same iter-0 verified claims.

    Both call `apply_feedback_strategy("cascade", claims, source_report)`, whose
    deterministic `apply_cascade` is a pure function of the claims (SUPPORTED
    keep / CONTRADICTED replace / UNSUPPORTED drop / INSUFFICIENT keep / UV
    drop). This pins that the production `_run_cascade_iteration` does not
    diverge from the experiment — so the 112-task A_cascade metrics (which are
    determined by the claims, not the cosmetic weave narrative) carry over.
    """
    from concord.agent.feedback_strategies import apply_feedback_strategy

    # iter-0 verified claims covering all five cascade verdict rules.
    iter0_claims = [
        _make_verified_claim(ClaimVerdict.SUPPORTED, pathway_name="Eicosanoid synthesis"),
        _make_verified_claim(ClaimVerdict.UNSUPPORTED, pathway_name="Some Unsupported Path"),
        _make_verified_claim(ClaimVerdict.INSUFFICIENT_EVIDENCE, pathway_name="Insufficient Path"),
        _make_verified_claim(ClaimVerdict.UNVERIFIABLE_V0, pathway_name="UV Path"),
    ]

    # --- Experiment-harness call (the exact call feedback_ab_eval makes) ---
    # source_report=None: apply_cascade ignores it (pure fn of claims).
    fb_exp = apply_feedback_strategy("cascade", iter0_claims, None, llm_call=lambda _p: "")
    corrected_exp = fb_exp.corrected_claims

    # --- Production react_runner path ---
    iter0_verdict = _make_verdict_mock(claims_v2=iter0_claims)
    iter1_verdict = _make_verdict_mock(supported=3, unsupported=0)
    verdict_sequence = iter([iter0_verdict, iter1_verdict])

    runner = ConcordReactRunner(
        chat_with_tools=lambda _m, **_k: _finalise_msg(),
        verifier_fn=lambda _n, _s, **_k: next(verdict_sequence),
        llm_model="fake-model",
        max_feedback_iters=1,
    )
    base_result = ConcordReactResult(task_id="test_cascade_task")

    rk, _vk = runner._run_cascade_iteration(
        fake_task,
        prev_outcome=_outcome_wrapping(iter0_verdict),
        base_result=base_result,
        trace_id="consistency",
        k=1,
    )
    corrected_prod = rk.final_claims

    # Deterministic cascade output must be byte-for-byte identical.
    assert corrected_prod == corrected_exp, (
        "production cascade corrected claims diverge from experiment harness:\n"
        f"  production:  {corrected_prod}\n"
        f"  experiment:  {corrected_exp}"
    )
    # Sanity: SUPPORTED + INSUFFICIENT kept (2 claims), UNSUPPORTED + UV dropped.
    assert len(corrected_prod) == 2, (
        f"cascade must keep SUPPORTED + INSUFFICIENT (2), drop UNSUPPORTED + UV; "
        f"got {len(corrected_prod)} claims: {corrected_prod}"
    )
    blob = json.dumps(corrected_prod)
    assert "Eicosanoid synthesis" in blob, (
        f"cascade must preserve the SUPPORTED claim's pathway; got {corrected_prod}"
    )
    assert "Some Unsupported Path" not in blob and "UV Path" not in blob, (
        f"cascade must drop UNSUPPORTED + UV claims; got {corrected_prod}"
    )


def _outcome_wrapping(verdict):
    """Wrap a verdict object in a VerificationOutcome (ok, verdict only)."""
    from concord.agent.react_runner import VerificationOutcome

    return VerificationOutcome(ok=True, verdict=verdict, error=None)


# ---------------------------------------------------------------------------
# Test 5: cascade synthetic result must carry pathway_prediction
# ---------------------------------------------------------------------------


def test_cascade_iteration_populates_pathway_prediction(fake_task, monkeypatch):
    """REGRESSION: the synthetic ConcordReactResult from a cascade iteration
    must carry a non-None `pathway_prediction`.

    The production scorecard (`full344_pathway_scorecard.py`) reads pathway
    accuracy from `final_react_result.pathway_prediction`. Before this fix the
    cascade iteration left that field at its default (None), so every task that
    ran a cascade feedback round scored as prediction-failed — the v4 112-task
    cascade run showed exactly this: all 62 cascade-feedback tasks had
    pathway_prediction_ok=False, collapsing overall pathway accuracy from
    ~76.8% to 41%. To stay consistent with the pre-merge production contract,
    cascade must regenerate pathway_prediction via the SAME second-pass
    generator used at iter-0 (on the cascade-corrected claims + woven narrative).
    """
    sentinel = {
        "primary": {"pathway_id": "WP:WP167", "pathway_name": "Eicosanoid synthesis"},
        "alternatives": [],
        "abstain": False,
        "abstain_reason": None,
    }
    calls = {"n": 0}

    def _fake_second_pass(**_kwargs):
        calls["n"] += 1
        return dict(sentinel)

    monkeypatch.setattr(
        "concord.agent.react_runner.generate_pathway_prediction_second_pass",
        _fake_second_pass,
    )

    iter0_claims = [
        _make_verified_claim(ClaimVerdict.SUPPORTED, pathway_name="Eicosanoid synthesis"),
    ]
    iter0_verdict = _make_verdict_mock(claims_v2=iter0_claims)

    runner = ConcordReactRunner(
        chat_with_tools=lambda _m, **_k: _finalise_msg(),
        verifier_fn=lambda _n, _s, **_k: _make_verdict_mock(supported=1, unsupported=0),
        llm_model="fake-model",
        max_feedback_iters=1,
    )
    base_result = ConcordReactResult(task_id="test_cascade_task")

    rk, _vk = runner._run_cascade_iteration(
        fake_task,
        prev_outcome=_outcome_wrapping(iter0_verdict),
        base_result=base_result,
        trace_id="pp",
        k=1,
    )

    # Cascade must call the second-pass generator exactly once (on its
    # corrected claims) — before the fix it never called it.
    assert calls["n"] == 1, (
        "cascade iteration must regenerate pathway_prediction via the "
        f"second-pass generator exactly once; got {calls['n']} calls"
    )
    # The synthetic result must carry the prediction so the scorecard can read it.
    assert rk.pathway_prediction is not None, (
        "cascade synthetic ConcordReactResult must carry pathway_prediction"
    )
    assert rk.pathway_prediction["primary"]["pathway_name"] == "Eicosanoid synthesis", (
        f"cascade must store the regenerated prediction; got {rk.pathway_prediction}"
    )
