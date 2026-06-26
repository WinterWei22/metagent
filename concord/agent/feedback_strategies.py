"""Strategy A: deterministic cascade claim processing (feedback-redesign Task 1+2+3).

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

Task 3 public API:
  weave_narrative(corrected_claims, llm_call) → str
    Given a list of verified grammar-v2 claim dicts, call LLM once with
    a prompt that instructs: write a 150-300 word coherent narrative
    describing these claims, mentioning every pathway name, adding NO
    new claims, modifying NO claim. Returns the LLM's narrative_text.

This module is NEW code (✅ add-only per verifier modification policy).
Do NOT import from or modify B1-core helpers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

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
        # M1 fix: use pathway_name as final fallback so term_id is never empty
        # string (which would fail grammar.validate). The cascade's goal is to
        # NOT lose claims; using the pathway name as a last-resort ID keeps the
        # claim alive for verify_sub6 re-verification.
        if "term_id" not in d or not d["term_id"]:
            ctx = claim.enrichment_context
            claimed_id = (ctx.claimed_pathway_id if ctx else None) or pathway_id
            # Final fallback: pathway_name if both enrichment_context and
            # pathway_id are absent. This ensures term_id is never empty.
            d["term_id"] = claimed_id or pathway_name or ""

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


def _build_claims_summary(corrected_claims: list[dict]) -> str:
    """Build a structured summary of claims for the LLM to narrate.

    Parameters
    ----------
    corrected_claims:
        List of grammar-v2 claim dicts (the corrected set after cascade).

    Returns
    -------
    str
        A formatted markdown-style summary listing each claim's key
        details (pathway_name, subject, grammar shape).
    """
    if not corrected_claims:
        return "(No claims provided.)"

    lines = []
    for i, claim in enumerate(corrected_claims, start=1):
        grammar = claim.get("grammar", "unknown")
        claim_text = claim.get("claim_text", "")
        pathway_name = claim.get("pathway_name") or claim.get("term_name")
        subject = claim.get("subject")

        summary_parts = [f"Claim {i} ({grammar})"]
        if claim_text:
            summary_parts.append(f"Text: {claim_text}")
        if pathway_name:
            summary_parts.append(f"Pathway: {pathway_name}")
        if subject:
            summary_parts.append(f"Subject: {subject}")

        lines.append(" | ".join(summary_parts))

    return "\n".join(lines)


def weave_narrative(
    corrected_claims: list[dict],
    llm_call: Callable[[str], str] | None = None,
) -> str:
    """Weave a narrative describing the corrected claims using LLM.

    Given a list of deterministically corrected grammar-v2 claim dicts,
    this function calls the LLM once to produce a coherent narrative
    that describes these claims. The LLM is instructed to:

    1. Write a 150-300 word coherent paragraph
    2. Mention every pathway name from the claims
    3. NOT add any new claims
    4. NOT modify any claim's pathway, subject, or structured fields
    5. NOT use meta-language, hedging, or qualifications
    6. Preserve the factual specificity of each claim

    Parameters
    ----------
    corrected_claims:
        List of grammar-v2 claim dicts as produced by apply_cascade().
        Each dict has keys: grammar, claim_text, pathway_name,
        subject, etc.
    llm_call:
        A callable that takes a prompt (str) and returns the LLM's
        response (str). If None, uses the default LLM client.

    Returns
    -------
    str
        The LLM's narrative text, returned verbatim (no post-processing).
    """
    if llm_call is None:
        llm_call = _default_weave_narrative_call

    # Build structured summary of claims for the prompt
    claims_summary = _build_claims_summary(corrected_claims)

    # Load the prompt template
    prompt_template = _load_narrative_weave_template()

    # Substitute {claims_summary} placeholder
    prompt = prompt_template.replace("{claims_summary}", claims_summary)

    # Call LLM with the constructed prompt
    narrative_text = llm_call(prompt)

    return narrative_text


def _load_narrative_weave_template() -> str:
    """Load the narrative weave prompt template from file.

    Returns
    -------
    str
        The prompt template with {claims_summary} placeholder ready
        for substitution.
    """
    # Path relative to this module
    template_path = Path(__file__).parent.parent.parent / "prompts" / "agent" / "feedback_narrative_weave_prompt.md"

    if template_path.exists():
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()

    # Fallback if file not found (for testing or edge cases)
    return """You have reviewed evidence-verified claims about metabolite pathways.
Write a coherent 150–300 word narrative that describes these claims.

CRITICAL CONSTRAINTS:
1. Do NOT add new claims.
2. Do NOT modify or remove any claim.
3. Do NOT use meta-language or hedging.
4. Mention every pathway name explicitly.

Claims to weave:

{claims_summary}

Write your narrative now:
"""


def _default_weave_narrative_call(prompt: str) -> str:
    """Default LLM call for weave_narrative.

    Uses the project's standard LLM client (common.llm_client.chat).

    Parameters
    ----------
    prompt:
        The structured prompt to send to the LLM.

    Returns
    -------
    str
        The LLM's response text.
    """
    from common.llm_client import chat

    response = chat(
        [
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=600,
        trace_id="feedback_narrative_weave",
        caller="concord.feedback_strategies.weave_narrative",
    )
    return response


# ---------------------------------------------------------------------------
# Task 4: B-strategy (anchored rewrite) + C-gating
# ---------------------------------------------------------------------------

# Verdicts whose claims must NOT appear in the anchored feedback prompt.
# INSUFFICIENT_EVIDENCE: the verifier is unsure → keep without guidance.
# UNVERIFIABLE_V0 / NEEDS_HUMAN_REVIEW / ERROR: out-of-scope for LLM fix.
_SILENT_VERDICTS = frozenset(
    [
        ClaimVerdict.INSUFFICIENT_EVIDENCE,
        ClaimVerdict.UNVERIFIABLE_V0,
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
        ClaimVerdict.ERROR,
    ]
)


def build_anchored_feedback(verified_claims: list[VerifiedClaim]) -> str:
    """B-strategy: build a feedback prompt with a positive anchor block.

    Unlike the original feedback prompt (which only shows the LLM the
    PROBLEMS — contradicted/unsupported), this prompt leads with a
    SUPPORTED-anchor block that explicitly tells the LLM which claims it
    must preserve verbatim. This prevents the LLM from accidentally
    degrading already-correct content during the rewrite.

    Verdict routing:
      SUPPORTED              → listed in anchor block (must preserve)
      CONTRADICTED           → listed in "must change" block with top-1
                               correction suggestion; if correction absent,
                               silently omitted from that block
      UNSUPPORTED            → listed in "rephrase or drop" block
      INSUFFICIENT_EVIDENCE  → omitted entirely (verifier unsure → keep)
      UNVERIFIABLE_V0        → omitted from prompt (handled separately if
                               the caller wants to add a UNV section)
      NEEDS_HUMAN_REVIEW     → omitted
      ERROR                  → omitted

    Parameters
    ----------
    verified_claims:
        The list of VerifiedClaim objects from one verifier pass.

    Returns
    -------
    str
        A formatted feedback prompt string ready to be sent as a user-role
        message in the feedback turn. Uses the anchored prompt template
        ``prompts/agent/sub6b_react_feedback_prompt_anchored.md``.
    """
    supported: list[VerifiedClaim] = []
    contradicted: list[VerifiedClaim] = []
    unsupported: list[VerifiedClaim] = []

    for claim in verified_claims:
        if claim.verdict == ClaimVerdict.SUPPORTED:
            supported.append(claim)
        elif claim.verdict == ClaimVerdict.CONTRADICTED:
            contradicted.append(claim)
        elif claim.verdict == ClaimVerdict.UNSUPPORTED:
            unsupported.append(claim)
        # INSUFFICIENT_EVIDENCE and all other verdicts are silently skipped

    # Build anchor block
    if supported:
        anchor_lines = ["已验证，原样保留 (preserve verbatim):"]
        for c in supported:
            anchor_lines.append(f"- {c.claim_text}")
        supported_anchor_block = "\n".join(anchor_lines)
    else:
        supported_anchor_block = "(No SUPPORTED claims in this pass.)"

    # Build CONTRADICTED block
    contradicted_lines: list[str] = []
    for c in contradicted:
        correction = c.correction
        if correction and correction.strip():
            contradicted_lines.append(
                f"- CLAIM: {c.claim_text}\n  应该是 (should be): {correction.strip()}"
            )
        # If no correction, omit from the "must change" block (no usable suggestion)
    contradicted_block = "\n".join(contradicted_lines) if contradicted_lines else "(None)"

    # Build UNSUPPORTED block
    unsupported_lines: list[str] = []
    for c in unsupported:
        unsupported_lines.append(f"- {c.claim_text}")
    unsupported_block = "\n".join(unsupported_lines) if unsupported_lines else "(None)"

    # Load prompt template and substitute placeholders
    template = _load_anchored_feedback_template()
    output = (
        template
        .replace("{supported_anchor_block}", supported_anchor_block)
        .replace("{n_contradicted}", str(len(contradicted)))
        .replace("{n_unsupported}", str(len(unsupported)))
        .replace("{contradicted_block}", contradicted_block)
        .replace("{unsupported_block}", unsupported_block)
        # Leave optional placeholders with sensible defaults
        .replace("{n_unverifiable}", "0")
        .replace("{unverifiable_block}", "(None)")
        .replace("{n_dropped_by_grammar}", "0")
        .replace("{dropped_block}", "(None)")
        .replace("{original_narrative_text}", "")
    )
    return output


def _load_anchored_feedback_template() -> str:
    """Load the anchored feedback prompt template from file."""
    template_path = (
        Path(__file__).parent.parent.parent
        / "prompts"
        / "agent"
        / "sub6b_react_feedback_prompt_anchored.md"
    )
    if template_path.exists():
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()

    # Inline fallback (used only if the file is missing — e.g. bare test env)
    return (
        "# ANCHOR — Already-Verified Claims (DO NOT CHANGE)\n"
        "{supported_anchor_block}\n\n"
        "# What to fix\n"
        "- {n_contradicted} CONTRADICTED claim(s) — MUST change.\n"
        "- {n_unsupported} UNSUPPORTED claim(s) — rephrase or drop.\n\n"
        "# CONTRADICTED claims\n"
        "{contradicted_block}\n\n"
        "# UNSUPPORTED claims\n"
        "{unsupported_block}\n"
    )


def should_trigger_feedback(
    verified_claims: list[VerifiedClaim],
    min_bad_frac: float = 0.0,
) -> bool:
    """C-gating: decide whether a feedback turn is warranted.

    A feedback turn is triggered only if there is meaningful actionable
    content to give the LLM. Specifically, there must be at least one
    CONTRADICTED or UNSUPPORTED claim (the two verdicts the LLM can act
    on with a prompt-level fix).

    INSUFFICIENT_EVIDENCE is explicitly excluded from triggering feedback:
    the verifier was uncertain, not confident of an error, so sending the
    LLM back to revise those claims risks spurious rewrites.

    Parameters
    ----------
    verified_claims:
        The list of VerifiedClaim objects from one verifier pass.
    min_bad_frac:
        Optional minimum fraction of claims that must be CONTRADICTED or
        UNSUPPORTED before triggering. Default 0.0 means any single bad
        claim triggers. Set to e.g. 0.5 to require >= 50% bad claims.

    Returns
    -------
    bool
        True → run a feedback turn; False → skip.
    """
    if not verified_claims:
        return False

    bad_verdicts = frozenset([ClaimVerdict.CONTRADICTED, ClaimVerdict.UNSUPPORTED])
    bad_count = sum(1 for c in verified_claims if c.verdict in bad_verdicts)

    if bad_count == 0:
        return False

    if min_bad_frac > 0.0:
        frac = bad_count / len(verified_claims)
        return frac >= min_bad_frac

    return True


# ---------------------------------------------------------------------------
# Task 5: FeedbackResult dataclass + apply_feedback_strategy dispatch
# ---------------------------------------------------------------------------


@dataclass
class FeedbackResult:
    """Unified output of apply_feedback_strategy.

    Fields
    ------
    strategy:
        The strategy name that produced this result ("cascade", "anchored",
        or "gated").
    kind:
        "cascade" — payload is a grammar-v2 JSON string for re-ingestion by
        verify_sub6's zero-LLM path.
        "rewrite" — payload is a feedback prompt string (or None for gated
        no-trigger).
    payload:
        For cascade: JSON string ``{"narrative_text": ..., "claims": [...]}``
        built by build_cascade_payload after weaving narrative via LLM.
        For anchored: the anchored feedback prompt string.
        For gated: the B1 default feedback prompt if triggered, None if not.
    corrected_claims:
        For cascade only: the list of grammar-v2 claim dicts produced by
        apply_cascade (before wrapping into JSON).  None for B/C strategies.
    """
    strategy: str
    kind: str  # "cascade" | "rewrite"
    payload: str | None
    corrected_claims: list[dict] | None


def _build_gated_feedback(
    verified_claims: list[VerifiedClaim],
    verdict_obj: Any,
) -> str:
    """Build the B1 default feedback string (gated strategy, trigger path).

    Mirrors ``concord.agent.react_runner._resolve_default_feedback_builder``
    but operates directly on the verified_claims list (no VerifiedIdentification
    wrapper) because the gated strategy is called with raw VerifiedClaim objects.

    The gated strategy calls this only when should_trigger_feedback is True.
    """
    from evaluation.sub6.run_sub6b_react_feedback import build_feedback_message
    from verifier.feedback_hints import annotate_claims

    annotated = annotate_claims(list(verified_claims), pass_id="v1")
    contradicted = [c for c in annotated if c.verdict == ClaimVerdict.CONTRADICTED]
    unsupported = [c for c in annotated if c.verdict == ClaimVerdict.UNSUPPORTED]
    unverifiable = [c for c in annotated if c.verdict == ClaimVerdict.UNVERIFIABLE_V0]
    dropped = list(getattr(verdict_obj, "dropped_claims", None) or []) if verdict_obj else []

    return build_feedback_message(
        contradicted=contradicted,
        unsupported=unsupported,
        unverifiable=unverifiable,
        dropped=dropped,
        original_narrative="",
    )


def apply_feedback_strategy(
    strategy: str,
    verified_claims: list[VerifiedClaim],
    source_report: Any,
    llm_call: Callable[[str], str] | None = None,
) -> FeedbackResult:
    """Unified dispatch for feedback strategies A / B / C.

    Parameters
    ----------
    strategy:
        One of "cascade", "anchored", "gated".
    verified_claims:
        VerifiedClaim list from one verifier pass (iter-0 output).
    source_report:
        The source report (accepted for signature symmetry; cascade may
        use it for narrative context — not strictly required today).
    llm_call:
        Callable(prompt: str) -> str injected for testability.  Used only
        by cascade's weave_narrative step.  If None, the default LLM
        client is used by weave_narrative.

    Returns
    -------
    FeedbackResult
        Dispatch result with kind, payload, corrected_claims populated
        per strategy contract.

    Raises
    ------
    ValueError
        If ``strategy`` is not one of the three supported values.
    """
    if strategy == "cascade":
        corrected = apply_cascade(verified_claims)
        narrative = weave_narrative(corrected, llm_call=llm_call)
        payload = build_cascade_payload(corrected, narrative)
        return FeedbackResult(
            strategy="cascade",
            kind="cascade",
            payload=payload,
            corrected_claims=corrected,
        )

    elif strategy == "anchored":
        payload = build_anchored_feedback(verified_claims)
        return FeedbackResult(
            strategy="anchored",
            kind="rewrite",
            payload=payload,
            corrected_claims=None,
        )

    elif strategy == "gated":
        if should_trigger_feedback(verified_claims):
            payload = _build_gated_feedback(verified_claims, verdict_obj=source_report)
            return FeedbackResult(
                strategy="gated",
                kind="rewrite",
                payload=payload,
                corrected_claims=None,
            )
        else:
            return FeedbackResult(
                strategy="gated",
                kind="rewrite",
                payload=None,
                corrected_claims=None,
            )

    else:
        raise ValueError(
            f"unknown strategy {strategy!r}; expected one of 'cascade', 'anchored', 'gated'"
        )
