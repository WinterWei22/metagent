"""Stage 2 — classify each claim by which layer should verify it.

Two-pass design:

1. **Rule-based pass.** Regex patterns for database IDs, pathway / disease
   keywords, and chemical-property field references decide most claims
   without an LLM call. Per the Track V brief, rules are expected to handle
   80%+ of claims.

2. **LLM fallback (single batched call).** Claims that no rule matched are
   collected and shipped in one call, using a line-delimited
   ``<index>: <type>`` format so a single malformed line only affects one
   claim instead of the whole batch.

The classifier returns ``ClassifiedClaim`` with ``classifier_source`` set
to ``"rule"`` / ``"llm"`` / ``"fallback"`` (the last is a defensive default
when neither rule nor LLM produced a classification — logged for analysis).

Note: ``CONSISTENCY`` claims are not assigned by Stage 2. Layer D performs
a global consistency sweep over the full classified-claim set and emits
``CONSISTENCY``-typed ``VerifiedClaim`` entries on top of the per-claim
verdicts from layers A/B/C. This keeps Stage 2's job to a single primary
type per claim.
"""
from __future__ import annotations

import re
from typing import Literal

from common.llm_client import chat
from verifier.prompts import classify_ambiguous as prompts
from verifier.schemas import ClaimType, ClassifiedClaim, ExtractedClaim


CALLER = "verifier.stage2.classify_ambiguous"


# ---------------------------------------------------------------------------
# Rule patterns
# ---------------------------------------------------------------------------

# Pathway / metabolism / disease keywords → BIOLOGICAL
_PATHWAY_KEYWORDS = re.compile(
    r"\b("
    r"pathway|pathways|metabolism|metabolic|biosynthesis|degradation|"
    r"disease|diseases|syndrome|syndromes|disorder|disorders|"
    r"galactosemia|signal[l]?ing|cycle|"
    r"neighbour|neighbor|neighbours|neighbors|"
    r"biological\s+matrix|biological\s+context|biofluid|tissue"
    r")\b",
    re.IGNORECASE,
)

# Pathway-shaped IDs (KEGG map, SMPDB, Reactome) → BIOLOGICAL
_PATHWAY_ID_RE = re.compile(
    r"\b("
    r"map\d{5}|hsa\d{5}|R-HSA-\d+|SMP\d+|WP\d+"
    r")\b",
    re.IGNORECASE,
)

# Source-report field references → GROUNDED
_GROUNDED_KEYWORDS = re.compile(
    r"\b("
    r"evidence[\s_]?score|cosine|cosine\s+similarity|"
    r"score:|B/C|"
    r"ppm|mass[\s_]?accuracy|mass[\s_]?match|exact[\s_]?mass|"
    r"neutral[\s_]?mass|precursor|"
    r"molecular[\s_]?formula|formula|"
    r"peak[\s_]?count|adduct|m/z|"
    r"smiles|chemical[\s_]?class|"
    r"hit[\s_]?count|hit[s]?\b"
    r")\b",
    re.IGNORECASE,
)

# Bare empirical-formula match (e.g. C6H12O6, C8H10N4O2) → GROUNDED
_FORMULA_RE = re.compile(
    r"\bC\d{1,3}H\d{1,3}(?:[A-Z][a-z]?\d{0,3})*\b"
)

# Compound database IDs → FACTUAL (when no pathway / grounded keyword wins)
_COMPOUND_ID_RE = re.compile(
    r"\b("
    r"HMDB\d{6,}|"
    r"CHEBI[:_-]?\d+|"
    r"CID[:_-]?\d+|"
    r"CCMSLIB\d+|"
    r"C\d{5}\b|"  # KEGG compound (C followed by exactly 5 digits)
    r"[A-Z]{14}-[A-Z]{10}-[A-Z]"  # InChIKey
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def classify_claims(
    claims: list[ExtractedClaim], *, trace_id: str
) -> tuple[list[ClassifiedClaim], int]:
    """Classify each claim. Returns ``(classified, llm_calls_used)``.

    ``llm_calls_used`` is 0 when every claim was decided by rules, 1 when
    the batched LLM fallback was needed.
    """
    if not claims:
        return [], 0

    decisions: list[ClaimType | None] = []
    sources: list[Literal["rule", "llm", "fallback"]] = []
    ambiguous_indices: list[int] = []

    for i, c in enumerate(claims):
        decided = _rule_classify(c.claim_text)
        decisions.append(decided)
        if decided is None:
            ambiguous_indices.append(i)
            sources.append("fallback")  # may be overwritten by LLM
        else:
            sources.append("rule")

    llm_calls = 0
    if ambiguous_indices:
        llm_decisions = _llm_classify(
            [claims[i].claim_text for i in ambiguous_indices],
            trace_id=trace_id,
        )
        llm_calls = 1
        for offset, idx in enumerate(ambiguous_indices):
            if offset < len(llm_decisions) and llm_decisions[offset] is not None:
                decisions[idx] = llm_decisions[offset]
                sources[idx] = "llm"
            # else: leave as None / "fallback" — caller will see this and
            # default-route in the layer dispatch.

    classified: list[ClassifiedClaim] = []
    for i, c in enumerate(claims):
        ct = decisions[i] if decisions[i] is not None else ClaimType.GROUNDED
        classified.append(
            ClassifiedClaim(
                claim_text=c.claim_text,
                subject=c.subject,
                claim_type=ct,
                classifier_source=sources[i],
            )
        )
    return classified, llm_calls


# ---------------------------------------------------------------------------
# Rule logic
# ---------------------------------------------------------------------------


def _rule_classify(claim_text: str) -> ClaimType | None:
    """Apply the precedence rules. Return None when no rule matches."""
    if _PATHWAY_KEYWORDS.search(claim_text) or _PATHWAY_ID_RE.search(claim_text):
        return ClaimType.BIOLOGICAL
    if _GROUNDED_KEYWORDS.search(claim_text) or _FORMULA_RE.search(claim_text):
        return ClaimType.GROUNDED
    if _COMPOUND_ID_RE.search(claim_text):
        return ClaimType.FACTUAL
    return None


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------


def _llm_classify(
    ambiguous_texts: list[str], *, trace_id: str
) -> list[ClaimType | None]:
    """Send all ambiguous claims in one batched call. Return per-claim type
    or None when the line could not be parsed.

    The line-delimited format is intentionally noise-tolerant: a single
    malformed line returns None for that index but does not invalidate the
    rest of the batch.
    """
    user_msg = prompts.build(ambiguous_texts)
    response = chat(
        messages=[
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        trace_id=trace_id,
        caller=CALLER,
    )

    decisions: list[ClaimType | None] = [None] * len(ambiguous_texts)
    for line in response.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        head, _, tail = line.partition(":")
        head, tail = head.strip(), tail.strip()
        if not head.isdigit():
            continue
        idx = int(head)
        if not (0 <= idx < len(ambiguous_texts)):
            continue
        ct = _parse_type(tail)
        if ct is not None:
            decisions[idx] = ct
    return decisions


_TYPE_LITERALS = {
    "grounded_claim": ClaimType.GROUNDED,
    "grounded": ClaimType.GROUNDED,
    "factual_roundtrip_claim": ClaimType.FACTUAL,
    "factual": ClaimType.FACTUAL,
    "biological_claim": ClaimType.BIOLOGICAL,
    "biological": ClaimType.BIOLOGICAL,
    "consistency_claim": ClaimType.CONSISTENCY,
    "consistency": ClaimType.CONSISTENCY,
}


def _parse_type(token: str) -> ClaimType | None:
    return _TYPE_LITERALS.get(token.strip().lower())
