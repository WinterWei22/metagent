"""Resolve verifier claims to IdentificationReport candidates.

Resolution is intentionally conservative. A claim without a clear subject,
SMILES, database id, or rank cue does not bind to top-1 by default.
"""
from __future__ import annotations

import re
from typing import Union

from schemas.report import CandidateReport, IdentificationReport
from verifier.claim_fields import normalize_claim_text, parse_claim_fields
from verifier.schemas import CandidateRef, ClassifiedClaim, ExtractedClaim, VerifiedClaim


ClaimLike = Union[ExtractedClaim, ClassifiedClaim, VerifiedClaim]

_TOP_CANDIDATE_RE = re.compile(
    r"\b(top|highest[-\s]?scoring|best[-\s]?scoring|rank(?:ed)?\s*1|#\s*1)\b",
    re.IGNORECASE,
)


def resolve_candidate_ref(
    claim: ClaimLike,
    source_report: IdentificationReport,
) -> CandidateRef | None:
    """Return a structured candidate reference, or None when ambiguous."""
    fields = getattr(claim, "extracted_fields", None) or parse_claim_fields(claim.claim_text)
    subject = getattr(claim, "subject", None)
    normalized_subject = _norm(subject) if subject else None

    if normalized_subject:
        for i, cr in enumerate(source_report.candidates):
            if _norm(cr.candidate.name) == normalized_subject:
                return _ref(i, cr, "candidate.name")

        for i, cr in enumerate(source_report.candidates):
            mi = cr.metabolite_info
            if mi is not None and _norm(mi.primary_name) == normalized_subject:
                return _ref(i, cr, "metabolite_info.primary_name")

        for i, cr in enumerate(source_report.candidates):
            mi = cr.metabolite_info
            if mi is None:
                continue
            if any(_norm(s) == normalized_subject for s in mi.synonyms):
                return _ref(i, cr, "metabolite_info.synonym")

    for smiles in _smiles_mentions(claim.claim_text, fields.smiles):
        for i, cr in enumerate(source_report.candidates):
            if cr.candidate.smiles == smiles:
                return _ref(i, cr, "candidate.smiles")
            mi = cr.metabolite_info
            if mi is not None and mi.smiles == smiles:
                return _ref(i, cr, "metabolite_info.smiles")

    inchikey = fields.inchikey
    if inchikey:
        for i, cr in enumerate(source_report.candidates):
            mi = cr.metabolite_info
            if mi is None:
                continue
            if mi.inchikey and mi.inchikey.upper() == inchikey.upper():
                return _ref(i, cr, "metabolite_info.inchikey")
            for key, value in mi.cross_refs.items():
                if key.lower() == "inchikey" and value.upper() == inchikey.upper():
                    return _ref(i, cr, "metabolite_info.cross_refs.inchikey")

    if fields.database_name and fields.database_id:
        ref = _match_database_id(source_report, fields.database_name, fields.database_id)
        if ref is not None:
            return ref

    if fields.rank is not None:
        idx = fields.rank - 1
        if 0 <= idx < len(source_report.candidates):
            return _ref(idx, source_report.candidates[idx], "rank")

    if _TOP_CANDIDATE_RE.search(claim.claim_text) and source_report.candidates:
        return _ref(0, source_report.candidates[0], "top_candidate_phrase")

    return None


def _match_database_id(
    report: IdentificationReport,
    db_name: str,
    db_id: str,
) -> CandidateRef | None:
    wanted = _norm_db_value(db_id, db_name)
    for i, cr in enumerate(report.candidates):
        mi = cr.metabolite_info
        if mi is None:
            continue
        if db_name == "inchikey" and mi.inchikey:
            if mi.inchikey.upper() == db_id.upper():
                return _ref(i, cr, "metabolite_info.inchikey")
        stored = mi.cross_refs.get(db_name, "")
        if stored and _norm_db_value(stored, db_name) == wanted:
            return _ref(i, cr, f"metabolite_info.cross_refs.{db_name}")
    return None


def _ref(index: int, cr: CandidateReport, match_method: str) -> CandidateRef:
    mi = cr.metabolite_info
    name = cr.candidate.name or (mi.primary_name if mi is not None else None)
    inchikey = mi.inchikey if mi is not None else None
    return CandidateRef(
        index=index,
        path=f"candidates[{index}]",
        name=name,
        smiles=cr.candidate.smiles,
        inchikey=inchikey,
        source_id=cr.candidate.source_id,
        match_method=match_method,
    )


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return normalize_claim_text(value).strip().lower()


def _norm_db_value(value: str, db_name: str) -> str:
    v = value.strip().upper()
    if db_name == "chebi":
        v = v.removeprefix("CHEBI:").removeprefix("CHEBI_").removeprefix("CHEBI-")
    if db_name == "pubchem_cid":
        for prefix in ("CID:", "CID-", "CID_", "PUBCHEM CID"):
            v = v.removeprefix(prefix)
        v = v.strip()
    return v


def _extract_smiles_like(text: str) -> str | None:
    # First-stage pragmatic support: only match exact candidate SMILES later;
    # this avoids treating ordinary prose as a SMILES.
    for token in re.findall(r"`([^`]+)`|(\S+)", text):
        raw = token[0] or token[1]
        if any(ch in raw for ch in ("=", "#", "(", ")", "[", "]")):
            return raw.strip(".,;:")
    return None


def _smiles_mentions(text: str, parsed_smiles: str | None) -> list[str]:
    mentions: list[str] = []
    if parsed_smiles:
        mentions.append(parsed_smiles)

    explicit = re.search(r"\bSMILES\s+([^\s,;]+)", text, re.IGNORECASE)
    if explicit:
        mentions.append(explicit.group(1).strip(".,;:"))

    smiles_like = _extract_smiles_like(text)
    if smiles_like:
        mentions.append(smiles_like)

    # Conservative fallback for short exact SMILES such as "CCO": these are
    # only used for exact matching against candidate strings.
    for token in re.findall(r"\b[A-Za-z0-9@+\-\[\]\(\)=#/\\]+\b", text):
        if len(token) >= 2 and any(ch.isupper() for ch in token):
            mentions.append(token.strip(".,;:"))

    out: list[str] = []
    for item in mentions:
        if item and item not in out:
            out.append(item)
    return out
