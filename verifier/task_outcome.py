"""Phase B1 D4 — task-level outcome detection.

Pure function (zero LLM calls, zero IO). Buckets a finished verifier
run into one of four ``TaskOutcome`` values so the D5 aggregator can
report NORMAL ratios without honest-refusal / system-failure tasks
polluting the denominator.

Decision rule:

    raw_present = len(verified_claims) > 0 OR len(dropped_claims) > 0
    if raw_present:                       → NORMAL
    elif narrative is empty / unparseable → EMPTY_SYSTEM_FAILURE
    elif claims field is [] AND
         narrative_text contains a refusal signal → EMPTY_HONEST_REFUSAL
    elif claims field is [] (no signal)   → EMPTY_UNKNOWN
    else (parse OK but malformed schema)  → EMPTY_SYSTEM_FAILURE

The refusal signal lexicon is intentionally short and case-insensitive
substring-only — precision matters less than recall here, since the
classifier feeds the D5 sanity table, not a feedback-control loop.
"""
from __future__ import annotations

import json
import re

from verifier.schemas import DroppedClaim, TaskOutcome, VerifiedClaim


# Substrings that flag the LLM acknowledging tool failure / lack of
# evidence in its narrative_text. Lowercased; matched as plain
# substrings in the lowercased narrative_text.
_REFUSAL_SIGNALS: tuple[str, ...] = (
    "tool_errors",  # LLM-emitted schema-extra field name (Mode B)
    "all tool calls failed",
    "tools failed",
    "unable to retrieve",
    "no enrichment results",
    "no enrichment result was returned",
    "no compound metadata was retrieved",
    "no kegg reaction graph",
    "every tool call",
    "cannot ground",
    "no anchors",
    "systematic failure",
)


_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def _has_refusal_signal(text: str) -> bool:
    """True iff ``text`` contains any refusal signal substring.

    Both the JSON envelope (where ``tool_errors`` appears as a field
    name) and the narrative_text body are scanned, so the signal does
    not have to live strictly inside narrative_text.
    """
    if not text:
        return False
    haystack = text.lower()
    return any(signal in haystack for signal in _REFUSAL_SIGNALS)


def detect_task_outcome(
    *,
    llm_output: str,
    verified_claims: list[VerifiedClaim],
    dropped_claims: list[DroppedClaim],
) -> TaskOutcome:
    """Bucket a finished verifier run into one of the four
    :class:`TaskOutcome` values. See module docstring for the rule.

    Both ``verified_claims`` and ``dropped_claims`` together represent
    "claims the LLM actually emitted that survived to the verifier" —
    if either is non-empty the LLM produced something for the verifier
    to look at, regardless of subsequent verdicts. That is the
    NORMAL signal.
    """
    if verified_claims or dropped_claims:
        return TaskOutcome.NORMAL

    candidate = _strip_fences(llm_output) if llm_output else ""
    if not candidate:
        return TaskOutcome.EMPTY_SYSTEM_FAILURE

    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return TaskOutcome.EMPTY_SYSTEM_FAILURE

    if not isinstance(obj, dict):
        return TaskOutcome.EMPTY_SYSTEM_FAILURE

    claims = obj.get("claims")
    if not isinstance(claims, list):
        # Schema malformed — no claims field at all, or wrong type.
        return TaskOutcome.EMPTY_SYSTEM_FAILURE

    if claims:
        # Claims emitted but neither verified nor dropped tracked them
        # — should be unreachable in practice (would mean the runner
        # produced a payload but never invoked the verifier extractor),
        # but treat conservatively as NORMAL since the LLM did try.
        return TaskOutcome.NORMAL

    # claims == [] — either honest refusal or unknown empty.
    if _has_refusal_signal(llm_output):
        return TaskOutcome.EMPTY_HONEST_REFUSAL
    return TaskOutcome.EMPTY_UNKNOWN
