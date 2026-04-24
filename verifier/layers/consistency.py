"""Layer D — detect intra-document contradictions across the claim set.

Different signature from Layers A/B/C: this layer operates on the *full*
classified-claim list rather than one claim at a time, and returns a list
of additional ``VerifiedClaim`` entries with ``claim_type=CONSISTENCY``
and ``verdict=CONTRADICTED``. The agent merges these onto the per-claim
verdicts that A/B/C produced.

Single batched LLM call. The prompt explicitly forbids flagging claims
that are merely surprising or contradicted only by external knowledge —
that is Layers A/B/C's job. This guard prevents Layer D from over-firing
on H7 (the chemistry-knowledge silicon-warning) and similar.

Parse failures are surfaced as ``verification_warnings`` (returned to
caller), not as ``ERROR`` claims, so the rewriter never has to reason
about half-broken consistency reports.
"""
from __future__ import annotations

import json

from common.llm_client import chat, extract_json_list
from verifier.prompts import check_consistency as prompts
from verifier.schemas import (
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    VerifiedClaim,
)


CALLER = "verifier.stage3.check_consistency"


def detect_consistency_contradictions(
    classified_claims: list[ClassifiedClaim],
    *,
    trace_id: str,
) -> tuple[list[VerifiedClaim], int, list[str]]:
    """Run the consistency sweep. Returns ``(claims, llm_calls, warnings)``.

    * ``claims`` — additional ``VerifiedClaim`` entries (one per
      contradiction group the LLM identified).
    * ``llm_calls`` — 0 if fewer than 2 claims (skip), 1 otherwise.
    * ``warnings`` — non-empty when the LLM response could not be parsed.
      The agent attaches these to ``VerifiedIdentification.verification_warnings``.
    """
    if len(classified_claims) < 2:
        return [], 0, []

    user_msg = prompts.build([c.claim_text for c in classified_claims])
    response = chat(
        messages=[
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        trace_id=trace_id,
        caller=CALLER,
    )

    raw_items = extract_json_list(response)
    if not raw_items:
        # Distinguish "model said []" (no contradictions, success) from
        # "could not parse" (failure).
        if response.strip().endswith("[]"):
            return [], 1, []
        return [], 1, [
            f"VERIFICATION_PARSE_FAILED at stage3 consistency: "
            f"response did not contain a parseable JSON list. "
            f"First 200 chars: {response[:200]!r}"
        ]

    out: list[VerifiedClaim] = []
    warnings: list[str] = []
    for k, item in enumerate(raw_items):
        if not isinstance(item, dict):
            warnings.append(
                f"stage3 consistency item {k} is not an object: {item!r}"
            )
            continue
        indices = item.get("claim_indices")
        if not isinstance(indices, list) or not all(
            isinstance(i, int) and 0 <= i < len(classified_claims)
            for i in indices
        ):
            warnings.append(
                f"stage3 consistency item {k} has invalid claim_indices: "
                f"{indices!r}"
            )
            continue
        if len(indices) < 2:
            warnings.append(
                f"stage3 consistency item {k} cited fewer than 2 claims: "
                f"{indices!r}"
            )
            continue
        reason = item.get("reason") or "(no reason given)"
        cited_texts = [classified_claims[i].claim_text for i in indices]
        out.append(
            VerifiedClaim(
                claim_text=(
                    "Intra-document contradiction across claims "
                    + ", ".join(f"[{i}]" for i in indices)
                ),
                claim_type=ClaimType.CONSISTENCY,
                verdict=ClaimVerdict.CONTRADICTED,
                evidence=(
                    f"Layer D reason: {reason}. Cited claim texts: "
                    + json.dumps(cited_texts, ensure_ascii=False)
                ),
                source_field=None,
                correction=None,
            )
        )
    return out, 1, warnings
