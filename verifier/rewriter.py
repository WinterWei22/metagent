"""Stage 4 — rewrite the LLM output applying verifier edits.

Single-purpose module: pick out the actionable v1 claims (CONTRADICTED,
UNSUPPORTED, UNVERIFIABLE_V0), build the rewrite prompt, call the LLM
once, return the rewritten string. No re-extraction, no re-verification —
those are orchestrated by ``agent.py`` so that this module stays cheap to
test in isolation.

If no claim is actionable, ``rewrite()`` is never called by the agent —
Stage 4 short-circuits, ``rewritten_output`` equals ``source_llm_output``,
and the saved LLM call drops the verification budget by 3 (rewrite +
re-extract + re-consistency).
"""
from __future__ import annotations

from common.llm_client import chat
from verifier.prompts import rewrite_verified as prompts
from verifier.schemas import ClaimVerdict, VerifiedClaim


CALLER = "verifier.stage4.rewrite"


# Verdicts the rewriter is asked to act on. ``ERROR`` is excluded — when a
# layer raised, the agent's caller already has a verification warning;
# pretending we know how to fix the underlying claim would be dishonest.
_ACTIONABLE = {
    ClaimVerdict.CONTRADICTED,
    ClaimVerdict.UNSUPPORTED,
    ClaimVerdict.UNVERIFIABLE_V0,
}


def is_rewrite_needed(verified_claims: list[VerifiedClaim]) -> bool:
    """Return True iff Stage 4 should run.

    Pure check, no I/O. Used by the agent to decide whether to spend the
    Stage 4 LLM budget at all.
    """
    return any(c.verdict in _ACTIONABLE for c in verified_claims)


def rewrite(
    *,
    source_llm_output: str,
    verified_claims: list[VerifiedClaim],
    trace_id: str,
) -> str:
    """Run the rewrite LLM call. Returns the rewritten output string.

    Caller is responsible for checking :func:`is_rewrite_needed` first —
    invoking ``rewrite()`` with no actionable claims wastes an LLM call.
    """
    edits = [_to_edit(c) for c in verified_claims if c.verdict in _ACTIONABLE]
    if not edits:
        # Defensive — shouldn't happen if caller honoured is_rewrite_needed,
        # but we'd rather return the original than send an empty edit list.
        return source_llm_output

    user_msg = prompts.build(original_output=source_llm_output, edits=edits)
    return chat(
        messages=[
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        trace_id=trace_id,
        caller=CALLER,
    )


def _to_edit(c: VerifiedClaim) -> dict:
    """Map a VerifiedClaim onto the dict shape ``rewrite_verified.build``
    expects."""
    return {
        "claim_text": c.claim_text,
        "verdict": c.verdict.value,
        "correction": c.correction,
        "evidence": c.evidence,
    }
