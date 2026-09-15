"""Phase B1 D4 unit suite — TaskOutcome detection, dispatcher
deprecation warnings, feedback hint per-drop_reason templates,
two-layer retry, task-level timeout, and the UNV-not-neutral
regression.

These tests are pure-Python (no LLM, no network). The smoke that
runs the full pipeline against MiniMax lives outside the pytest
suite — see ``data/eval/sub6/b1_d4_smoke/``.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from verifier import feedback_hints
from verifier.feedback_hints import (
    _NEUTRAL_VERDICTS,
    generate_drop_hint,
    generate_feedback_hint,
    generate_refusal_hint,
)
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    DroppedClaim,
    SubjectKind,
    TaskOutcome,
    VerifiedClaim,
)
from verifier.task_outcome import detect_task_outcome


# ---------------------------------------------------------------------------
# Helpers — minimal VerifiedClaim factory
# ---------------------------------------------------------------------------


def _vc(
    text: str = "x",
    *,
    verdict: ClaimVerdict = ClaimVerdict.SUPPORTED,
    claim_type: ClaimType = ClaimType.BIOLOGICAL,
    grammar=None,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_text=text,
        claim_type=claim_type,
        claim_subtype=ClaimSubtype.UNKNOWN,
        subject=None,
        subject_kind=SubjectKind.UNKNOWN,
        candidate_ref=None,
        verdict=verdict,
        evidence="",
        extracted_fields=ClaimExtractedFields(),
        verifier_layer="test",
        trace_summary="test",
    )


# ---------------------------------------------------------------------------
# 1. TaskOutcome detection — 4 cases
# ---------------------------------------------------------------------------


def test_outcome_normal_when_claims_present() -> None:
    out = detect_task_outcome(
        llm_output="anything",
        verified_claims=[_vc()],
        dropped_claims=[],
    )
    assert out is TaskOutcome.NORMAL


def test_outcome_normal_when_dropped_present() -> None:
    """Even if every claim was grammar-dropped, the LLM did emit and
    the run is NORMAL (not refusal / system failure)."""
    dropped = DroppedClaim(claim_text="x", drop_reason="banned hedge: may")
    out = detect_task_outcome(
        llm_output='{"narrative_text":"x","claims":[]}',
        verified_claims=[],
        dropped_claims=[dropped],
    )
    assert out is TaskOutcome.NORMAL


def test_outcome_empty_system_failure_when_unparseable() -> None:
    out = detect_task_outcome(
        llm_output="not json at all",
        verified_claims=[],
        dropped_claims=[],
    )
    assert out is TaskOutcome.EMPTY_SYSTEM_FAILURE


def test_outcome_empty_system_failure_when_empty_string() -> None:
    out = detect_task_outcome(
        llm_output="",
        verified_claims=[],
        dropped_claims=[],
    )
    assert out is TaskOutcome.EMPTY_SYSTEM_FAILURE


def test_outcome_empty_honest_refusal_with_signal() -> None:
    payload = json.dumps({
        "tool_errors": ["RaMP unreachable"],
        "narrative_text": "All tool calls failed; no enrichment results obtained.",
        "claims": [],
    })
    out = detect_task_outcome(
        llm_output=payload, verified_claims=[], dropped_claims=[],
    )
    assert out is TaskOutcome.EMPTY_HONEST_REFUSAL


def test_outcome_empty_unknown_when_no_signal() -> None:
    payload = json.dumps({
        "narrative_text": "Some prose without any specific refusal language.",
        "claims": [],
    })
    out = detect_task_outcome(
        llm_output=payload, verified_claims=[], dropped_claims=[],
    )
    assert out is TaskOutcome.EMPTY_UNKNOWN


# ---------------------------------------------------------------------------
# 2. UNV is no longer neutral (D4 regression guard)
# ---------------------------------------------------------------------------


def test_unverifiable_v0_not_in_neutral_verdicts() -> None:
    assert ClaimVerdict.UNVERIFIABLE_V0 not in _NEUTRAL_VERDICTS, (
        "UNV must be removed from _NEUTRAL_VERDICTS so D4 hint generation "
        "fires. (Phase B1 D4 design decision.)"
    )


def test_generate_feedback_hint_returns_text_for_unverifiable() -> None:
    """The legacy code returned None for UNV; D4 returns a real hint."""
    claim = _vc(
        text="abstract single-compound regulatory claim",
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        claim_type=ClaimType.OTHER,
    )
    hint = generate_feedback_hint(claim)
    assert hint is not None
    assert "OTHER" in hint or "abstract" in hint.lower() or "rewrite" in hint.lower()


# ---------------------------------------------------------------------------
# 3. Per-drop_reason hint templates — 8 categories minimum
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "drop_reason, expected_substr",
    [
        ("banned hedge: 'may'", "speculative"),
        ("banned directional: 'upstream'", "direction"),
        ("banned abstract: 'cascade'", "abstract"),
        ("banned meta: 'limited to'", "limitations"),
        ("banned tool-roundtrip pattern: \\bC\\d{5}\\b", "structured field"),
        ("required field 'pathway_name' missing", "Provide"),
        ("schema validation failed: oh no", "schema"),
        ("grammar='fancy_new_shape' is not a valid ClaimGrammar value", "4 allowed"),
        ("claim_text missing or empty", "claim_text"),
    ],
)
def test_drop_hint_template_matches_each_drop_reason(
    drop_reason: str, expected_substr: str,
) -> None:
    dropped = DroppedClaim(
        claim_text="X via Y",
        grammar_attempt="metabolite_pathway_link",
        drop_reason=drop_reason,
    )
    hint = generate_drop_hint(dropped)
    assert expected_substr.lower() in hint.lower(), (
        f"hint for drop_reason={drop_reason!r} did not contain "
        f"{expected_substr!r}; got: {hint}"
    )


def test_drop_hint_fallback_for_unknown_reason() -> None:
    dropped = DroppedClaim(
        claim_text="weird claim",
        drop_reason="entirely unrecognised reason from a future check",
    )
    hint = generate_drop_hint(dropped)
    assert "weird claim" in hint
    assert "4 grammar shapes" in hint


# ---------------------------------------------------------------------------
# 4. Mode B refusal hint — task-level
# ---------------------------------------------------------------------------


def test_refusal_hint_is_static_and_actionable() -> None:
    hint = generate_refusal_hint()
    # Sanity: actionable bullet points present, not generic apology.
    assert "query_ramp_enrichment" in hint
    assert "query_kegg_path" in hint
    assert "do not fabricate" in hint.lower()


# ---------------------------------------------------------------------------
# 5. Sub-6 dispatcher — v1 legacy types still produce UNV (regression),
#    and v2 path with surprising type emits a deprecation warning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim_type",
    [
        ClaimType.GROUNDED,
        ClaimType.FACTUAL,
        ClaimType.LITERATURE,
        ClaimType.PEAK_MECHANISTIC,
    ],
)
def test_v2_path_legacy_type_emits_deprecation_warning(
    claim_type: ClaimType, caplog: pytest.LogCaptureFixture,
) -> None:
    """Constructing a ClassifiedClaim with both ``grammar`` set
    (v2 path) and a v1 ``claim_type`` should fire the deprecation
    warning when the dispatcher inspects it."""
    from verifier.agent import _maybe_warn_v1_legacy_in_v2_path
    from verifier.grammar import ClaimGrammar
    from verifier.schemas import ClassifiedClaim

    c = ClassifiedClaim(
        claim_id="test_dep",
        claim_text="x",
        claim_type=claim_type,
        classifier_source="rule",
        grammar=ClaimGrammar.PATHWAY_MEMBERSHIP,
    )
    with caplog.at_level(logging.WARNING, logger="verifier.agent"):
        _maybe_warn_v1_legacy_in_v2_path(c, where="test")
    assert any(
        "v1 legacy claim_type" in r.message for r in caplog.records
    ), f"expected deprecation warning for {claim_type.value}; got {caplog.records}"


def test_v2_path_expected_type_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A ``ClassifiedClaim`` with grammar=PATHWAY_MEMBERSHIP +
    claim_type=BIOLOGICAL is the expected v2 mapping — no warning."""
    from verifier.agent import _maybe_warn_v1_legacy_in_v2_path
    from verifier.grammar import ClaimGrammar
    from verifier.schemas import ClassifiedClaim

    c = ClassifiedClaim(
        claim_id="test_ok",
        claim_text="x",
        claim_type=ClaimType.BIOLOGICAL,
        classifier_source="rule",
        grammar=ClaimGrammar.PATHWAY_MEMBERSHIP,
    )
    with caplog.at_level(logging.WARNING, logger="verifier.agent"):
        _maybe_warn_v1_legacy_in_v2_path(c, where="test")
    assert not any(
        "v1 legacy claim_type" in r.message for r in caplog.records
    ), "v2-path claim with expected type should NOT warn"


def test_v1_legacy_path_no_grammar_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A ``ClassifiedClaim`` with ``grammar=None`` (v1 legacy path)
    is allowed to have any v1 type — no warning."""
    from verifier.agent import _maybe_warn_v1_legacy_in_v2_path
    from verifier.schemas import ClassifiedClaim

    c = ClassifiedClaim(
        claim_id="legacy",
        claim_text="x",
        claim_type=ClaimType.GROUNDED,
        classifier_source="rule",
        grammar=None,
    )
    with caplog.at_level(logging.WARNING, logger="verifier.agent"):
        _maybe_warn_v1_legacy_in_v2_path(c, where="test")
    assert not any(
        "v1 legacy claim_type" in r.message for r in caplog.records
    )


# ---------------------------------------------------------------------------
# 6. Inner retry — Mode A trigger + budget = 1
# ---------------------------------------------------------------------------


def test_inner_retry_helper_recognises_invalid_payload() -> None:
    from evaluation.sub6.run_sub6b_react import _is_valid_json_payload
    assert _is_valid_json_payload("") is False
    assert _is_valid_json_payload("not json") is False
    assert _is_valid_json_payload('{"narrative_text":"x"}') is False  # no claims field
    assert _is_valid_json_payload('{"claims":[]}') is True
    assert _is_valid_json_payload('{"narrative_text":"x","claims":[]}') is True


def test_inner_retry_fires_once_then_propagates_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive ``run_sub6b_react`` with a chat_with_tools_fn that always
    yields an empty content message — the runner should:
      1. exhaust ReAct loop with no narrative
      2. issue ONE finalise call (also empty)
      3. issue ONE inner-retry finalise (also empty)
      4. give up with ``inner_retry_used=True`` and a non-None error
    and NOT loop forever."""
    from evaluation.sub6 import run_sub6b_react

    finalise_calls: list[dict] = []

    def _empty_finalise(*args: Any, **kwargs: Any) -> dict:
        finalise_calls.append(kwargs)
        return {"role": "assistant", "content": "", "tool_calls": []}

    def _empty_react(*args: Any, **kwargs: Any) -> dict:
        # ReAct turn returns assistant with no content + no tool_calls,
        # so the loop sets narrative="" and breaks immediately.
        return {"role": "assistant", "content": "", "tool_calls": []}

    task = {"task_id": "t_inner_retry",
            "differential_metabolites": [{"name": "A"}]}
    res = run_sub6b_react.run_sub6b_react(
        task,
        chat_with_tools_fn=_empty_react,
        finalise_chat_fn=_empty_finalise,
        max_turns=2,
        total_timeout=5.0,
    )
    # The finalise pass fires (because narrative is empty after the
    # main loop) and the inner retry fires once on top → 2 finalise calls.
    assert len(finalise_calls) == 2, (
        f"expected exactly 1 finalise + 1 inner retry; got "
        f"{len(finalise_calls)} calls"
    )
    assert res.inner_retry_used is True
    assert res.error == "empty_narrative_after_finalise"
    assert res.narrative == ""


def test_inner_retry_skipped_when_finalise_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the very first finalise call returns valid JSON, the inner
    retry must NOT fire (budget is preserved for genuine failures)."""
    from evaluation.sub6 import run_sub6b_react

    n = {"finalise_calls": 0}

    def _good_finalise(*args: Any, **kwargs: Any) -> dict:
        n["finalise_calls"] += 1
        return {
            "role": "assistant",
            "content": '{"narrative_text":"ok","claims":[]}',
            "tool_calls": [],
        }

    def _empty_react(*args: Any, **kwargs: Any) -> dict:
        return {"role": "assistant", "content": "", "tool_calls": []}

    task = {"task_id": "t_no_retry",
            "differential_metabolites": [{"name": "A"}]}
    res = run_sub6b_react.run_sub6b_react(
        task,
        chat_with_tools_fn=_empty_react,
        finalise_chat_fn=_good_finalise,
        max_turns=2,
        total_timeout=5.0,
    )
    assert n["finalise_calls"] == 1
    assert res.inner_retry_used is False
    assert "claims" in res.narrative


# ---------------------------------------------------------------------------
# 7. Task-level wall timeout — observable, no raise
# ---------------------------------------------------------------------------


def test_task_total_timeout_returns_empty_no_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting task_total_timeout=0 should bypass finalise on the very
    first iteration and return a result with empty narrative + a
    ``task_total_timeout`` error tag — never raising."""
    from evaluation.sub6 import run_sub6b_react

    def _empty_react(*args: Any, **kwargs: Any) -> dict:
        # End the ReAct loop immediately by returning no tool_calls and
        # empty content.
        return {"role": "assistant", "content": "", "tool_calls": []}

    task = {"task_id": "t_task_timeout",
            "differential_metabolites": [{"name": "A"}]}
    res = run_sub6b_react.run_sub6b_react(
        task,
        chat_with_tools_fn=_empty_react,
        finalise_chat_fn=_empty_react,  # would never be called
        max_turns=2,
        total_timeout=5.0,
        task_total_timeout=0.0,  # Phase B1 D4 — force-trip the guard
    )
    assert res.narrative == ""
    assert res.error and "task_total_timeout" in res.error
    assert res.inner_retry_used is False


# ---------------------------------------------------------------------------
# 7b. D5 hotfix: feedback runner _react_loop also fires the inner retry
# ---------------------------------------------------------------------------


def test_feedback_react_loop_fires_inner_retry_on_empty_finalise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase B1 D5 surfaced 13 EMPTY_SYSTEM_FAILURE / seed-0 because the
    D4 inner-retry only landed in ``run_sub6b_react.run_sub6b_react``
    and the feedback runner uses its own ``_react_loop``. This test
    locks the hotfix: with empty react + empty finalise, the feedback
    runner's ``_react_loop`` must issue ONE retry of the finalise
    turn and then propagate ``empty_narrative_after_finalise``."""
    from evaluation.sub6 import run_sub6b_react_feedback as fr

    finalise_calls: list[dict] = []

    def _empty_finalise(*args: Any, **kwargs: Any) -> dict:
        finalise_calls.append(kwargs)
        return {"role": "assistant", "content": "", "tool_calls": []}

    def _react_with_tool_then_empty(*args: Any, **kwargs: Any) -> dict:
        # Make turn 1 emit a tool_call so the loop progresses; later
        # turns emit empty content so the loop sets narrative=""
        # and the finalise pass triggers. We just always return empty
        # tool_calls to keep this simple — the loop exits on turn 1
        # with empty narrative, the finalise pass fires, then the
        # retry fires.
        return {"role": "assistant", "content": "", "tool_calls": []}

    # Sentinel for "this run actually flipped the inner-retry tripwire"
    # — the helper writes it on the function attribute.
    if hasattr(fr._react_loop, "_last_inner_retry"):
        fr._react_loop._last_inner_retry = False

    narrative, _tool_log, n_turns, _tc, force_fin, err, _msgs = fr._react_loop(
        messages=[{"role": "user", "content": "start"}],
        chat_with_tools_fn=_react_with_tool_then_empty,
        finalise_chat_fn=_empty_finalise,
        model="MiniMax-M2.7-highspeed",
        provider="minimax",
        temperature=0.0,
        max_turns=2,
        deadline=__import__("time").perf_counter() + 30.0,
        trace_id="test_d5_hotfix",
        caller="test_d5_hotfix",
    )
    # Finalise pass + 1 inner retry → exactly 2 finalise_chat_fn calls
    assert len(finalise_calls) == 2, (
        f"Expected 1 finalise + 1 inner retry; got {len(finalise_calls)} "
        f"finalise_chat_fn calls. Hotfix not wired."
    )
    assert err == "empty_narrative_after_finalise"
    assert narrative == ""
    assert force_fin is True
    # Tripwire attribute set by the hotfix logic
    assert getattr(fr._react_loop, "_last_inner_retry", False) is True


# ---------------------------------------------------------------------------
# 8. Mode B does NOT count grammar-dropped claims toward quality
# ---------------------------------------------------------------------------


def test_quality_score_counts_contra_unsup_and_unv() -> None:
    """Phase B1 P0 fix (2026-05-18): quality = n_contradicted +
    n_unsupported + n_unverifiable_v0.

    D4 commit 39c4272 removed UV from ``_NEUTRAL_VERDICTS`` (UV is
    actionable — feedback hints tell the LLM to rewrite or omit it).
    But ``_quality_score`` was left with the pre-D4 formula, so:

    1. The post-iteration exit ``if q == 0: break`` treated UV-only
       iterations as "nothing more to fix" and exited the feedback
       loop early.
    2. ``_select_final_iteration`` rolled back to (or held) iters with
       fewer contra+unsup but more UV, even though those UVs are
       material defects.

    Grammar-dropped claims (DroppedClaim) are tracked separately and
    deliberately NOT in quality — counting them would tempt the LLM
    to write fewer claims to lower the score.
    """
    from evaluation.sub6.run_sub6b_react_feedback import _quality_score

    # The P0 spec assertion: UV-only iteration is NOT quality==0.
    quality, _, _, _ = _quality_score(
        {"supported": 10, "unverifiable_v0": 1}
    )
    assert quality == 1, "UV must count toward quality (P0 fix)"

    # Mixed: contra+unsup+UV should all roll up.
    quality, n_c, n_u, n_s = _quality_score(
        {
            "supported": 5,
            "contradicted": 1,
            "unsupported": 2,
            "unverifiable_v0": 3,
        }
    )
    assert quality == 1 + 2 + 3 == 6
    assert n_c == 1
    assert n_u == 2
    assert n_s == 5

    # All-supported is still quality == 0.
    quality, _, _, _ = _quality_score({"supported": 8})
    assert quality == 0

    # Empty verdict_total degrades gracefully.
    quality, n_c, n_u, n_s = _quality_score({})
    assert (quality, n_c, n_u, n_s) == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# 9. build_feedback_message wires the new placeholders without KeyError
# ---------------------------------------------------------------------------


def test_build_feedback_message_handles_d1_placeholders() -> None:
    """Regression guard: the D1 commit added 5 new placeholders to the
    feedback prompt; D4 must wire them or build_feedback_message
    raises KeyError. This was actually broken between D1 commit and
    D4 — see status file Anomaly entry."""
    from evaluation.sub6.run_sub6b_react_feedback import (
        build_feedback_message,
    )
    msg = build_feedback_message(
        contradicted=[],
        unsupported=[],
        original_narrative="prev narrative",
        unverifiable=[],
        dropped=[],
    )
    # Must contain the headers we expect from the new template.
    assert "UNVERIFIABLE" in msg.upper()
    assert "DROPPED-BY-GRAMMAR" in msg.upper() or "dropped" in msg.lower()
    assert "prev narrative" in msg


# ---------------------------------------------------------------------------
# 10. grammar field passthrough — VerifiedClaim must carry ClassifiedClaim.grammar
# ---------------------------------------------------------------------------


def test_grammar_field_passthrough_to_verified() -> None:
    """Phase B1 P0 Stage D regression — verifier.agent's dispatcher
    centrally stamps ``ClassifiedClaim.grammar`` onto each
    ``VerifiedClaim`` so per-grammar metric aggregation (distinguishing
    ``pathway_membership`` from ``metabolite_pathway_link``, both of
    which collapse to ``ClaimType.BIOLOGICAL``) does not have to
    round-trip through ``ExtractedClaim``.

    Was followup_debt P0 #1: VerifiedClaim.grammar was always None
    because (a) the field didn't exist on VerifiedClaim, and (b) layers
    construct VerifiedClaim from scratch without knowing about grammar.
    Fix adds the field + centralised dispatcher-level stamp helper.
    """
    from verifier.agent import _stamp_grammar_from_classified
    from verifier.grammar import ClaimGrammar
    from verifier.schemas import (
        ClaimExtractedFields,
        ClaimProvenance,
        ClaimType,
        ClaimVerdict,
        ClassifiedClaim,
        VerifiedClaim,
    )

    # 1) v2-grammar claim → grammar must propagate
    c = ClassifiedClaim(
        claim_id="t1",
        claim_text="Lysine is a member of Lysine degradation",
        claim_type=ClaimType.BIOLOGICAL,
        extracted_fields=ClaimExtractedFields(),
        provenance=ClaimProvenance(),
        classifier_source="rule",
        grammar=ClaimGrammar.PATHWAY_MEMBERSHIP,
    )
    v = VerifiedClaim(
        claim_text=c.claim_text,
        claim_type=c.claim_type,
        verdict=ClaimVerdict.SUPPORTED,
        evidence="RaMP lookup ok",
    )
    assert v.grammar is None, "pre-stamp must be None"
    stamped = _stamp_grammar_from_classified([v], [c])
    assert stamped[0].grammar == ClaimGrammar.PATHWAY_MEMBERSHIP

    # 2) v1 claim (no grammar) → must stay None
    c_legacy = ClassifiedClaim(
        claim_id="t2",
        claim_text="legacy",
        claim_type=ClaimType.BIOLOGICAL,
        extracted_fields=ClaimExtractedFields(),
        provenance=ClaimProvenance(),
        classifier_source="rule",
        grammar=None,
    )
    v_legacy = VerifiedClaim(
        claim_text="legacy",
        claim_type=ClaimType.BIOLOGICAL,
        verdict=ClaimVerdict.SUPPORTED,
        evidence="x",
    )
    stamped_legacy = _stamp_grammar_from_classified([v_legacy], [c_legacy])
    assert stamped_legacy[0].grammar is None

    # 3) Different v2 grammars route correctly (distinguishes membership vs link)
    c_link = c.model_copy(update={"grammar": ClaimGrammar.METABOLITE_PATHWAY_LINK})
    v_link = v.model_copy(update={"claim_text": "link"})
    stamped_link = _stamp_grammar_from_classified([v_link], [c_link])
    assert stamped_link[0].grammar == ClaimGrammar.METABOLITE_PATHWAY_LINK
    # Mixed: both should land with their own grammar in one batch
    mixed = _stamp_grammar_from_classified([v, v_legacy, v_link], [c, c_legacy, c_link])
    assert mixed[0].grammar == ClaimGrammar.PATHWAY_MEMBERSHIP
    assert mixed[1].grammar is None
    assert mixed[2].grammar == ClaimGrammar.METABOLITE_PATHWAY_LINK
