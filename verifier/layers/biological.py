"""Layer C — verify Type 3 (biological / pathway) claims.

A biological claim asserts a pathway membership, a metabolic context, or a
network relationship. Verification is *membership-only* in v0:

* Pathway IDs (``map00232``, ``R-HSA-1430728``, ``SMP00525``) are looked up
  in ``source_report.candidates[*].pathway_context.pathways[*].id``.
* Pathway *names* (e.g. "galactose metabolism", "Fabry disease") are
  matched fuzzily against the same pathway entries' ``name`` field.
* Claims that depend on **upstream / downstream / neighbour** information
  are marked ``UNVERIFIABLE_V0`` regardless of source contents — the
  D/E audit (P-2/P-3/P-4/P-6) flagged these fields as unreliable for v0.
* Cooccurrence-score claims are also ``UNVERIFIABLE_V0`` for the same
  reason.

Source-first only in v0. A future iteration may add a real
``pathway_context`` round-trip when the subject has a resolvable HMDB /
KEGG ID, but for the seed data the formatter already includes every
pathway the tool returned; a re-query would not surface new evidence.
"""
from __future__ import annotations

import re

from schemas.report import CandidateReport, IdentificationReport
from verifier.schemas import (
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    VerifiedClaim,
)
from verifier.source_lookup import find_candidate_by_name


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_NEIGHBOUR_KEYWORDS = re.compile(
    r"\b("
    r"upstream|downstream|neighbour|neighbor|neighbours|neighbors|"
    r"co[\s-]?occurrence|co[\s-]?observed|co[\s-]?detected|cooccur"
    r")\b",
    re.IGNORECASE,
)

_PATHWAY_ID_RE = re.compile(
    r"\b("
    r"map\d{5}|hsa\d{5}|R-HSA-\d+|SMP\d+|WP\d+"
    r")\b",
    re.IGNORECASE,
)

# Heuristics to lift candidate pathway names out of free-text claims.
# Captures phrases like:
#   "galactose metabolism"
#   "Fabry disease"
#   "caffeine metabolism"
#   "Galactosemia"
#   "biological oxidations"
_PATHWAY_PHRASE_RE = re.compile(
    r"\b("
    r"[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,4}\s+"
    r"(?:metabolism|biosynthesis|degradation|disease|syndrome|cycle|"
    r"oxidations?|signal[l]?ing|transduction|disorder|pathways?)"
    r"|"
    r"galactosemia(?:\s+[IVX]+)?(?:\s+\([A-Z]+\))?"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def verify_biological(
    claim: ClassifiedClaim,
    source_report: IdentificationReport,
) -> VerifiedClaim:
    """Verify one biological claim. Source-first; no tool calls in v0."""
    if _NEIGHBOUR_KEYWORDS.search(claim.claim_text):
        return _unverifiable(
            claim,
            evidence=(
                "Neighbour / cooccurrence claims are blocked on the "
                "P-2/P-3/P-4/P-6 D/E audit fixes; verifier returns "
                "UNVERIFIABLE_V0 rather than risk a false confirmation."
            ),
        )

    pathway_ids = _extract_pathway_ids(claim.claim_text)
    pathway_phrases = _extract_pathway_phrases(claim.claim_text)
    if not pathway_ids and not pathway_phrases:
        return _unverifiable(
            claim,
            evidence=(
                "Layer C found no pathway ID or pathway phrase in the claim. "
                "Cannot map to a membership check at v0."
            ),
        )

    # Resolve candidate scope: subject's candidate if known, else all.
    scope: list[tuple[int, CandidateReport]]
    cand_idx: int | None = None
    if claim.subject:
        cr, cand_idx = find_candidate_by_name(source_report, claim.subject)
        if cr is None:
            return _unverifiable(
                claim,
                evidence=(
                    f"Subject {claim.subject!r} not matched to any candidate "
                    "in source_report."
                ),
            )
        scope = [(cand_idx, cr)]
    else:
        scope = list(enumerate(source_report.candidates))

    # Layer C only fires when the subject's pathway_context is populated for
    # at least one candidate in scope. If every scope candidate has
    # pathway_context=None (legitimate degradation), UNVERIFIABLE_V0.
    if all(cr.pathway_context is None for _, cr in scope):
        path = (
            f"candidates[{cand_idx}].pathway_context"
            if cand_idx is not None
            else "candidates[*].pathway_context"
        )
        return _unverifiable(
            claim,
            evidence=f"{path} is None for every candidate in scope.",
            source_field=path,
        )

    # Try ID match first (more precise).
    for pid in pathway_ids:
        for i, cr in scope:
            if cr.pathway_context is None:
                continue
            for j, p in enumerate(cr.pathway_context.pathways):
                if p.id.strip().lower() == pid.strip().lower():
                    path = f"candidates[{i}].pathway_context.pathways[{j}]"
                    return _supported(
                        claim,
                        evidence=(
                            f"source {path}.id = {p.id!r}, name = {p.name!r}"
                        ),
                        source_field=path,
                    )

    # Then phrase match (fuzzy, case-insensitive substring).
    for phrase in pathway_phrases:
        norm = _normalise(phrase)
        for i, cr in scope:
            if cr.pathway_context is None:
                continue
            for j, p in enumerate(cr.pathway_context.pathways):
                if _phrase_matches(norm, p.name):
                    path = f"candidates[{i}].pathway_context.pathways[{j}]"
                    return _supported(
                        claim,
                        evidence=(
                            f"source {path}.name = {p.name!r} matches "
                            f"claimed phrase {phrase!r}"
                        ),
                        source_field=path,
                    )

    # Nothing matched.
    return VerifiedClaim(
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        verdict=ClaimVerdict.UNSUPPORTED,
        evidence=(
            f"None of the claimed pathway IDs ({pathway_ids}) or phrases "
            f"({pathway_phrases}) matched any pathway entry in the "
            "candidate(s) under consideration."
        ),
        source_field=None,
        correction=None,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_pathway_ids(text: str) -> list[str]:
    return [m.group(1) for m in _PATHWAY_ID_RE.finditer(text)]


def _extract_pathway_phrases(text: str) -> list[str]:
    """Return candidate pathway-name phrases. Deduplicated, ordered by
    first appearance.

    Conservative — better to miss a phrase than to over-match (which
    would give us false SUPPORTEDs).
    """
    seen: list[str] = []
    for m in _PATHWAY_PHRASE_RE.finditer(text):
        phrase = m.group(0).strip()
        if phrase.lower() not in {p.lower() for p in seen}:
            seen.append(phrase)
    return seen


def _normalise(s: str) -> str:
    return " ".join(s.lower().split())


def _phrase_matches(norm_claim_phrase: str, source_pathway_name: str) -> bool:
    """Loose match: claim phrase appears (case- and whitespace-insensitive)
    inside source name, or vice versa. Both directions because the
    formatter sometimes appends qualifiers ("Galactose Metabolism" vs.
    "Galactosemia II (GALK)")."""
    src = _normalise(source_pathway_name)
    cl = norm_claim_phrase
    return cl in src or src in cl


def _supported(
    claim: ClassifiedClaim, *, evidence: str, source_field: str
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        verdict=ClaimVerdict.SUPPORTED,
        evidence=evidence,
        source_field=source_field,
        correction=None,
    )


def _unverifiable(
    claim: ClassifiedClaim, *, evidence: str, source_field: str | None = None,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence=evidence,
        source_field=source_field,
        correction=None,
    )
