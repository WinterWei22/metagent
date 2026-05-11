"""LLM-facing feedback hint generation (phase A2 D1).

After ``verify_sub6`` produces a list of ``VerifiedClaim`` objects, this
module annotates each one with:

  1. ``claim_id`` — synthetic ID (``v1:c000`` / ``v2:c042``) when the
     extractor did not supply one. The ``claim_table`` builder uses the
     same algorithm; we hoist it here so the per-claim ID is also
     available on the serialised JSONL output (where the table view is
     not consumed).

  2. ``feedback_hint`` — a short, actionable string the next-iteration
     agent can paste into its revision prompt. Generated only for
     verdicts the agent can act on (CONTRADICTED / UNSUPPORTED) — for
     SUPPORTED / UNVERIFIABLE_V0 / ERROR / NEEDS_HUMAN_REVIEW the
     verifier has nothing useful to say to the agent.

Hints are intentionally template-based and short. They reference fields
already present on the claim (``extracted_fields.pathway_name``,
``correction``, ``evidence``) rather than re-running any verifier logic
— this module does NOT make additional database calls and does NOT
change any verdict.

Backward compatibility: this module produces new ``VerifiedClaim``
instances via ``model_copy(update=...)`` (the model is frozen). Callers
that pass an old claim list through ``annotate_claims`` get a new list;
the originals are untouched.
"""
from __future__ import annotations

from typing import Iterable

from verifier.schemas import (
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    VerifiedClaim,
)


# ---------------------------------------------------------------------------
# Synthetic claim ID generation (mirrors verifier/claim_table.py:47)
# ---------------------------------------------------------------------------


def _claim_id_for(claim: VerifiedClaim, *, pass_id: str, idx: int) -> str:
    """Return claim.claim_id if already set, else synthesise from pass + idx."""
    return claim.claim_id or f"{pass_id}:c{idx:03d}"


# ---------------------------------------------------------------------------
# Feedback hint templates
# ---------------------------------------------------------------------------


_NEUTRAL_VERDICTS: frozenset[ClaimVerdict] = frozenset(
    {
        ClaimVerdict.SUPPORTED,
        ClaimVerdict.UNVERIFIABLE_V0,
        ClaimVerdict.ERROR,
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
    }
)


def _pathway_phrase(claim: VerifiedClaim) -> str | None:
    """Best-effort pathway-name phrase from the claim's extracted fields."""
    name = (claim.extracted_fields.pathway_name or "").strip()
    return name if name else None


def _correction_phrase(claim: VerifiedClaim) -> str | None:
    val = (claim.correction or "").strip()
    return val if val else None


def _hint_for_contradicted(claim: VerifiedClaim) -> str:
    """Return an actionable revision hint for a CONTRADICTED claim."""
    ctype = claim.claim_type
    subtype = claim.claim_subtype

    # Pathway directional / relationship claims (Layer 6d)
    if ctype == ClaimType.PATHWAY_RELATIONSHIP or subtype in (
        ClaimSubtype.PATHWAY_UPSTREAM,
        ClaimSubtype.PATHWAY_DOWNSTREAM,
        ClaimSubtype.PATHWAY_CROSS_TALK,
    ):
        correction = _correction_phrase(claim)
        if correction:
            return (
                "KEGG reaction graph contradicts this directional claim. "
                f"Verifier suggests: {correction}. Either retract the "
                "original direction or restate it in line with the verifier."
            )
        return (
            "KEGG reaction graph contradicts this directional claim. Either "
            "retract or reverse the direction; do not argue against the "
            "graph."
        )

    # Driver / list-of-compounds claims (Layer 6b)
    if (
        ctype == ClaimType.DRIVER_METABOLITE
        or subtype == ClaimSubtype.DRIVER_LIST
    ):
        return (
            "The compound named as a driver is not in the input metabolite "
            "list (or doesn't match by InChIKey/KEGG/HMDB). Replace with a "
            "compound that actually appears in the input list, or drop the "
            "driver claim."
        )

    # Set-enrichment / pathway membership claims (Layer 6a / 6c)
    if ctype == ClaimType.SET_ENRICHMENT or subtype in (
        ClaimSubtype.PATHWAY_MEMBERSHIP,
        ClaimSubtype.ENRICHMENT_PATHWAY,
    ):
        pathway = _pathway_phrase(claim)
        correction = _correction_phrase(claim)
        if correction:
            return (
                f"Pathway '{pathway or 'in claim'}' contradicted by RaMP-DB. "
                f"Use '{correction}' instead, or retract."
            )
        if pathway:
            return (
                f"Pathway '{pathway}' contradicted by your "
                f"query_ramp_enrichment / query_pathway_membership tool "
                "results. Retract this claim or substitute a verified "
                "pathway from those tool outputs."
            )
        return (
            "Set/membership claim contradicted by your tool outputs. Retract "
            "or substitute a verified pathway name."
        )

    # Generic biological claim
    if ctype == ClaimType.BIOLOGICAL:
        pathway = _pathway_phrase(claim)
        if pathway:
            return (
                f"Biological claim mentioning '{pathway}' is contradicted by "
                "the verifier's evidence. Retract or qualify."
            )
        return "Biological claim contradicted by verifier evidence — retract or qualify."

    # Fallback
    return (
        "Verifier flagged this claim as contradicted. Retract or revise "
        "using only vocabulary from your earlier tool calls."
    )


def _hint_for_unsupported(claim: VerifiedClaim) -> str:
    """Return an actionable revision hint for an UNSUPPORTED claim.

    UNSUPPORTED means the verifier could not find positive evidence; the
    LLM should rephrase to use vocabulary from its tool outputs, or drop
    the claim.
    """
    ctype = claim.claim_type
    subtype = claim.claim_subtype

    if ctype == ClaimType.PATHWAY_RELATIONSHIP:
        return (
            "Directional / relationship claim has no positive support in "
            "the KEGG reaction graph. Either drop the directional language "
            "(co-membership is fine) or back the claim with a path you "
            "actually retrieved from query_kegg_path."
        )

    if (
        ctype == ClaimType.DRIVER_METABOLITE
        or subtype == ClaimSubtype.DRIVER_LIST
    ):
        return (
            "Driver claim is not supported by the input metabolite list. "
            "Drop the claim or rephrase to reference a compound that "
            "actually appears in the input list."
        )

    if ctype == ClaimType.SET_ENRICHMENT or subtype in (
        ClaimSubtype.PATHWAY_MEMBERSHIP,
        ClaimSubtype.ENRICHMENT_PATHWAY,
    ):
        pathway = _pathway_phrase(claim)
        if pathway:
            return (
                f"Pathway '{pathway}' was not found in your "
                "query_ramp_enrichment top hits. Rephrase using one of the "
                "verified pathway names returned by that tool, or drop the "
                "reference."
            )
        return (
            "Pathway / set-membership claim has no support in your tool "
            "outputs. Use a verified pathway name from "
            "query_ramp_enrichment, or drop the claim."
        )

    if ctype == ClaimType.BIOLOGICAL:
        # Phase A3 D1b: biological_claim claims that are unsupported in
        # the structured DB layers (RaMP, KEGG, HMDB) are often genuinely
        # literature-supported — e.g. mechanistic statements about a
        # disease, a tissue-specific role, a recent enzymology insight.
        # Steer the agent toward search_literature instead of an
        # unconditional retract, but keep retract as the fallback.
        subject = (claim.subject or "").strip()
        pathway = _pathway_phrase(claim)
        focus = subject or pathway or _extract_search_query(claim)
        if focus:
            return (
                f"Biological claim referencing '{focus}' has no positive "
                "evidence in the pathway databases (RaMP / KEGG / HMDB). "
                "This is often a literature-supported claim. Call "
                f"search_literature(\"{focus}\") to find supporting papers "
                "and cite them inline (PMID); otherwise drop the claim "
                "if speculative."
            )
        return (
            "Biological claim lacks positive evidence in the pathway "
            "databases. Try search_literature for a tight query that "
            "matches the claim, cite resulting PMIDs inline; if nothing "
            "supports it, drop the claim."
        )

    return (
        "Claim has no positive evidence in your tool calls. Rephrase using "
        "verified vocabulary, or drop."
    )


def _extract_search_query(claim: VerifiedClaim) -> str:
    """Build a plausible Europe PMC query from a claim's text.

    Heuristics — keep it minimal so the agent has freedom to refine:
      * If the extracted_fields carry a pathway_name, use it.
      * Else fall back to the first 6 words of the claim text.
    """
    pathway = (claim.extracted_fields.pathway_name or "").strip()
    if pathway:
        return pathway
    text = (claim.claim_text or "").strip()
    if not text:
        return ""
    words = text.split()
    return " ".join(words[:6])


def generate_feedback_hint(claim: VerifiedClaim) -> str | None:
    """Return an LLM-facing actionable hint, or ``None`` for neutral verdicts.

    Returns ``None`` when the verdict is one of SUPPORTED /
    UNVERIFIABLE_V0 / ERROR / NEEDS_HUMAN_REVIEW — the agent cannot act
    on those.
    """
    if claim.verdict in _NEUTRAL_VERDICTS:
        return None
    if claim.verdict == ClaimVerdict.CONTRADICTED:
        return _hint_for_contradicted(claim)
    if claim.verdict == ClaimVerdict.UNSUPPORTED:
        return _hint_for_unsupported(claim)
    return None  # defensive — covers any future verdict additions


# ---------------------------------------------------------------------------
# Annotation pass — produces a new list (model is frozen)
# ---------------------------------------------------------------------------


def annotate_claims(
    claims: Iterable[VerifiedClaim],
    *,
    pass_id: str,
) -> list[VerifiedClaim]:
    """Return a new list with ``claim_id`` synthesised and ``feedback_hint``
    populated. Originals are untouched.

    ``pass_id`` is one of ``"v1"`` (the initial verifier pass) or
    ``"v2"`` (the post-rewrite pass; Sub-6 reuses v1 here since the
    rewriter is disabled). Ordering follows the input list.
    """
    out: list[VerifiedClaim] = []
    for i, claim in enumerate(claims):
        out.append(
            claim.model_copy(
                update={
                    "claim_id": _claim_id_for(claim, pass_id=pass_id, idx=i),
                    "feedback_hint": generate_feedback_hint(claim),
                }
            )
        )
    return out
