"""Stage 1 — extract atomic factual claims from a naive LLM output.

One LLM call per ``verify()`` invocation. The model is asked for a JSON
list of ``{claim_text, subject?}`` objects. Parse failures raise
:class:`ClaimExtractionError`; the verifier agent surfaces this as a
``VERIFICATION_PARSE_FAILED`` warning. **No retry** — per the Track V
brief, retries mask the failure modes the paper needs to record.

JSON parsing is done locally rather than via
``common.llm_client.extract_json_list``. The common helper uses
``rfind``-based bracket search, which corrupts results when the LLM's
claim list contains substrings like ``"[M+H]+"`` — a real phenomenon
observed on the first live-LLM integration run, where 32 well-formed
claims collapsed to 1 because ``rfind("[")`` landed inside a claim text.
Extractor-local parsing strips markdown code fences first, then falls
through standard ``json.loads`` — deterministic for this shape.
"""
from __future__ import annotations

import json
import re

from common.llm_client import chat, strip_thinking
from verifier.claim_fields import (
    infer_claim_subtype,
    normalize_claim_text,
    parse_claim_fields,
)
from verifier.prompts import extract_claims as prompts
from verifier.schemas import ExtractedClaim


_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*|\s*```$", re.MULTILINE)


def _parse_claim_list(text: str) -> list | None:
    """Parse a JSON-list-of-objects response. Returns None on failure.

    Strategy:
      1. Strip ``<think>`` chain-of-thought (via ``strip_thinking``).
      2. Strip markdown code fences (``\\`\\`\\`json ... \\`\\`\\```).
      3. ``json.loads`` the result; require a list.
      4. If still not JSON, try the first-``[``-to-last-``]`` slice.

    Step 4 uses the *outer* brackets, not ``rfind``, so a claim text
    containing ``[M+H]+`` does not corrupt the slice boundary.
    """
    text = strip_thinking(text)
    if not text:
        return None
    text = _FENCE_RE.sub("", text).strip()

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        pass

    # Fall back: first '[' to last ']' slice. Using the FIRST '[' (not
    # rfind) avoids being misled by '[M+H]+' inside a claim_text.
    i = text.find("[")
    j = text.rfind("]")
    if 0 <= i < j:
        try:
            parsed = json.loads(text[i : j + 1])
            return parsed if isinstance(parsed, list) else None
        except json.JSONDecodeError:
            pass
    return None


CALLER = "verifier.stage1.extract_claims"


# Phase 6.4: rule-based alternative extractor for Sub-6A real-id v2.
# The default LLM extractor (Opus-4-7) decomposes compound mechanistic
# phrases like "m/z 109.0648 corresponds to fragment of A-ring enone" into
# atomic sub-claims, neither of which carries both the m/z AND the
# mechanism keyword required by Layer F's regex contract
# (verifier/claim_classifier.py:107-119). The rule-based path below splits
# the narrative on sentence / bullet boundaries WITHOUT decomposing line
# content, so compound mechanistic sentences arrive at the classifier
# intact and can be routed to PEAK_MECHANISTIC.
_BULLET_RE = re.compile(r"^[\s]*(?:[-*•]\s+|\d+\.\s+)", re.MULTILINE)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def extract_claims_rulebased(llm_output: str, *, trace_id: str | None = None) -> list[ExtractedClaim]:
    """Sentence-level non-LLM extractor.

    Splits ``llm_output`` on bullet markers and sentence boundaries, then
    emits each non-trivial line as a single :class:`ExtractedClaim`. Does
    NOT atomically decompose compound phrases — the goal is to preserve
    sentence-level mechanistic statements so the rule-based classifier
    (`verifier/claim_classifier.py`) can route them to PEAK_MECHANISTIC.

    Parameters
    ----------
    llm_output : str
        The narrative text (single LLM-as-reranker output, or any free-form
        text). Empty / whitespace returns ``[]``.
    trace_id : optional, accepted for API compatibility with the LLM
        extractor but unused (this path makes no LLM calls).

    Returns
    -------
    list[ExtractedClaim]
        One claim per non-empty sentence/bullet. ``claim_text`` is the raw
        sentence; ``normalized_text`` and ``extracted_fields`` populate as
        usual via ``parse_claim_fields``.
    """
    if not llm_output or not llm_output.strip():
        return []

    # Step 1: line-level split. Bullets are the dominant structure in
    # LLM-as-reranker output (each "Peak-level claims:" entry is a bullet).
    raw_lines: list[str] = []
    for chunk in llm_output.splitlines():
        chunk = chunk.strip()
        if not chunk:
            continue
        # Strip leading bullet marker if any.
        chunk = _BULLET_RE.sub("", chunk).strip()
        if not chunk:
            continue
        raw_lines.append(chunk)

    # Step 2: sentence-level split within each line. We split only on
    # ". " followed by uppercase, so "[M+H]+" embedded in a clause stays
    # intact (the Track-V `rfind` bug analog).
    sentences: list[str] = []
    for line in raw_lines:
        parts = _SENTENCE_END_RE.split(line)
        for p in parts:
            p = p.strip()
            if len(p) >= 8:  # filter trivially short fragments
                sentences.append(p)

    # Step 3: emit ExtractedClaim per sentence. Subject is heuristic —
    # leave None and let the classifier fill via rule.
    claims: list[ExtractedClaim] = []
    for sent in sentences:
        normalized = normalize_claim_text(sent)
        fields = parse_claim_fields(sent)
        claims.append(
            ExtractedClaim(
                source_text=sent,
                claim_text=sent,
                normalized_text=normalized,
                subject=None,
                peak_mz=fields.mz,
                neutral_loss=fields.neutral_loss,
                claim_subtype=infer_claim_subtype(sent, fields),
                extracted_fields=fields,
            )
        )
    return claims


class ClaimExtractionError(RuntimeError):
    """Raised when Stage 1 cannot parse a usable claim list from the LLM.

    The agent catches this, logs a verification warning, and returns a
    ``VerifiedIdentification`` with ``overall_verdict='failed'`` rather than
    re-prompting the model.
    """


def extract_claims(llm_output: str, *, trace_id: str) -> list[ExtractedClaim]:
    """Run the Stage 1 extractor on ``llm_output``.

    Returns a list (possibly empty if the model legitimately found no
    claims, e.g. an empty input). Raises :class:`ClaimExtractionError` when
    the response cannot be parsed into the expected JSON shape.
    """
    if not llm_output.strip():
        return []

    user_msg = prompts.build(llm_output)
    response = chat(
        messages=[
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        trace_id=trace_id,
        caller=CALLER,
    )

    raw_items = _parse_claim_list(response)
    if raw_items is None:
        raise ClaimExtractionError(
            f"Stage 1 extractor produced no parseable JSON list. "
            f"First 200 chars of response: {response[:200]!r}"
        )
    if not raw_items:
        # Legitimate zero-claim response.
        return []

    claims: list[ExtractedClaim] = []
    for i, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise ClaimExtractionError(
                f"Stage 1 item {i} is not a JSON object: {item!r}"
            )
        text = item.get("claim_text")
        if not isinstance(text, str) or not text.strip():
            raise ClaimExtractionError(
                f"Stage 1 item {i} missing or empty 'claim_text': {item!r}"
            )
        subject = item.get("subject")
        if subject is not None and not isinstance(subject, str):
            # Tolerate non-string subjects by coercing to None rather than
            # failing the whole extraction — only claim_text is load-bearing.
            subject = None
        clean_text = text.strip()
        normalized = normalize_claim_text(clean_text)
        fields = parse_claim_fields(clean_text)
        claims.append(
            ExtractedClaim(
                source_text=clean_text,
                claim_text=clean_text,
                normalized_text=normalized,
                subject=subject.strip() if isinstance(subject, str) and subject.strip() else None,
                peak_mz=fields.mz,
                neutral_loss=fields.neutral_loss,
                claim_subtype=infer_claim_subtype(clean_text, fields),
                extracted_fields=fields,
            )
        )

    return claims
