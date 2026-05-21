"""W10 D2 P0-B — RED: default feedback builder must pass
``unverifiable=`` and ``dropped=`` kwargs to B1's ``build_feedback_message``.

The current ``concord/agent/react_runner.py:_resolve_default_feedback_builder``
extracts CONTRADICTED + UNSUPPORTED from ``claims_v1`` and calls
``build_feedback_message(contradicted=..., unsupported=..., original_narrative='')``.

B1 D4 (commit f9fe9a5 series, finalised in ed6243b) extended
``build_feedback_message`` to accept two more optional kwargs
``unverifiable=`` and ``dropped=`` so the feedback template can surface
UV claim text and grammar-dropped claim text to the next iter.
The ConcordMet side still passes neither — leaving D4's richer hints
on the table.

These three RED tests pin the contract the GREEN commit must satisfy:
  1. ``unverifiable`` kwarg → populated with UV claims from claims_v1
  2. ``dropped`` kwarg     → populated with verdict.dropped_claims
  3. Integration end-to-end: a verdict with 1 UV claim must produce a
     feedback message that says "1 UNVERIFIABLE claim".
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from concord.agent.react_runner import _resolve_default_feedback_builder
from verifier.schemas import (
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    DroppedClaim,
    SubjectKind,
    VerifiedClaim,
)


def _make_claim(claim_id: str, claim_text: str, verdict: ClaimVerdict) -> VerifiedClaim:
    """Construct a minimal VerifiedClaim with all required fields populated."""
    return VerifiedClaim(
        claim_id=claim_id,
        claim_text=claim_text,
        claim_type=ClaimType.OTHER,
        claim_subtype=ClaimSubtype.UNKNOWN,
        subject=None,
        subject_kind=SubjectKind.UNKNOWN,
        verdict=verdict,
        evidence="stub evidence for test",
    )


def _make_dropped(claim_text: str, drop_reason: str) -> DroppedClaim:
    return DroppedClaim(
        claim_text=claim_text,
        grammar_attempt="pathway_membership",
        drop_reason=drop_reason,
    )


def _verdict_stub(claims_v1, dropped_claims):
    return SimpleNamespace(claims_v1=claims_v1, dropped_claims=dropped_claims)


def test_default_feedback_builder_passes_unverifiable_from_claims_v1():
    """W10 D2 P0-B RED #1.

    When claims_v1 contains UV verdicts, the builder must forward them
    via the ``unverifiable=`` kwarg of ``build_feedback_message``.
    """
    uv_claim = _make_claim("UV1", "claim about a vague pathway", ClaimVerdict.UNVERIFIABLE_V0)
    contradicted = _make_claim("C1", "wrong formula", ClaimVerdict.CONTRADICTED)
    verdict = _verdict_stub(claims_v1=[uv_claim, contradicted], dropped_claims=[])

    builder = _resolve_default_feedback_builder()
    with patch(
        "evaluation.sub6.run_sub6b_react_feedback.build_feedback_message",
        return_value="<rendered>",
    ) as mock_build:
        builder(verdict)

    assert mock_build.called, "build_feedback_message must be invoked"
    kwargs = mock_build.call_args.kwargs
    assert "unverifiable" in kwargs, "build_feedback_message must receive 'unverifiable' kwarg"
    uvs = kwargs["unverifiable"] or []
    uv_ids = [getattr(c, "claim_id", None) for c in uvs]
    assert "UV1" in uv_ids, f"UV claim missing from unverifiable kwarg, got ids={uv_ids}"


def test_default_feedback_builder_passes_dropped_from_verdict():
    """W10 D2 P0-B RED #2.

    When verdict.dropped_claims is non-empty, the builder must forward
    them via the ``dropped=`` kwarg of ``build_feedback_message``.
    """
    dropped = [
        _make_dropped("unrecognised shape", "grammar.unknown_shape"),
        _make_dropped("missing claim_text", "grammar.missing_claim_text"),
    ]
    verdict = _verdict_stub(claims_v1=[], dropped_claims=dropped)

    builder = _resolve_default_feedback_builder()
    with patch(
        "evaluation.sub6.run_sub6b_react_feedback.build_feedback_message",
        return_value="<rendered>",
    ) as mock_build:
        builder(verdict)

    kwargs = mock_build.call_args.kwargs
    assert "dropped" in kwargs, "build_feedback_message must receive 'dropped' kwarg"
    drops = kwargs["dropped"] or []
    assert len(drops) == 2, f"expected 2 dropped claims forwarded, got {len(drops)}"
    drop_texts = [getattr(d, "claim_text", None) for d in drops]
    assert "unrecognised shape" in drop_texts
    assert "missing claim_text" in drop_texts


def test_default_feedback_builder_emits_unverifiable_hint_when_present():
    """W10 D2 P0-B RED #3.

    Integration check: a verdict with 1 UV claim must produce a feedback
    message containing the template line ``1 UNVERIFIABLE claim(s)``.
    Mirrors B1 D4's behavioural contract; surfaces in iter ≥ 1 prompts.
    """
    uv_claim = _make_claim("UV-int1", "pathway claim too vague", ClaimVerdict.UNVERIFIABLE_V0)
    verdict = _verdict_stub(claims_v1=[uv_claim], dropped_claims=[])

    builder = _resolve_default_feedback_builder()
    out = builder(verdict)

    assert "1 UNVERIFIABLE" in out, (
        "feedback prompt must report n_unverifiable=1 when one UV claim is "
        f"present in claims_v1. Output was:\n{out[:500]}"
    )
