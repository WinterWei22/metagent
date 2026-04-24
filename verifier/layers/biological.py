"""Layer C — verify Type 3 (biological / pathway) claims.

A biological claim asserts a pathway membership, a metabolic context, or a
network relationship. v0 verifies three shapes:

* **Pathway membership** — pathway IDs (``map00232``, ``R-HSA-1430728``,
  ``SMP00525``) and pathway *names* (e.g. "galactose metabolism") are
  looked up in
  ``source_report.candidates[*].pathway_context.pathways``.
* **Neighbour membership** — claims of the form "X is upstream of Y" /
  "X is downstream of Y" / "Y is in X's neighbours" are verified against
  ``upstream_neighbours`` / ``downstream_neighbours``. The
  ``pathway_context`` tool's neighbour lists were originally flagged
  unreliable (P-2 up==down collapse, P-3 non-HMDB/KEGG ID leaks, P-4
  cofactor flooding); all four are now resolved (commits ``afd044f``,
  ``8432cbe``, ``4e968fa``, ``9bebd3a``) and Layer C uses them as a
  trust anchor. Name-only neighbour claims that name no resolvable ID
  still return ``UNVERIFIABLE_V0`` (no v0 name-to-ID resolver in this
  layer).
* **Cooccurrence-score claims** — still ``UNVERIFIABLE_V0``. P-6 fixed
  the score computation (resolvable-only denominator), but the verifier
  has no v0 mapping from natural-language qualifiers ("high",
  "moderate") to a numeric threshold.

Source-first only in v0. A future iteration may add a real
``pathway_context`` round-trip when the subject has a resolvable HMDB /
KEGG ID, but for the seed data the formatter already includes every
pathway and neighbour the tool returned.
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
    r"upstream|downstream|neighbour|neighbor|neighbours|neighbors"
    r")\b",
    re.IGNORECASE,
)

_COOCCURRENCE_KEYWORDS = re.compile(
    r"\b("
    r"co[\s-]?occurrence|co[\s-]?observed|co[\s-]?detected|cooccur|"
    r"co[\s-]?occurring"
    r")\b",
    re.IGNORECASE,
)

_PATHWAY_ID_RE = re.compile(
    r"\b("
    r"map\d{5}|hsa\d{5}|R-HSA-\d+|SMP\d+|WP\d+"
    r")\b",
    re.IGNORECASE,
)

# Metabolite-shaped IDs (HMDB / KEGG-compound) — used by neighbour lookup.
# Distinct from the pathway IDs above (``map00232`` etc.).
_METABOLITE_ID_RE = re.compile(
    r"\b("
    r"HMDB\d{6,}|"
    r"C\d{5}"  # KEGG compound (C followed by exactly 5 digits)
    r")\b",
    re.IGNORECASE,
)

# Heuristics to lift candidate pathway names out of free-text claims.
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
    # Cooccurrence claims need a numeric-threshold mapping that v0 does
    # not have ("high cooccurrence" → score > X?). Hold these out of
    # neighbour-membership routing.
    if _COOCCURRENCE_KEYWORDS.search(claim.claim_text):
        return _unverifiable(
            claim,
            evidence=(
                "Cooccurrence-score claims need a v1 mapping from "
                "qualifiers ('high', 'moderate') to a numeric threshold; "
                "v0 cannot adjudicate even though P-6 fixed the score's "
                "computation."
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

    # Neighbour-membership claims get their own routing — they verify
    # against upstream_neighbours / downstream_neighbours, not pathways.
    if _NEIGHBOUR_KEYWORDS.search(claim.claim_text):
        return _verify_neighbour_membership(claim, scope, cand_idx)

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
# Neighbour-membership verification (post-P-2/3/4/6 fixes)
# ---------------------------------------------------------------------------


def _verify_neighbour_membership(
    claim: ClassifiedClaim,
    scope: list[tuple[int, "CandidateReport"]],
    cand_idx: int | None,
) -> VerifiedClaim:
    """Check whether any HMDB/KEGG ID named in the claim appears in a
    scope candidate's neighbour lists.

    The neighbour fields became trustworthy after Track D commits
    afd044f (P-2 up==down collapse), 8432cbe (P-3 non-HMDB/KEGG prefix
    leaks), 4e968fa (P-4 cofactor flooding). v0 verifies *direction-aware*
    membership when the claim explicitly says "upstream" or "downstream",
    or *either-direction* membership for general "neighbour" claims.
    """
    # If pathway_context is None across the whole scope, we cannot
    # adjudicate.
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

    metab_ids = _extract_metabolite_ids(claim.claim_text)
    if not metab_ids:
        # Name-only neighbour claim. v0 has no name-to-ID resolver in
        # Layer C; soft-fail rather than risk a false confirmation.
        return _unverifiable(
            claim,
            evidence=(
                "Neighbour claim names no HMDB / KEGG-compound ID; v0 "
                "Layer C has no name-to-ID resolver. The neighbour list "
                "stores IDs only (e.g. 'hmdb:HMDB0000243'), so a literal "
                "ID is required for membership lookup."
            ),
        )

    direction = _claim_direction(claim.claim_text)

    for mid in metab_ids:
        mid_l = mid.lower()
        for i, cr in scope:
            if cr.pathway_context is None:
                continue
            up_hit = _id_in_neighbour_list(
                mid_l, cr.pathway_context.upstream_neighbours
            )
            down_hit = _id_in_neighbour_list(
                mid_l, cr.pathway_context.downstream_neighbours
            )
            # Direction-aware match.
            if direction == "upstream" and up_hit:
                path = (
                    f"candidates[{i}].pathway_context.upstream_neighbours"
                )
                return _supported(
                    claim,
                    evidence=f"{mid!r} found in source {path}",
                    source_field=path,
                )
            if direction == "downstream" and down_hit:
                path = (
                    f"candidates[{i}].pathway_context.downstream_neighbours"
                )
                return _supported(
                    claim,
                    evidence=f"{mid!r} found in source {path}",
                    source_field=path,
                )
            if direction == "either" and (up_hit or down_hit):
                where = "upstream_neighbours" if up_hit else "downstream_neighbours"
                path = f"candidates[{i}].pathway_context.{where}"
                return _supported(
                    claim,
                    evidence=f"{mid!r} found in source {path}",
                    source_field=path,
                )
            # Direction-mismatch: claimed upstream but found downstream
            # (or vice versa). This is a real CONTRADICTED — the claim
            # asserts a relationship that the source actively disagrees
            # with.
            if direction == "upstream" and down_hit and not up_hit:
                path = (
                    f"candidates[{i}].pathway_context.downstream_neighbours"
                )
                return VerifiedClaim(
                    claim_text=claim.claim_text,
                    claim_type=claim.claim_type,
                    verdict=ClaimVerdict.CONTRADICTED,
                    evidence=(
                        f"claim says upstream, but {mid!r} is in source "
                        f"{path} (downstream)"
                    ),
                    source_field=path,
                    correction=None,
                )
            if direction == "downstream" and up_hit and not down_hit:
                path = (
                    f"candidates[{i}].pathway_context.upstream_neighbours"
                )
                return VerifiedClaim(
                    claim_text=claim.claim_text,
                    claim_type=claim.claim_type,
                    verdict=ClaimVerdict.CONTRADICTED,
                    evidence=(
                        f"claim says downstream, but {mid!r} is in source "
                        f"{path} (upstream)"
                    ),
                    source_field=path,
                    correction=None,
                )

    # Named ID(s) not found in any direction across scope.
    return VerifiedClaim(
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        verdict=ClaimVerdict.UNSUPPORTED,
        evidence=(
            f"None of the claimed metabolite IDs ({metab_ids}) appear in "
            f"any candidate's upstream / downstream neighbour list."
        ),
        source_field=None,
        correction=None,
    )


def _claim_direction(text: str) -> str:
    """Return 'upstream', 'downstream', or 'either' from claim text."""
    t = text.lower()
    has_up = "upstream" in t
    has_down = "downstream" in t
    if has_up and not has_down:
        return "upstream"
    if has_down and not has_up:
        return "downstream"
    return "either"  # "neighbour" / "neighbours" — direction-agnostic


def _id_in_neighbour_list(id_lower: str, neighbours: list[str]) -> bool:
    """RaMP/D-output neighbour entries are stored as 'hmdb:HMDB0000243'
    or 'kegg:C00022' (post-P-3 fix). Match on the bare ID (case-insens)
    so a claim text like 'HMDB0000243' resolves regardless of the prefix
    convention used."""
    for n in neighbours:
        n_l = n.lower()
        if n_l == id_lower or n_l.endswith(":" + id_lower):
            return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_pathway_ids(text: str) -> list[str]:
    return [m.group(1) for m in _PATHWAY_ID_RE.finditer(text)]


def _extract_metabolite_ids(text: str) -> list[str]:
    """Return HMDB / KEGG-compound IDs (NOT pathway IDs) found in claim
    text. Used by the neighbour-membership routing."""
    return [m.group(1) for m in _METABOLITE_ID_RE.finditer(text)]


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
