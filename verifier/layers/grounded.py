"""Layer A — verify Type 1 (grounded) claims against ``IdentificationReport``.

Highest-volume layer. No LLM calls, no tool calls — pure lookup in the
source report that was fed to the orchestrator.

Design: a chain of *field extractors*. Each extractor takes the claim
text and tries to recognise what property is being asserted (molecular
formula, evidence_score, cosine, B/C, ppm, mass_match). The first
extractor that recognises a field is authoritative; the rest are
skipped. A claim with no recognised field returns ``UNSUPPORTED``
with ``source_field=None`` — which is also the correct verdict for
the H2 family (LLM invented a numeric quantity whose scalar form the
pipeline never emits).

Verdict semantics (Layer-A-local):

* ``SUPPORTED`` — field resolved; asserted value agrees with source.
* ``CONTRADICTED`` — field resolved; asserted value disagrees.
  ``correction`` populated with the source value.
* ``UNSUPPORTED`` — field cannot be resolved (wrong subject, wrong
  field name, asserted scalar has no corresponding scalar in source).
  H2's "<1 ppm" lands here.
* ``UNVERIFIABLE_V0`` — field resolved but source has ``None`` legitimately
  (e.g. ``metabolite_info`` degraded to None). Layer A cannot adjudicate.
"""
from __future__ import annotations

import re

from schemas.report import CandidateReport, IdentificationReport
from verifier.schemas import (
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
    EvidenceRef,
    VerifiedClaim,
)
from verifier.source_lookup import find_candidate_by_name


# ---------------------------------------------------------------------------
# Regexes used by individual extractors
# ---------------------------------------------------------------------------

_FORMULA_RE = re.compile(
    r"\b(C\d{1,3}H\d{1,3}(?:[A-Z][a-z]?\d{0,3})*)\b"
)
_EVIDENCE_SCORE_RE = re.compile(
    r"evidence[_\s-]*score[^\d-]*?(-?\d+\.\d+|-?\d+)", re.IGNORECASE
)
_COSINE_RE = re.compile(
    r"(?:predicted[\s-]*spectrum\s+)?cosine(?:\s+similarity)?[^\d-]*?(-?\d+\.\d+|-?\d+)",
    re.IGNORECASE,
)
_BC_RE = re.compile(
    r"(?:B\s*/\s*C|candidate[\s_]*score)[^\d-]*?(-?\d+\.\d+|-?\d+)",
    re.IGNORECASE,
)
_PPM_RE = re.compile(
    r"(?:<\s*|below\s+|under\s+|less\s+than\s+)?(\d+\.?\d*)\s*ppm",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def verify_grounded(
    claim: ClassifiedClaim, source_report: IdentificationReport
) -> VerifiedClaim:
    """Verify one grounded claim against ``source_report``. Pure."""
    cand: CandidateReport | None = None
    cand_idx: int | None = None
    if claim.candidate_ref is not None and claim.candidate_ref.index is not None:
        idx = claim.candidate_ref.index
        if 0 <= idx < len(source_report.candidates):
            cand, cand_idx = source_report.candidates[idx], idx
    if cand is None and claim.subject:
        cand, cand_idx = find_candidate_by_name(source_report, claim.subject)

    for extractor in (
        _check_typed_spectrum_field,
        _check_typed_rank,
        _check_formula,
        _check_typed_score,
        _check_evidence_score,
        _check_cosine,
        _check_bc_score,
        _check_ppm,
    ):
        result = extractor(claim, source_report, cand, cand_idx)
        if result is not None:
            return result

    return _unsupported(
        claim,
        evidence=(
            "Layer A could not map this claim to any known source field."
            + (f" Subject {claim.subject!r} not matched to any candidate."
               if claim.subject and cand is None else "")
        ),
    )


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


def _check_formula(
    claim: ClassifiedClaim,
    report: IdentificationReport,
    cand: CandidateReport | None,
    cand_idx: int | None,
) -> VerifiedClaim | None:
    """Match a claim like 'D-Gulose has molecular formula C7H14O7'.

    Unicode-subscript variants ('C₆H₁₂O₆') are normalised to ASCII before
    matching — H1 in the real glucose fixture uses subscripts.
    """
    typed_formula = claim.extracted_fields.formula
    if typed_formula is None and "formula" not in claim.claim_text.lower():
        # A bare 'C6H12O6' mentioned without the keyword 'formula' is
        # ambiguous (it might be part of a pathway description). Require
        # an explicit 'formula' cue.
        return None
    m = _FORMULA_RE.search(_normalise_formula_text(claim.claim_text))
    if typed_formula is None and not m:
        return None
    asserted = typed_formula or m.group(1)

    if cand is None or cand.metabolite_info is None:
        return _unsupported(
            claim,
            evidence=(
                f"Claim asserts formula {asserted!r} but subject "
                f"{claim.subject!r} has no metabolite_info in source_report."
            ),
        )
    source_formula = cand.metabolite_info.molecular_formula
    path = f"candidates[{cand_idx}].metabolite_info.molecular_formula"
    if source_formula is None:
        return _unverifiable(
            claim,
            evidence=f"metabolite_info.molecular_formula is None at {path}",
            source_field=path,
        )

    if _normalise_formula(asserted) == _normalise_formula(source_formula):
        return _supported(
            claim,
            evidence=f"source {path} = {source_formula!r}, claim asserts {asserted!r}",
            source_field=path,
        )
    return _contradicted(
        claim,
        evidence=(
            f"source {path} = {source_formula!r}, claim asserts {asserted!r}"
        ),
        source_field=path,
        correction=source_formula,
    )


def _check_typed_score(
    claim: ClassifiedClaim,
    report: IdentificationReport,
    cand: CandidateReport | None,
    cand_idx: int | None,
) -> VerifiedClaim | None:
    fields = claim.extracted_fields
    if fields.score_name is None or fields.score_value is None:
        return None
    if cand is None:
        return _unsupported(
            claim,
            evidence=(
                f"Claim asserts {fields.score_name} {fields.score_value} but "
                f"subject {claim.subject!r} not matched to any candidate."
            ),
        )
    if fields.score_name == "evidence_score":
        return _compare_numeric(
            claim,
            asserted=fields.score_value,
            source=cand.evidence_score,
            source_field=f"candidates[{cand_idx}].evidence_score",
            tolerance=1e-3,
        )
    if fields.score_name == "candidate_score":
        return _compare_numeric(
            claim,
            asserted=fields.score_value,
            source=cand.candidate.score,
            source_field=f"candidates[{cand_idx}].candidate.score",
            tolerance=1e-3,
        )
    if fields.score_name == "predicted_cosine":
        path = f"candidates[{cand_idx}].predicted_spectrum_cosine"
        if cand.predicted_spectrum_cosine is None:
            return _unverifiable(
                claim,
                evidence=f"{path} is None (spectrum prediction skipped)",
                source_field=path,
            )
        return _compare_numeric(
            claim,
            asserted=fields.score_value,
            source=cand.predicted_spectrum_cosine,
            source_field=path,
            tolerance=1e-3,
        )
    return None


def _check_typed_rank(
    claim: ClassifiedClaim,
    report: IdentificationReport,
    cand: CandidateReport | None,
    cand_idx: int | None,
) -> VerifiedClaim | None:
    rank = claim.extracted_fields.rank
    if rank is None:
        return None
    if cand_idx is None:
        return _unsupported(
            claim,
            evidence=f"Claim asserts rank {rank}, but no candidate_ref resolved.",
        )
    asserted_idx = rank - 1
    path = f"candidates[{cand_idx}]"
    if asserted_idx == cand_idx:
        return _supported(
            claim,
            evidence=f"candidate_ref {path} matches asserted rank {rank}",
            source_field=path,
        )
    correction = str(cand_idx + 1)
    return _contradicted(
        claim,
        evidence=f"candidate_ref {path} does not match asserted rank {rank}",
        source_field=path,
        correction=correction,
    )


def _check_typed_spectrum_field(
    claim: ClassifiedClaim,
    report: IdentificationReport,
    cand: CandidateReport | None,
    cand_idx: int | None,
) -> VerifiedClaim | None:
    fields = claim.extracted_fields
    if fields.precursor_mz is not None:
        return _compare_numeric(
            claim,
            asserted=fields.precursor_mz,
            source=report.experimental_spectrum.precursor_mz,
            source_field="experimental_spectrum.precursor_mz",
            tolerance=1e-4,
        )
    if fields.neutral_mass is not None:
        return _compare_numeric(
            claim,
            asserted=fields.neutral_mass,
            source=report.neutral_mass_computed,
            source_field="neutral_mass_computed",
            tolerance=1e-2,
        )
    if fields.adduct is not None and "adduct" in claim.claim_text.lower():
        source = report.experimental_spectrum.adduct
        if fields.adduct == source:
            return _supported(
                claim,
                evidence=f"source experimental_spectrum.adduct = {source!r}",
                source_field="experimental_spectrum.adduct",
            )
        return _contradicted(
            claim,
            evidence=(
                f"source experimental_spectrum.adduct = {source!r}, "
                f"claim asserts {fields.adduct!r}"
            ),
            source_field="experimental_spectrum.adduct",
            correction=source,
        )
    return None


def _check_evidence_score(
    claim: ClassifiedClaim,
    report: IdentificationReport,
    cand: CandidateReport | None,
    cand_idx: int | None,
) -> VerifiedClaim | None:
    m = _EVIDENCE_SCORE_RE.search(claim.claim_text)
    if not m:
        return None
    asserted = float(m.group(1))
    if cand is None:
        return _unsupported(
            claim,
            evidence=(
                f"Claim asserts evidence_score {asserted} but subject "
                f"{claim.subject!r} not matched to any candidate."
            ),
        )
    path = f"candidates[{cand_idx}].evidence_score"
    return _compare_numeric(
        claim, asserted=asserted, source=cand.evidence_score,
        source_field=path, tolerance=1e-3,
    )


def _check_cosine(
    claim: ClassifiedClaim,
    report: IdentificationReport,
    cand: CandidateReport | None,
    cand_idx: int | None,
) -> VerifiedClaim | None:
    m = _COSINE_RE.search(claim.claim_text)
    if not m:
        return None
    asserted = float(m.group(1))
    if cand is None:
        return _unsupported(
            claim,
            evidence=(
                f"Claim asserts cosine {asserted} but subject "
                f"{claim.subject!r} not matched to any candidate."
            ),
        )
    path = f"candidates[{cand_idx}].predicted_spectrum_cosine"
    src = cand.predicted_spectrum_cosine
    if src is None:
        return _unverifiable(
            claim,
            evidence=f"{path} is None (spectrum prediction skipped)",
            source_field=path,
        )
    return _compare_numeric(
        claim, asserted=asserted, source=src,
        source_field=path, tolerance=1e-3,
    )


def _check_bc_score(
    claim: ClassifiedClaim,
    report: IdentificationReport,
    cand: CandidateReport | None,
    cand_idx: int | None,
) -> VerifiedClaim | None:
    m = _BC_RE.search(claim.claim_text)
    if not m:
        return None
    asserted = float(m.group(1))
    if cand is None:
        return _unsupported(
            claim,
            evidence=(
                f"Claim asserts B/C {asserted} but subject "
                f"{claim.subject!r} not matched to any candidate."
            ),
        )
    path = f"candidates[{cand_idx}].candidate.score"
    return _compare_numeric(
        claim, asserted=asserted, source=cand.candidate.score,
        source_field=path, tolerance=1e-3,
    )


def _check_ppm(
    claim: ClassifiedClaim,
    report: IdentificationReport,
    cand: CandidateReport | None,
    cand_idx: int | None,
) -> VerifiedClaim | None:
    """A ppm scalar claim is never supported by the pipeline.

    The pipeline emits ``mass_match_indicator`` as a binary (1.0 iff the
    SMILES-derived mass is within 5 ppm of neutral_mass_computed). There
    is no per-candidate scalar ppm in ``IdentificationReport``. A claim
    asserting a specific ppm value (e.g. "<1 ppm") therefore fails on
    *field-shape mismatch* and is UNSUPPORTED. This is the H2 catch.
    """
    m = _PPM_RE.search(claim.claim_text)
    if not m:
        return None
    asserted_ppm = m.group(1)
    return _unsupported(
        claim,
        evidence=(
            f"Claim asserts {asserted_ppm} ppm, but the pipeline emits "
            f"only a binary mass_match_indicator (5 ppm gate). No "
            f"per-candidate scalar ppm exists in source_report."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compare_numeric(
    claim: ClassifiedClaim,
    *,
    asserted: float,
    source: float,
    source_field: str,
    tolerance: float,
) -> VerifiedClaim:
    if abs(asserted - source) <= tolerance:
        return _supported(
            claim,
            evidence=(
                f"source {source_field} = {source}, claim asserts {asserted} "
                f"(within {tolerance})"
            ),
            source_field=source_field,
        )
    return _contradicted(
        claim,
        evidence=(
            f"source {source_field} = {source}, claim asserts {asserted}"
        ),
        source_field=source_field,
        correction=str(source),
    )


_SUBSCRIPT_TR = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def _normalise_formula_text(s: str) -> str:
    """Translate unicode subscripts to ASCII digits in arbitrary text.

    Used to pre-normalise claim text before formula regex matching, since
    the regex uses ASCII ``\\d``. Does not strip whitespace or upper-case —
    that's :func:`_normalise_formula`'s job, applied only to the
    extracted formula string.
    """
    return s.translate(_SUBSCRIPT_TR)


def _normalise_formula(s: str) -> str:
    """Strip whitespace and unicode subscripts so 'C₆H₁₂O₆' == 'C6H12O6'."""
    return s.translate(_SUBSCRIPT_TR).replace(" ", "").upper()


def _supported(
    claim: ClassifiedClaim, *, evidence: str, source_field: str | None
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.SUPPORTED,
        evidence=evidence,
        source_field=source_field,
        correction=None,
        extracted_fields=claim.extracted_fields,
        evidence_refs=_evidence_refs(source_field, evidence),
        verifier_layer="grounded",
        trace_summary=evidence,
    )


def _contradicted(
    claim: ClassifiedClaim,
    *,
    evidence: str,
    source_field: str | None,
    correction: str | None,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.CONTRADICTED,
        evidence=evidence,
        source_field=source_field,
        correction=correction,
        extracted_fields=claim.extracted_fields,
        evidence_refs=_evidence_refs(source_field, evidence),
        verifier_layer="grounded",
        trace_summary=evidence,
    )


def _unsupported(
    claim: ClassifiedClaim, *, evidence: str,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNSUPPORTED,
        evidence=evidence,
        source_field=None,
        correction=None,
        extracted_fields=claim.extracted_fields,
        verifier_layer="grounded",
        trace_summary=evidence,
    )


def _unverifiable(
    claim: ClassifiedClaim, *, evidence: str, source_field: str | None,
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
        evidence_refs=_evidence_refs(source_field, evidence),
        verifier_layer="grounded",
        trace_summary=evidence,
    )


def _evidence_refs(source_field: str | None, summary: str) -> list[EvidenceRef]:
    if source_field is None:
        return []
    return [EvidenceRef(source="source_report", path=source_field, summary=summary)]
