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
from verifier import grammar as _grammar
from verifier.claim_fields import (
    infer_claim_subtype,
    normalize_claim_text,
    parse_claim_fields,
)
from verifier.prompts import extract_claims as prompts
from verifier.schemas import (
    ClaimExtractedFields,
    ClaimSubtype,
    DroppedClaim,
    ExtractedClaim,
)


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


# ---------------------------------------------------------------------------
# Phase B1 D2 — grammar-validated JSON extraction (zero LLM calls)
# ---------------------------------------------------------------------------


# Per-grammar mapping from v2 claim field names to ClaimExtractedFields
# field names. Used to populate ``extracted_fields`` so downstream
# Stage 2 / Stage 3 layers see the same structure they would from a
# legacy LLM extraction. Unmapped fields are kept verbatim on
# ``raw_object`` in DroppedClaim or threaded through as-is.
_GRAMMAR_TO_SUBTYPE: dict[str, ClaimSubtype] = {
    "pathway_membership": ClaimSubtype.PATHWAY_MEMBERSHIP,
    "metabolite_pathway_link": ClaimSubtype.PATHWAY_MEMBERSHIP,
    "pathway_enrichment": ClaimSubtype.ENRICHMENT_PATHWAY,
    "driver_metabolite": ClaimSubtype.DRIVER_LIST,
}


def _to_extracted_claim(claim_obj: dict) -> ExtractedClaim:
    """Convert a grammar-validated v2 claim dict to an ExtractedClaim.

    Only called *after* :func:`verifier.grammar.validate` returned
    ``is_valid=True``, so every field required by the grammar shape is
    present.

    Phase B1 D3: also stamps ``ExtractedClaim.grammar`` with the v2
    grammar enum so the downstream classifier can route directly via
    ``route_v2_claim`` without re-inferring the type.
    """
    from verifier.grammar import ClaimGrammar

    text = claim_obj["claim_text"].strip()
    grammar_str = claim_obj["grammar"]
    grammar_enum = ClaimGrammar(grammar_str)

    # Populate the downstream-visible extracted_fields. Pathway name and
    # subject are the two fields the Sub-6 verifier layers actually
    # consume (cf. verifier/layers/biological_sub6.py et al.).
    fields_kwargs: dict = {}
    pathway = claim_obj.get("pathway_name") or claim_obj.get("term_name")
    if pathway:
        fields_kwargs["pathway_name"] = pathway

    subject = claim_obj.get("subject")
    normalized = normalize_claim_text(text)

    return ExtractedClaim(
        source_text=text,
        claim_text=text,
        normalized_text=normalized,
        subject=subject.strip() if isinstance(subject, str) and subject.strip() else None,
        claim_subtype=_GRAMMAR_TO_SUBTYPE.get(grammar_str, ClaimSubtype.UNKNOWN),
        extracted_fields=ClaimExtractedFields(**fields_kwargs) if fields_kwargs else ClaimExtractedFields(),
        grammar=grammar_enum,
    )


def _try_parse_grammar_payload(text: str) -> dict | None:
    """Return the parsed dict if ``text`` is a v2 grammar JSON payload,
    else ``None``.

    The v2 contract: ``{"narrative_text": str, "claims": list[dict]}``.
    Anything missing either key or having the wrong type falls through
    to the legacy LLM extractor path so v1 callers and partial
    outputs do not regress.
    """
    if not text or not text.strip():
        return None
    candidate = strip_thinking(text)
    candidate = _FENCE_RE.sub("", candidate).strip()
    if not candidate.startswith("{"):
        return None
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    if "claims" not in obj or not isinstance(obj["claims"], list):
        return None
    return obj


def extract_claims_from_json(
    narrative_payload: str | dict,
    *,
    trace_id: str,
) -> tuple[list[ExtractedClaim], list[DroppedClaim]]:
    """Schema-validate a v2 grammar JSON payload — zero LLM calls.

    Each ``claims[]`` entry goes through
    :func:`verifier.grammar.validate`. Valid entries become
    ``ExtractedClaim`` instances; invalid entries become
    ``DroppedClaim`` instances bucketed for the
    ``dropped_by_grammar`` metric.

    ``narrative_payload`` may be the raw LLM string (the runner just
    passes ``msg["content"]``) or an already-parsed dict.

    ``trace_id`` is kept for parity with the legacy extractor signature
    so callers can swap freely. It is not used by this implementation
    because no LLM call is made.
    """
    del trace_id  # unused — kept for signature parity

    if isinstance(narrative_payload, dict):
        obj: dict | None = narrative_payload
    else:
        obj = _try_parse_grammar_payload(narrative_payload)

    if obj is None:
        raise ClaimExtractionError(
            "extract_claims_from_json received a payload that is not a "
            "v2 grammar JSON object (no 'claims' list). Caller should "
            "fall back to ``extract_claims`` (LLM path) for legacy "
            "narratives."
        )

    extracted: list[ExtractedClaim] = []
    dropped: list[DroppedClaim] = []
    for i, raw in enumerate(obj.get("claims", [])):
        if not isinstance(raw, dict):
            dropped.append(
                DroppedClaim(
                    claim_text=str(raw)[:200],
                    grammar_attempt=None,
                    drop_reason=f"claims[{i}] is not a JSON object",
                    raw_object=None,
                )
            )
            continue
        result = _grammar.validate(raw)
        if result.is_valid:
            extracted.append(_to_extracted_claim(raw))
        else:
            dropped.append(
                DroppedClaim(
                    claim_text=str(raw.get("claim_text") or "")[:500],
                    grammar_attempt=raw.get("grammar")
                    if isinstance(raw.get("grammar"), str)
                    else None,
                    drop_reason=result.drop_reason or "unknown",
                    raw_object=raw,
                )
            )
    return extracted, dropped


# ---------------------------------------------------------------------------
# Legacy LLM extractor (kept as fallback for v1 narratives + degraded paths)
# ---------------------------------------------------------------------------


def extract_claims(llm_output: str, *, trace_id: str) -> list[ExtractedClaim]:
    """Run the Stage 1 extractor on ``llm_output``.

    Phase B1 D2: if ``llm_output`` is a v2 grammar JSON object
    (recognised by :func:`_try_parse_grammar_payload`), the function
    delegates to :func:`extract_claims_from_json` and DROPS dropped
    claims silently — the legacy callers cannot see them. Callers that
    care about dropped counts must call :func:`extract_claims_from_json`
    directly and surface the dropped list themselves.

    Returns a list (possibly empty if the model legitimately found no
    claims, e.g. an empty input). Raises :class:`ClaimExtractionError`
    when the response cannot be parsed into the expected JSON shape.
    """
    # Phase B1 D2: prefer schema validation if the payload is a v2 JSON.
    obj = _try_parse_grammar_payload(llm_output)
    if obj is not None:
        valid, _dropped = extract_claims_from_json(obj, trace_id=trace_id)
        return valid
    # ---- legacy LLM-based extractor below ----
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
