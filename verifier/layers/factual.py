"""Layer B — verify Type 2 (factual round-trip) claims.

A factual claim is one that names an external database entity — an HMDB
ID, KEGG compound ID, CID, ChEBI ID, or InChIKey — and asserts something
about it.

Two-pass strategy:

1. **Source-first.** If the claimed ID already appears in
   ``source_report.candidates[*].metabolite_info.cross_refs`` (or
   ``inchikey``), Layer B can verify the claim by lookup, without calling
   any external tool. This handles H4 cleanly when the LLM repeats an ID
   the formatter already showed it.

2. **Tool round-trip.** If the ID is not in source, call
   ``fetch_metabolite_info(identifier)`` and verify against the tool's
   response. ``fetcher`` is dependency-injected so unit tests never need
   to spin up HMDB/PubChem.

Aliasing tolerance (H5 design): name mismatches alone never produce a
``CONTRADICTED`` verdict. If the claimed name does not match
``primary_name`` or any synonym, but the database ID resolves, the
verdict is ``UNVERIFIABLE_V0`` — never ``CONTRADICTED``. The Track V
brief is explicit on this: never hard-reject on name difference alone.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any, Callable

from schemas.molecule import MetaboliteInfoRequest, MetaboliteInfoResponse
from schemas.report import CandidateReport, IdentificationReport
from verifier.schemas import (
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    VerifiedClaim,
)
from verifier.source_lookup import find_candidate_by_name


Fetcher = Callable[[str], MetaboliteInfoResponse]
ClassyfireClassifier = Callable[[Any], Any]


# ---------------------------------------------------------------------------
# ID extraction
# ---------------------------------------------------------------------------

_HMDB_RE = re.compile(r"\b(HMDB\d{6,})\b", re.IGNORECASE)
_KEGG_C_RE = re.compile(r"\b(C\d{5})\b")
_CHEBI_RE = re.compile(r"\bCHEBI[:_-]?(\d+)\b", re.IGNORECASE)
_CID_RE = re.compile(r"\bCID[:_-]?(\d+)\b", re.IGNORECASE)
_INCHIKEY_RE = re.compile(r"\b([A-Z]{14}-[A-Z]{10}-[A-Z])\b")
_CCMSLIB_RE = re.compile(r"\b(CCMSLIB\d+)\b", re.IGNORECASE)

_ID_EXTRACTORS: list[tuple[re.Pattern, str]] = [
    (_HMDB_RE, "hmdb"),
    (_INCHIKEY_RE, "inchikey"),
    (_CHEBI_RE, "chebi"),
    (_CID_RE, "pubchem_cid"),
    (_CCMSLIB_RE, "ccmslib"),
    (_KEGG_C_RE, "kegg"),
]

_CLASS_CLAIM_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bis\s+an?\s+.+",
        r"\bbelongs\s+to\s+.+",
        r"\bclassified\s+as\s+.+",
        r"\bclass(?:ified|ification)?\b",
        r"\btype\s+of\s+.+",
    )
]

_CHEMICAL_CLASS_TERMS = [
    "purine alkaloid",
    "amino acid",
    "fatty acid",
    "carboxylic acid",
    "organic acid",
    "carbonyl compound",
    "organonitrogen compound",
    "organooxygen compound",
    "monosaccharide",
    "disaccharide",
    "oligosaccharide",
    "polysaccharide",
    "carbohydrate",
    "nucleoside",
    "nucleotide",
    "phenylpropanoid",
    "polyketide",
    "flavonoid",
    "terpenoid",
    "terpene",
    "alkaloid",
    "steroid",
    "lipid",
    "hexose",
    "xanthine",
    "purine",
    "pyrimidine",
    "peptide",
    "sugar",
]


def _extract_ids(claim_text: str) -> list[tuple[str, str]]:
    """Return ``[(id_type, id_value), ...]`` extracted from claim_text."""
    out: list[tuple[str, str]] = []
    for pattern, kind in _ID_EXTRACTORS:
        for m in pattern.finditer(claim_text):
            value = m.group(1)
            # Normalise representation
            if kind == "chebi":
                value = f"CHEBI:{value}" if not value.upper().startswith("CHEBI") else value
            elif kind == "pubchem_cid":
                value = value  # bare digit string; cross_refs may store either form
            out.append((kind, value))
    return out


def _ids_from_claim(claim: ClassifiedClaim) -> list[tuple[str, str]]:
    fields = claim.extracted_fields
    if fields.database_name and fields.database_id:
        return [(fields.database_name, fields.database_id)]
    if fields.inchikey:
        return [("inchikey", fields.inchikey)]
    return _extract_ids(claim.claim_text)


# ---------------------------------------------------------------------------
# Default fetcher — lazy imported to avoid heavy initialisation at module load
# ---------------------------------------------------------------------------


def _default_fetcher(identifier: str) -> MetaboliteInfoResponse:
    """Wrap ``tools.metabolite_info.tool.fetch_metabolite_info`` for the
    Layer B signature. Lazy-imported so unit tests that always pass a mock
    do not pay the import cost.
    """
    from tools.metabolite_info.tool import fetch_metabolite_info

    return fetch_metabolite_info(
        MetaboliteInfoRequest(identifier=identifier, id_type="auto")
    )


def _default_classyfire_classifier(request: Any) -> Any:
    """Lazy wrapper around the ClassyFire tool."""
    from tools.classyfire import classify_structure

    return classify_structure(request)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def verify_factual(
    claim: ClassifiedClaim,
    source_report: IdentificationReport,
    *,
    fetcher: Fetcher | None = None,
    classyfire_fn: ClassyfireClassifier | None = None,
) -> VerifiedClaim:
    """Verify one factual round-trip claim.

    ``fetcher`` defaults to the real ``fetch_metabolite_info`` tool but
    can be replaced with any callable taking an identifier and returning
    a ``MetaboliteInfoResponse`` — used by tests to avoid hitting HMDB.
    """
    ids = _ids_from_claim(claim)

    if not ids and is_chemical_class_claim(claim.claim_text):
        return _verify_via_classyfire(
            claim, source_report, classyfire_fn=classyfire_fn,
        )

    if not ids:
        # No usable anchor. We cannot verify a name-only factual claim
        # without a database ID — would have to do free-text disambiguation.
        return _unverifiable(
            claim,
            evidence=(
                "Layer B found no database ID in the claim. Name-only "
                "factual claims are out of v0 scope."
            ),
        )

    # Phase 1 — source-first: try to find the ID in source_report.
    src_result = _try_source_first(claim, source_report, ids)
    if src_result is not None:
        return src_result

    # Phase 2 — tool round-trip: lookup the first ID via the fetcher.
    if fetcher is None:
        fetcher = _default_fetcher
    return _verify_via_roundtrip(claim, ids, fetcher=fetcher)


# ---------------------------------------------------------------------------
# Phase 1 — source-first
# ---------------------------------------------------------------------------


def _try_source_first(
    claim: ClassifiedClaim,
    source_report: IdentificationReport,
    ids: list[tuple[str, str]],
) -> VerifiedClaim | None:
    """Look up each ID in source_report.cross_refs. Return None if none
    of the IDs appear in source — caller falls through to tool round-trip.
    """
    for kind, value in ids:
        for i, cr in enumerate(source_report.candidates):
            mi = cr.metabolite_info
            if mi is None:
                continue
            # InChIKey lives at top level, not in cross_refs.
            if kind == "inchikey":
                if mi.inchikey and mi.inchikey.upper() == value.upper():
                    path = f"candidates[{i}].metabolite_info.inchikey"
                    return _matched_in_source(
                        claim, kind, value, mi, cr, path,
                    )
                continue
            xref = mi.cross_refs.get(kind, "")
            # Defensive: cross_refs values may carry "CHEBI:" prefix
            # variation; compare case-insensitively and strip prefixes.
            if _xref_match(xref, value, kind):
                path = f"candidates[{i}].metabolite_info.cross_refs[{kind}]"
                return _matched_in_source(
                    claim, kind, value, mi, cr, path,
                )
    return None


def _xref_match(stored: str, claimed: str, kind: str) -> bool:
    if not stored:
        return False
    s = stored.strip().upper()
    c = claimed.strip().upper()
    if s == c:
        return True
    # Strip prefixes for ChEBI, CID
    for prefix in ("CHEBI:", "CID:", "CID-", "CID_"):
        if s.startswith(prefix):
            s = s[len(prefix):]
        if c.startswith(prefix):
            c = c[len(prefix):]
    return s == c


def _matched_in_source(
    claim: ClassifiedClaim,
    id_kind: str,
    id_value: str,
    matched_info: MetaboliteInfoResponse,
    matched_cr: CandidateReport,
    path: str,
) -> VerifiedClaim:
    """We found the claimed ID in source. If the claim also names a
    subject, confirm the names line up (with synonym tolerance)."""
    if claim.subject:
        if not _name_matches(claim.subject, matched_info, matched_cr):
            return _unverifiable(
                claim,
                evidence=(
                    f"ID {id_value} found at {path}, but claim subject "
                    f"{claim.subject!r} did not match primary_name "
                    f"({matched_info.primary_name!r}) or any synonym. "
                    "Cannot adjudicate name disagreement at v0 — see "
                    "Track V H5 design note."
                ),
                source_field=path,
            )
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.SUPPORTED,
        evidence=f"source {path} = {id_value}",
        source_field=path,
        correction=None,
        extracted_fields=claim.extracted_fields,
        evidence_refs=[],
        verifier_layer="factual",
        trace_summary=f"source {path} = {id_value}",
    )


# ---------------------------------------------------------------------------
# Phase 2 — tool round-trip
# ---------------------------------------------------------------------------


def _verify_via_roundtrip(
    claim: ClassifiedClaim,
    ids: list[tuple[str, str]],
    *,
    fetcher: Fetcher,
) -> VerifiedClaim:
    """Call the metabolite-info tool for the first extracted ID and
    verify against the response."""
    kind, value = ids[0]
    try:
        info = fetcher(value)
    except Exception as exc:  # tool raised — surface as ERROR, do not retry
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            claim_subtype=claim.claim_subtype,
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.ERROR,
            evidence=(
                f"fetch_metabolite_info({value!r}) raised "
                f"{type(exc).__name__}: {exc}"
            ),
            source_field=None,
            correction=None,
            extracted_fields=claim.extracted_fields,
            verifier_layer="factual",
            tool_called="metabolite_info",
            trace_summary=f"fetch_metabolite_info({value!r}) raised",
        )

    if not info.found:
        # The ID did not resolve in any configured backend. This could
        # mean (a) the LLM hallucinated the ID, OR (b) the ID is valid
        # in a backend the local install does not have (HMDB has no
        # PubChem-only CIDs unless METAGENT_ALLOW_PUBCHEM is set;
        # PubChem-CID claims will commonly land here).
        #
        # We cannot distinguish (a) from (b) without more backends.
        # Conservative call: UNVERIFIABLE_V0 in both branches. Returning
        # CONTRADICTED on backend coverage gaps would falsely flag the
        # honest LLM behaviour observed on the L-carnitine fixture's
        # CID:218057 claim.
        return _unverifiable(
            claim,
            evidence=(
                f"fetch_metabolite_info({value!r}) returned found=False. "
                "Could be a hallucinated ID or a coverage gap (e.g. "
                "PubChem-only CID with METAGENT_ALLOW_PUBCHEM unset); "
                "v0 cannot disambiguate."
            ),
            tool_called="metabolite_info",
        )

    # Tool resolved the ID. Now check the claimed subject (if any) against
    # primary_name / synonyms.
    if claim.subject:
        if _info_name_matches(claim.subject, info):
            return VerifiedClaim(
                claim_id=claim.claim_id,
                claim_text=claim.claim_text,
                claim_type=claim.claim_type,
                claim_subtype=claim.claim_subtype,
                subject=claim.subject,
                subject_kind=claim.subject_kind,
                candidate_ref=claim.candidate_ref,
                verdict=ClaimVerdict.SUPPORTED,
                evidence=(
                    f"fetch_metabolite_info({value!r}) -> primary_name="
                    f"{info.primary_name!r}, claim names {claim.subject!r}"
                ),
                source_field=None,
                correction=None,
                extracted_fields=claim.extracted_fields,
                verifier_layer="factual",
                tool_called="metabolite_info",
                trace_summary=f"fetch_metabolite_info({value!r}) resolved",
            )
        # Per H5 design: never CONTRADICTED on names alone.
        return _unverifiable(
            claim,
            evidence=(
                f"fetch_metabolite_info({value!r}) -> primary_name="
                f"{info.primary_name!r} synonyms={info.synonyms[:3]!r}; "
                f"claim names {claim.subject!r}. No canonical-ID basis to "
                "judge name disagreement — see Track V H5 note."
            ),
            tool_called="metabolite_info",
        )

    # No subject — only the ID was asserted, and the tool resolved it.
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.SUPPORTED,
        evidence=(
            f"fetch_metabolite_info({value!r}) returned found=True"
        ),
        source_field=None,
        correction=None,
        extracted_fields=claim.extracted_fields,
        verifier_layer="factual",
        tool_called="metabolite_info",
        trace_summary=f"fetch_metabolite_info({value!r}) returned found=True",
    )


# ---------------------------------------------------------------------------
# ClassyFire taxonomy branch
# ---------------------------------------------------------------------------


def is_chemical_class_claim(claim_text: str) -> bool:
    """Heuristic for taxonomy claims handled by ClassyFire."""
    low = _norm(claim_text)
    if not any(term in low for term in _CHEMICAL_CLASS_TERMS):
        return False
    return any(p.search(claim_text) for p in _CLASS_CLAIM_PATTERNS)


def _verify_via_classyfire(
    claim: ClassifiedClaim,
    source_report: IdentificationReport,
    *,
    classyfire_fn: ClassyfireClassifier | None,
) -> VerifiedClaim:
    smiles = _get_smiles_for_claim(claim, source_report)
    if smiles is None:
        return _unverifiable(
            claim,
            evidence="No SMILES available for ClassyFire lookup",
        )
    claimed_class = _extract_class_from_claim(claim.claim_text)
    if claimed_class is None:
        return _unverifiable(
            claim,
            evidence="Layer B could not extract the claimed chemical class.",
        )

    if classyfire_fn is None:
        try:
            from tools.classyfire import ClassifyStructureRequest
        except ModuleNotFoundError as exc:
            return _unverifiable(
                claim,
                evidence=f"ClassyFire not available in this environment: {exc}",
            )
        request = ClassifyStructureRequest(smiles=smiles)
        classyfire_fn = _default_classyfire_classifier
    else:
        request = SimpleNamespace(smiles=smiles)

    try:
        resp = classyfire_fn(request)
    except Exception as exc:
        if _exception_name(exc) == "ClassyfireNotFoundError":
            return _unverifiable(
                claim,
                evidence="Compound not in ClassyFire database (novel or rare compound)",
                tool_called="classyfire",
            )
        if _exception_name(exc) == "InvalidStructureError":
            return _unverifiable(
                claim,
                evidence=f"ClassyFire could not classify invalid structure: {exc}",
                tool_called="classyfire",
            )
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            claim_subtype=claim.claim_subtype,
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.ERROR,
            evidence=(
                f"classify_structure(smiles=...) raised "
                f"{type(exc).__name__}: {exc}"
            ),
            extracted_fields=claim.extracted_fields,
            verifier_layer="factual",
            tool_called="classyfire",
            trace_summary="classify_structure(smiles=...) raised",
        )

    direct_parent = resp.direct_parent.name if resp.direct_parent else "unknown"
    if resp.matches_claim(claimed_class):
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            claim_subtype=claim.claim_subtype,
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.SUPPORTED,
            evidence=(
                f"ClassyFire confirms: {direct_parent} "
                f"(source: {resp.source})"
            ),
            extracted_fields=claim.extracted_fields,
            verifier_layer="factual",
            tool_called="classyfire",
            trace_summary=f"ClassyFire confirms {direct_parent}",
        )

    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.CONTRADICTED,
        evidence=(
            f"ClassyFire classifies this compound as {direct_parent!r}, "
            f"not {claimed_class!r}."
        ),
        correction=direct_parent if direct_parent != "unknown" else None,
        extracted_fields=claim.extracted_fields,
        verifier_layer="factual",
        tool_called="classyfire",
        trace_summary=f"ClassyFire classified as {direct_parent}",
    )


def _extract_class_from_claim(claim_text: str) -> str | None:
    low = _norm(claim_text)
    for term in sorted(_CHEMICAL_CLASS_TERMS, key=len, reverse=True):
        if term in low:
            return term
    return None


def _get_smiles_for_claim(
    claim: ClassifiedClaim,
    source_report: IdentificationReport,
) -> str | None:
    if claim.candidate_ref is not None and claim.candidate_ref.smiles:
        return claim.candidate_ref.smiles
    if claim.extracted_fields.smiles:
        return claim.extracted_fields.smiles
    if claim.subject:
        by_subject, _ = find_candidate_by_name(source_report, claim.subject)
        if by_subject is not None and by_subject.candidate.smiles:
            return by_subject.candidate.smiles

    low = _norm(claim.claim_text)
    for cr in source_report.candidates:
        if cr.candidate.name and _norm(cr.candidate.name) in low:
            return cr.candidate.smiles
        mi = cr.metabolite_info
        if mi is None:
            continue
        if mi.primary_name and _norm(mi.primary_name) in low:
            return cr.candidate.smiles
        for syn in mi.synonyms:
            if _norm(syn) in low:
                return cr.candidate.smiles

    if len(source_report.candidates) == 1:
        return source_report.candidates[0].candidate.smiles
    return None


def _exception_name(exc: Exception) -> str:
    return type(exc).__name__


# ---------------------------------------------------------------------------
# Name matching helpers
# ---------------------------------------------------------------------------


def _norm(s: str) -> str:
    return s.strip().lower()


def _name_matches(
    needle: str, info: MetaboliteInfoResponse, cr: CandidateReport
) -> bool:
    """True iff ``needle`` matches the candidate's name, primary_name, or
    any synonym (case-insensitive)."""
    n = _norm(needle)
    if cr.candidate.name and _norm(cr.candidate.name) == n:
        return True
    return _info_name_matches(needle, info)


def _info_name_matches(needle: str, info: MetaboliteInfoResponse) -> bool:
    n = _norm(needle)
    if info.primary_name and _norm(info.primary_name) == n:
        return True
    return any(_norm(s) == n for s in info.synonyms)


def _unverifiable(
    claim: ClassifiedClaim,
    *,
    evidence: str,
    source_field: str | None = None,
    tool_called: str | None = None,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence=evidence,
        source_field=source_field,
        correction=None,
        extracted_fields=claim.extracted_fields,
        verifier_layer="factual",
        tool_called=tool_called,
        trace_summary=evidence,
    )
