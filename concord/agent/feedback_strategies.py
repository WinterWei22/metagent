"""Strategy A: deterministic cascade claim processing (feedback-redesign Task 1+2).

GeneAgent-style: instead of letting the LLM rewrite claims freely (which
net-degrades quality as shown in W13.C / W14.B), the system deterministically
processes iter-0 verified claims by verdict and rebuilds them as grammar-v2
claim dicts that can be re-ingested by verify_sub6's zero-LLM path.

The LLM only weaves narrative after this deterministic filter — it never
decides which claims survive.

Verdict routing
---------------
SUPPORTED              → keep (rebuild as grammar-v2 dict)
INSUFFICIENT_EVIDENCE  → keep (verifier had right shape, data absent; LLM
                         wrote something plausible; preserve for renarration)
CONTRADICTED           → keep BUT replace pathway_name with claim.correction
                         (top-1 from multisource pool); if correction is
                         empty/None/whitespace → downgrade to drop
UNSUPPORTED            → drop
UNVERIFIABLE_V0        → drop
NEEDS_HUMAN_REVIEW     → drop (not in spec table; treat like UV — out-of-scope
                         for deterministic fix; note: VerifiedClaim.verdict is
                         a string enum so this value must be handled explicitly)
ERROR                  → drop (system failure; do not propagate)

Grammar-v2 dict keys used by _to_extracted_claim (verifier/claim_extractor.py):
  Required:
    "grammar"       — str, value of ClaimGrammar enum (e.g. "pathway_membership")
    "claim_text"    — str, verbatim sentence
  Consumed when present:
    "pathway_name"  — str | None (OR "term_name" as fallback in _to_extracted_claim)
    "subject"       — str | None
  Grammar-specific required fields (for verifier.grammar.validate to pass):
    pathway_membership:        subject, pathway_name
    metabolite_pathway_link:   subject, pathway_name, enzyme_or_reaction
    pathway_enrichment:        term_id, term_name, term_type
    driver_metabolite:         subject, pathway_name, signal_compound_ids

M1 fix (Task 2):
  pathway_enrichment claims require term_id / term_name / term_type in the
  grammar-v2 dict. These are NOT stored in ClaimExtractedFields by
  _to_extracted_claim (it only stores pathway_name there). Without explicit
  reconstruction, grammar.validate rejects the rebuilt dict and
  extract_claims_from_json silently drops the claim.

  Fix: _rebuild_grammar_v2_dict detects grammar=PATHWAY_ENRICHMENT and
  injects term_id / term_name / term_type sourced from:
    term_name  → extracted_fields.pathway_name (mapped by _to_extracted_claim)
    term_id    → enrichment_context.claimed_pathway_id (set by layer 6a)
                 OR extracted_fields.pathway_id (fallback)
    term_type  → "pathway" default (only value produced by the reactive runner;
                 no storage path exists in VerifiedClaim for the original value)

Task 2 public API:
  build_cascade_payload(corrected_claims, narrative_text) → str
    Wraps the corrected_claims list into the grammar-v2 JSON object
    {"narrative_text": ..., "claims": [...]} that verify_sub6 consumes
    via its zero-LLM extract_claims_from_json path.

This module is NEW code (✅ add-only per verifier modification policy).
Do NOT import from or modify B1-core helpers.
"""
from __future__ import annotations

import json

from verifier.grammar import ClaimGrammar
from verifier.schemas import ClaimVerdict, VerifiedClaim

# Verdicts that cause a claim to be kept (before correction logic).
_KEEP_VERDICTS = frozenset(
    [
        ClaimVerdict.SUPPORTED,
        ClaimVerdict.INSUFFICIENT_EVIDENCE,
        ClaimVerdict.CONTRADICTED,
    ]
)

# Verdicts that cause a claim to be unconditionally dropped.
_DROP_VERDICTS = frozenset(
    [
        ClaimVerdict.UNSUPPORTED,
        ClaimVerdict.UNVERIFIABLE_V0,
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
        ClaimVerdict.ERROR,
    ]
)


def _rebuild_grammar_v2_dict(claim: VerifiedClaim, *, pathway_name_override: str | None = None) -> dict:
    """Rebuild a VerifiedClaim into a grammar-v2 claim dict.

    The dict is shaped so that:
    1. ``verifier.claim_extractor._to_extracted_claim`` can parse it without
       error (the zero-LLM path in verify_sub6).
    2. ``verifier.grammar.validate`` passes for the four supported grammar
       shapes (pathway_membership / metabolite_pathway_link /
       pathway_enrichment / driver_metabolite).

    Strategy: start from the minimal set of keys that _to_extracted_claim
    consumes, then carry forward any extra keys from the claim's
    extracted_fields so grammar-specific required fields survive.

    Parameters
    ----------
    claim:
        The VerifiedClaim to rebuild.
    pathway_name_override:
        When provided (CONTRADICTED correction path), replaces the
        pathway_name in extracted_fields with this value.
    """
    # grammar value — ClaimGrammar enum → string value
    grammar_str: str | None = None
    if claim.grammar is not None:
        grammar_str = claim.grammar.value

    # claim_text is load-bearing; must never be None (VerifiedClaim.claim_text
    # is required, so this is always a str in practice).
    claim_text = claim.claim_text

    # pathway_name: use override if supplied (CONTRADICTED correction),
    # else fall back to extracted_fields.
    pathway_name = (
        pathway_name_override
        if pathway_name_override is not None
        else (claim.extracted_fields.pathway_name if claim.extracted_fields else None)
    )

    # pathway_id: carry forward for verifier layer lookups.
    pathway_id = claim.extracted_fields.pathway_id if claim.extracted_fields else None

    # subject: carry forward for grammar shapes that require it.
    subject = claim.subject

    d: dict = {
        "grammar": grammar_str,
        "claim_text": claim_text,
        "pathway_name": pathway_name,
        "pathway_id": pathway_id,
        "subject": subject,
    }

    # Carry forward any extra extracted_fields that grammar shapes need
    # (e.g. driver_metabolite needs signal_compound_ids;
    #  metabolite_pathway_link needs enzyme_or_reaction).
    # We do this by inspecting the Pydantic model's __fields__ to avoid
    # hard-coding every field name — forward-compatible as the schema grows.
    if claim.extracted_fields:
        for field_name, field_value in claim.extracted_fields.model_dump(exclude_none=True).items():
            if field_name not in d:
                d[field_name] = field_value

    # M1 fix: pathway_enrichment requires term_id / term_name / term_type in
    # the rebuilt dict, but _to_extracted_claim only stores pathway_name
    # (mapped from term_name) in ClaimExtractedFields. Reconstruct the three
    # required fields from wherever VerifiedClaim actually carries them.
    if claim.grammar == ClaimGrammar.PATHWAY_ENRICHMENT:
        # term_name: extracted_fields.pathway_name holds this (set by
        # _to_extracted_claim's fallback: pathway = claim_obj.get("pathway_name")
        # or claim_obj.get("term_name")).
        if "term_name" not in d or not d["term_name"]:
            d["term_name"] = pathway_name or ""

        # term_id: enrichment_context.claimed_pathway_id is set by layer 6a
        # (set_enrichment) from the original claim dict's term_id.
        # Fall back to extracted_fields.pathway_id (less reliable; pathway_id
        # key in ClaimExtractedFields holds the KEGG/RaMP path ID when the
        # layer stored it explicitly).
        if "term_id" not in d or not d["term_id"]:
            ctx = claim.enrichment_context
            claimed_id = (ctx.claimed_pathway_id if ctx else None) or pathway_id
            d["term_id"] = claimed_id or ""

        # term_type: not stored anywhere in VerifiedClaim; default to "pathway"
        # (the only value the reactive runner ever produces for enrichment claims;
        # the RaMP wrapper only returns pathway-type enrichment results).
        if "term_type" not in d or not d["term_type"]:
            d["term_type"] = "pathway"

    return d


def apply_cascade(verified_claims: list[VerifiedClaim]) -> list[dict]:
    """Deterministically process iter-0 verified claims by verdict.

    Parameters
    ----------
    verified_claims:
        The list of VerifiedClaim objects from one verifier pass.

    Returns
    -------
    list[dict]
        Grammar-v2 claim dicts for claims that survived the cascade.
        Each dict can be fed directly to ``extract_claims_from_json``
        (via a ``{"narrative_text": ..., "claims": [...]}`` wrapper) so
        verify_sub6 re-verifies them without an LLM round-trip.
    """
    kept: list[dict] = []

    for claim in verified_claims:
        verdict = claim.verdict

        if verdict in _DROP_VERDICTS:
            continue

        if verdict == ClaimVerdict.SUPPORTED or verdict == ClaimVerdict.INSUFFICIENT_EVIDENCE:
            kept.append(_rebuild_grammar_v2_dict(claim))

        elif verdict == ClaimVerdict.CONTRADICTED:
            # Downgrade to drop if correction is absent or whitespace-only.
            correction = claim.correction
            if not correction or not correction.strip():
                continue
            # Replace pathway_name with the top-1 correction from the
            # multisource pool, as specified in Task 1 brief.
            kept.append(_rebuild_grammar_v2_dict(claim, pathway_name_override=correction.strip()))

        # Any other verdict not explicitly mapped (defensive): drop.

    return kept


def build_cascade_payload(
    corrected_claims: list[dict],
    narrative_text: str,
) -> str:
    """Wrap corrected grammar-v2 claim dicts into a verify_sub6-consumable payload.

    Parameters
    ----------
    corrected_claims:
        List of grammar-v2 claim dicts as returned by ``apply_cascade``.
        Each dict must carry the keys required by
        ``verifier.grammar.validate`` for its grammar shape.
    narrative_text:
        The human-facing narrative string. When the cascade is used for
        pure re-verification (no LLM renarration), pass the original
        iter-0 narrative. When an LLM rewrites the narrative using the
        corrected claims, pass the new narrative.

    Returns
    -------
    str
        JSON string ``{"narrative_text": ..., "claims": [...]}`` that
        ``verify_sub6`` consumes via its zero-LLM
        ``extract_claims_from_json`` path (triggered when the payload
        parses as a v2 grammar JSON object).

    Notes
    -----
    The payload format follows the B1 D2 grammar-v2 contract defined in
    ``verifier/claim_extractor.py:_try_parse_grammar_payload``.
    ``extract_claims_from_json`` requires:
      - Top-level dict with ``"claims"`` key holding a list.
      - ``"narrative_text"`` key (consumed by verify_sub6 for the
        ``source_llm_output`` / ``rewritten_output`` fields).
    """
    payload = {
        "narrative_text": narrative_text,
        "claims": corrected_claims,
    }
    return json.dumps(payload, ensure_ascii=False)
