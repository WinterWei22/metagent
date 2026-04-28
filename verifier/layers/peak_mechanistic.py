"""Layer F — verify peak-level mechanistic claims with SIRIUS.

This layer handles claims that assert a fragment ion or neutral loss at a
specific m/z. It first checks that the peak exists in the experimental
spectrum, then asks SIRIUS for a fragmentation-tree annotation.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any, Callable

from schemas.report import IdentificationReport
from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim, VerifiedClaim


SiriusAnnotator = Callable[[Any], Any]

COMMON_NEUTRAL_LOSSES = {
    # formula: (mass_da, common_names)
    "H2O": (18.0106, ["h2o", "water", "h₂o"]),
    "NH3": (17.0265, ["nh3", "ammonia"]),
    "CO": (27.9949, ["co", "carbon monoxide"]),
    "CO2": (43.9898, ["co2", "carbon dioxide", "co₂"]),
    "CH2O2": (46.0055, ["formic acid", "hcooh"]),
    "C2H4O": (44.0262, ["acetaldehyde"]),
    "C2H2O": (42.0106, ["ketene"]),
    "HPO3": (79.9663, ["metaphosphoric acid", "hpo3"]),
    "H3PO4": (97.9769, ["phosphoric acid"]),
    "CH3": (15.0235, ["methyl", "ch3"]),
    "C2H4": (28.0313, ["ethylene", "c2h4"]),
    "HF": (20.0062, ["hf", "hydrogen fluoride"]),
    "HCl": (35.9767, ["hcl", "hydrogen chloride"]),
    "SO3": (79.9568, ["so3", "sulfur trioxide"]),
    "C5H8O4": (132.0423, ["glutaric acid"]),
}

_SUBSCRIPT_TRANS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_MZ_RE = re.compile(r"\bm/z\s*=?\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_MASS_RE = re.compile(r"(?<![A-Za-z])(\d+(?:\.\d+)?)(?:\s*Da)?", re.IGNORECASE)


def verify_peak_mechanistic(
    claim: ClassifiedClaim,
    source_report: IdentificationReport,
    *,
    sirius_fn: SiriusAnnotator | None = None,
) -> VerifiedClaim:
    """Verify one peak-level mechanistic claim against SIRIUS."""
    mz = (
        claim.extracted_fields.mz
        if claim.extracted_fields.mz is not None
        else claim.peak_mz if claim.peak_mz is not None else _extract_mz(claim.claim_text)
    )
    if mz is None:
        return _unverifiable(
            claim,
            "Layer F found no extractable m/z value in the peak claim.",
        )

    spectrum = source_report.experimental_spectrum
    peak_exists = any(abs(obs_mz - mz) / mz * 1e6 <= 5.0 for obs_mz in spectrum.mz)
    if not peak_exists:
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=ClaimType.PEAK_MECHANISTIC,
            claim_subtype=claim.claim_subtype,
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.CONTRADICTED,
            evidence=(
                f"Peak at m/z {mz:.4f} not found in experimental spectrum "
                f"(5 ppm tolerance). Spectrum has {len(spectrum.mz)} peaks."
            ),
            extracted_fields=claim.extracted_fields,
            verifier_layer="peak_mechanistic",
            trace_summary=f"Peak at m/z {mz:.4f} absent from experimental spectrum",
        )

    if _get_top_candidate(claim, source_report) is None:
        return _unverifiable(claim, "No candidate with SMILES available")

    if sirius_fn is None:
        try:
            from tools.sirius import SiriusAnnotateRequest, sirius_annotate
        except ModuleNotFoundError as exc:
            if exc.name == "dotenv":
                return _unverifiable(
                    claim, "SIRIUS not available in this environment"
                )
            raise

        request = SiriusAnnotateRequest(spectrum=spectrum)
        sirius_fn = sirius_annotate
    else:
        request = SimpleNamespace(spectrum=spectrum)

    try:
        sirius_resp = sirius_fn(request)
    except Exception as exc:
        if _is_exception_named(exc, "SiriusNotInstalledError"):
            return _unverifiable(claim, "SIRIUS not available in this environment")
        if _is_exception_named(exc, "SiriusNoFormulaError"):
            return _unverifiable(
                claim,
                "SIRIUS could not assign a formula (spectrum too noisy or too few peaks)",
            )
        raise

    annotation = sirius_resp.lookup_fragment(mz=mz, tolerance_ppm=5.0)
    if annotation is None:
        return VerifiedClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            claim_type=ClaimType.PEAK_MECHANISTIC,
            claim_subtype=claim.claim_subtype,
            subject=claim.subject,
            subject_kind=claim.subject_kind,
            candidate_ref=claim.candidate_ref,
            verdict=ClaimVerdict.UNSUPPORTED,
            evidence=(
                f"SIRIUS fragmentation tree has no fragment at m/z {mz:.4f} "
                f"± 5 ppm. Tree has {sirius_resp.tree_node_count} nodes."
            ),
            extracted_fields=claim.extracted_fields,
            verifier_layer="peak_mechanistic",
            tool_called="sirius",
            trace_summary=f"SIRIUS tree has no fragment at m/z {mz:.4f}",
        )

    claimed_nl = (
        claim.extracted_fields.neutral_loss
        or claim.neutral_loss
        or _extract_neutral_loss(claim.claim_text)
    )
    if claimed_nl is not None:
        sirius_nl = annotation.neutral_loss_formula or annotation.neutral_loss
        if not _neutral_loss_matches(claimed=claimed_nl, sirius_nl=sirius_nl):
            return VerifiedClaim(
                claim_id=claim.claim_id,
                claim_text=claim.claim_text,
                claim_type=ClaimType.PEAK_MECHANISTIC,
                claim_subtype=claim.claim_subtype,
                subject=claim.subject,
                subject_kind=claim.subject_kind,
                candidate_ref=claim.candidate_ref,
                verdict=ClaimVerdict.CONTRADICTED,
                evidence=(
                    f"SIRIUS assigns neutral loss {sirius_nl!r} at this m/z, "
                    f"but LLM claimed {claimed_nl!r}."
                ),
                correction=sirius_nl,
                extracted_fields=claim.extracted_fields,
                verifier_layer="peak_mechanistic",
                tool_called="sirius",
                trace_summary=f"SIRIUS neutral loss {sirius_nl!r} mismatched",
            )

    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.PEAK_MECHANISTIC,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.SUPPORTED,
        evidence=(
            f"SIRIUS confirms fragment at m/z {mz:.4f} "
            f"(formula {annotation.formula}, "
            f"neutral loss {annotation.neutral_loss_formula})."
        ),
        source_field="experimental_spectrum + sirius_fragmentation_tree",
        extracted_fields=claim.extracted_fields,
        verifier_layer="peak_mechanistic",
        tool_called="sirius",
        trace_summary=f"SIRIUS fragment at m/z {mz:.4f}",
    )


def _get_top_candidate(claim: ClassifiedClaim, source_report: IdentificationReport):
    if claim.candidate_ref is not None and claim.candidate_ref.smiles:
        return claim.candidate_ref
    if not source_report.candidates:
        return None
    top = source_report.candidates[0]
    if top.candidate.smiles:
        return top
    return None


def _is_exception_named(exc: Exception, class_name: str) -> bool:
    return type(exc).__name__ == class_name


def _extract_mz(text: str) -> float | None:
    m = _MZ_RE.search(text)
    if not m:
        return None
    return float(m.group(1))


def _extract_neutral_loss(text: str) -> str | None:
    low = _norm_loss(text)
    for formula, (_, aliases) in COMMON_NEUTRAL_LOSSES.items():
        if _norm_loss(formula) in low:
            return formula
        for alias in aliases:
            if _norm_loss(alias) in low:
                return alias
    m = re.search(r"(?:neutral\s+)?loss\s+of\s+([A-Za-z0-9₂₃₄.+-]+)", text, re.I)
    if m:
        return m.group(1).strip()
    return None


def _neutral_loss_matches(*, claimed: str, sirius_nl: str | None) -> bool:
    if not sirius_nl:
        return False
    claimed_info = _loss_info(claimed)
    sirius_info = _loss_info(sirius_nl)
    if claimed_info is None or sirius_info is None:
        return _norm_loss(claimed) == _norm_loss(sirius_nl)

    claimed_formula, claimed_mass = claimed_info
    sirius_formula, sirius_mass = sirius_info
    if claimed_formula and sirius_formula:
        return claimed_formula == sirius_formula
    return abs(claimed_mass - sirius_mass) <= 0.02


def _loss_info(value: str) -> tuple[str | None, float] | None:
    norm = _norm_loss(value)
    for formula, (mass, aliases) in COMMON_NEUTRAL_LOSSES.items():
        if norm == _norm_loss(formula):
            return formula, mass
        if any(norm == _norm_loss(alias) for alias in aliases):
            return formula, mass
    m = _MASS_RE.search(norm)
    if m:
        return None, float(m.group(1))
    return None


def _norm_loss(value: str) -> str:
    return value.translate(_SUBSCRIPT_TRANS).strip().lower()


def _unverifiable(claim: ClassifiedClaim, evidence: str) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.PEAK_MECHANISTIC,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=ClaimVerdict.UNVERIFIABLE_V0,
        evidence=evidence,
        extracted_fields=claim.extracted_fields,
        verifier_layer="peak_mechanistic",
        tool_called="sirius" if "SIRIUS" in evidence else None,
        trace_summary=evidence,
    )
