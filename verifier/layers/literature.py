"""Layer E — verify Type 5 (literature) claims.

A literature claim asserts a citation: a PMID, a DOI, a journal+year
combination, or a paraphrase of a published abstract. v0 verification is
**identifier-anchored**:

* **Source-first.** If the claim names a PMID / DOI that already appears
  in any ``candidate.literature_records[*]``, lookup is a free
  ``SUPPORTED`` — no network call. This is the common case post-Stage 7
  because the LLM was given the records in the first place.
* **Tool round-trip.** If the ID is not in source, query Europe PMC via
  the injected ``fetcher``. A result confirms the ID exists; an empty
  result signals a fabricated citation → ``CONTRADICTED``.
* **No ID in claim.** "See Smith 2023" / "as published" with no PMID or
  DOI → ``UNVERIFIABLE_V0`` (v0 cannot resolve free-text citation
  paraphrases).

Title-mismatch detection (claim names PMID 12345678 with title X but
record has title Y) is deliberately NOT implemented for v0 — fuzzy title
match without a chemistry-knowledge model produces too many
false-positives. When the next eval pass shows hallucinated titles,
revisit. For now, ID-existence is the v0 contract.
"""
from __future__ import annotations

import re
from typing import Callable

from schemas import LiteratureSearchRequest, LiteratureSearchResponse
from schemas.report import IdentificationReport
from verifier.schemas import (
    ClaimVerdict,
    ClassifiedClaim,
    VerifiedClaim,
)


Fetcher = Callable[[str], LiteratureSearchResponse]


# ---------------------------------------------------------------------------
# ID extraction
# ---------------------------------------------------------------------------

# PMIDs are bare integer strings, typically 1–9 digits. We require an
# anchor (`PMID`, `pmid`, or `pubmed`) to avoid scooping up arbitrary
# numbers (year 2023, mass 12345, etc.) that happen to look like PMIDs.
_PMID_RE = re.compile(
    r"\b(?:PMID|pubmed)[:\s]*(\d{1,9})\b",
    re.IGNORECASE,
)

# DOIs follow `10.<registrant>/<suffix>`. We require an anchor (`DOI`,
# `doi:`) OR the bare 10.NNNN/ form for the few cases the LLM doesn't
# prefix.
_DOI_RE = re.compile(
    r"\b(?:doi[:\s]*)?(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Default fetcher — wraps the production literature_search tool
# ---------------------------------------------------------------------------


def _default_fetcher(id_query: str) -> LiteratureSearchResponse:
    """Build an Europe PMC query that targets a specific PMID or DOI.

    Lazy-imported so unit tests that always pass a mock do not pay the
    import cost (and don't accidentally hit the network).
    """
    from tools.literature import literature_search

    return literature_search(
        LiteratureSearchRequest(
            query=id_query,
            max_results=1,
            sources=["europepmc"],
        )
    )


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def verify_literature(
    claim: ClassifiedClaim,
    source_report: IdentificationReport,
    *,
    fetcher: Fetcher | None = None,
) -> VerifiedClaim:
    """Verify one literature claim. ``fetcher`` defaults to the real
    ``literature_search`` tool but is dependency-injected for tests."""
    pmids = _extract_pmids(claim.claim_text)
    dois = _extract_dois(claim.claim_text)

    if not pmids and not dois:
        return _unverifiable(
            claim,
            evidence=(
                "Layer E found no PMID or DOI in the claim. v0 verifies "
                "identifier-anchored citations only; free-text references "
                "('Smith et al. 2023', 'as published') cannot be adjudicated."
            ),
        )

    # Phase 1 — source-first scan over candidates[*].literature_records.
    src = _try_source_first(claim, source_report, pmids, dois)
    if src is not None:
        return src

    # Phase 2 — tool round-trip via Europe PMC.
    if fetcher is None:
        fetcher = _default_fetcher

    # PMIDs first (more specific), DOIs as fallback.
    for pmid in pmids:
        return _verify_via_roundtrip_pmid(claim, pmid, fetcher=fetcher)
    for doi in dois:
        return _verify_via_roundtrip_doi(claim, doi, fetcher=fetcher)

    # Unreachable — pmids OR dois must be non-empty per the early return.
    return _unverifiable(
        claim, evidence="Layer E reached an impossible branch."
    )


# ---------------------------------------------------------------------------
# Source-first lookup
# ---------------------------------------------------------------------------


def _try_source_first(
    claim: ClassifiedClaim,
    source_report: IdentificationReport,
    pmids: list[str],
    dois: list[str],
) -> VerifiedClaim | None:
    pmid_set = {p.strip() for p in pmids}
    doi_set = {d.strip().lower() for d in dois}

    for i, cr in enumerate(source_report.candidates):
        for j, rec in enumerate(cr.literature_records):
            if pmid_set and rec.pmid in pmid_set:
                path = f"candidates[{i}].literature_records[{j}].pmid"
                return _supported(
                    claim,
                    evidence=f"source {path} = {rec.pmid!r}",
                    source_field=path,
                )
            if doi_set and rec.doi and rec.doi.lower() in doi_set:
                path = f"candidates[{i}].literature_records[{j}].doi"
                return _supported(
                    claim,
                    evidence=f"source {path} = {rec.doi!r}",
                    source_field=path,
                )
    return None


# ---------------------------------------------------------------------------
# Tool round-trip
# ---------------------------------------------------------------------------


def _verify_via_roundtrip_pmid(
    claim: ClassifiedClaim, pmid: str, *, fetcher: Fetcher,
) -> VerifiedClaim:
    """Search Europe PMC for the literal PMID. 1+ result → SUPPORTED;
    0 results → CONTRADICTED."""
    query = f"EXT_ID:{pmid} SRC:MED"
    try:
        resp = fetcher(query)
    except Exception as exc:
        return VerifiedClaim(
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            verdict=ClaimVerdict.ERROR,
            evidence=(
                f"literature_search({query!r}) raised "
                f"{type(exc).__name__}: {exc}"
            ),
            source_field=None,
            correction=None,
        )
    if not resp.records:
        return VerifiedClaim(
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            verdict=ClaimVerdict.CONTRADICTED,
            evidence=(
                f"Europe PMC returned 0 records for PMID {pmid!r} — "
                "claim asserts a PMID that does not resolve."
            ),
            source_field=None,
            correction=None,
        )
    rec = resp.records[0]
    return _supported(
        claim,
        evidence=(
            f"Europe PMC PMID {rec.pmid!r}: {rec.title!r} "
            f"({rec.journal} {rec.year})"
        ),
        source_field=None,
    )


def _verify_via_roundtrip_doi(
    claim: ClassifiedClaim, doi: str, *, fetcher: Fetcher,
) -> VerifiedClaim:
    query = f'DOI:"{doi}"'
    try:
        resp = fetcher(query)
    except Exception as exc:
        return VerifiedClaim(
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            verdict=ClaimVerdict.ERROR,
            evidence=(
                f"literature_search({query!r}) raised "
                f"{type(exc).__name__}: {exc}"
            ),
            source_field=None,
            correction=None,
        )
    if not resp.records:
        return VerifiedClaim(
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            verdict=ClaimVerdict.CONTRADICTED,
            evidence=(
                f"Europe PMC returned 0 records for DOI {doi!r} — "
                "claim asserts a DOI that does not resolve."
            ),
            source_field=None,
            correction=None,
        )
    rec = resp.records[0]
    return _supported(
        claim,
        evidence=(
            f"Europe PMC DOI {rec.doi!r}: {rec.title!r} "
            f"(PMID {rec.pmid})"
        ),
        source_field=None,
    )


# ---------------------------------------------------------------------------
# ID extractors
# ---------------------------------------------------------------------------


def _extract_pmids(text: str) -> list[str]:
    """Return PMIDs found in ``text``. Anchor-required (PMID:NNN /
    pubmed NNN) to avoid year/mass false positives."""
    seen: list[str] = []
    for m in _PMID_RE.finditer(text):
        pmid = m.group(1)
        if pmid not in seen:
            seen.append(pmid)
    return seen


def _extract_dois(text: str) -> list[str]:
    seen: list[str] = []
    for m in _DOI_RE.finditer(text):
        doi = m.group(1).rstrip(".,;:)")  # strip trailing punctuation
        if doi.lower() not in {d.lower() for d in seen}:
            seen.append(doi)
    return seen


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _supported(
    claim: ClassifiedClaim,
    *,
    evidence: str,
    source_field: str | None,
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
    claim: ClassifiedClaim,
    *,
    evidence: str,
    source_field: str | None = None,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence=evidence,
        source_field=source_field,
        correction=None,
    )
