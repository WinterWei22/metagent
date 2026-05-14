"""Layer F — verify peak-level mechanistic claims with cross-validation.

Two independent fragmentation tools vote on each claim:

* **SIRIUS** — fragmentation-tree solver that infers the precursor formula
  from the spectrum and assigns sub-formulas to peaks. Strong on dense,
  high-CE spectra; can lock onto a wrong nitrogen-rich precursor formula
  on sparse low-CE inputs (the NM-001 failure mode documented in
  ``reports/spike/negative_mode_spike_2026-04-28.md`` §2.8).

* **CFM-ID** — supervised in-silico spectrum predictor that, given the
  candidate's SMILES + adduct, emits a predicted MS/MS spectrum. Noisier
  than SIRIUS but does not depend on the experimental spectrum's quality,
  so it provides an independent vote on whether a claimed fragment can
  arise from the candidate structure.

The consensus rules NEVER silently arbitrate when the two tools disagree.
When SIRIUS and CFM-ID give incompatible verdicts, the layer returns
``NEEDS_HUMAN_REVIEW`` rather than picking a winner. This is the core
technical claim of the project's deterministic-cross-validation design.

A SIRIUS sanity check mitigates NM-001: if SIRIUS' precursor formula
differs from the candidate's formula by more than 2 atoms in any
element, SIRIUS' result is downgraded to ``LOW_CONFIDENCE`` and the
consensus defers to CFM-ID.

CFM-ID predictions are cached per ``(canonical_smiles, adduct)`` for the
lifetime of the process — many peak claims on the same spectrum share
the same candidate / adduct, so a single CFM-ID call serves dozens of
claims.
"""
from __future__ import annotations

import re
from enum import Enum
from types import SimpleNamespace
from typing import Any, Callable

from schemas.report import IdentificationReport
from verifier.schemas import ClaimType, ClaimVerdict, ClassifiedClaim, VerifiedClaim


SiriusAnnotator = Callable[[Any], Any]
CfmidPredictor = Callable[[Any], Any]


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
_FORMULA_TOKEN_RE = re.compile(r"([A-Z][a-z]?)(\d*)")

# NM-001 mitigation threshold. SIRIUS predictions whose top formula
# differs from the candidate by more than this many atoms in any single
# element are tagged LOW_CONFIDENCE — in the citric-acid spike case
# SIRIUS picked C4H6N3O6 vs the truth C6H8O7 (C diff 2, N diff 3, O
# diff 1), which exceeds the threshold. The threshold is permissive
# enough that small isobaric drift does not trigger it but tight enough
# to catch the nitrogen-laden hallucinations seen in the spike.
_SIRIUS_SANITY_MAX_ATOM_DIFF = 2

# CFM-ID's m/z tolerance is wider than SIRIUS' (~5 ppm) because the model
# emits exact theoretical masses for predicted fragments but is only
# approximately right about *which* fragments form; matching at 10 ppm
# avoids penalising correct assignments that drift slightly across the
# energy ramp union.
_CFMID_PPM = 10.0

# Tolerance for matching neutral-loss mass via (precursor − fragment).
# CFM-ID does not label its predicted peaks with neutral losses; we
# infer them from the precursor delta and accept the same ±0.02 Da slop
# the SIRIUS comparator uses.
_CFMID_NL_MASS_TOL_DA = 0.02


# Process-wide CFM-ID cache. Keyed by (canonical_smiles, adduct). CFM-ID
# 4.0 only exposes [10, 20, 40] eV pre-trained models, so the experimental
# CE is not part of the key — the predicted union spectrum is the same
# across CE values for a given (smiles, adduct).
_CFMID_FAILED = object()
_CFMID_CACHE: dict[tuple[str, str], Any] = {}


class ToolResult(str, Enum):
    """Per-tool verdict on a peak-mechanistic claim.

    The five values are exhaustive — every code path through SIRIUS or
    CFM-ID maps to exactly one of them.

    * ``MATCHES`` — the tool's evidence supports the claim.
    * ``MISMATCHES`` — the tool found relevant evidence but it conflicts
      with the claim (e.g. SIRIUS assigned a different neutral loss; or
      the ``(precursor − fragment)`` delta in the CFM-ID prediction does
      not match the claimed neutral loss).
    * ``NOT_FOUND`` — the tool ran successfully but its evidence does
      not address the claim (e.g. SIRIUS' tree has no fragment at the
      claimed m/z; CFM-ID's predicted spectrum has no peak at the
      claimed m/z). Distinct from ``MISMATCHES`` because absence of
      evidence is weaker than direct contradiction.
    * ``NO_DATA`` — the tool was unavailable or raised before producing
      output (Docker down, SIRIUS not installed, etc.).
    * ``LOW_CONFIDENCE`` — the tool ran but produced internally
      inconsistent output. Currently only SIRIUS uses this (the NM-001
      sanity check); CFM-ID has no analogous self-test.
    """

    MATCHES = "matches"
    MISMATCHES = "mismatches"
    NOT_FOUND = "not_found"
    NO_DATA = "no_data"
    LOW_CONFIDENCE = "low_confidence"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def verify_peak_mechanistic(
    claim: ClassifiedClaim,
    source_report: IdentificationReport,
    *,
    sirius_fn: SiriusAnnotator | None = None,
    cfmid_fn: CfmidPredictor | None = None,
) -> VerifiedClaim:
    """Verify one peak-mechanistic claim with SIRIUS + CFM-ID consensus.

    ``sirius_fn`` / ``cfmid_fn`` are dependency-injected for tests; in
    production both default to ``None`` and the real backends are
    auto-loaded on first use.
    """
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
        return _build_verdict(
            claim,
            verdict=ClaimVerdict.CONTRADICTED,
            evidence=(
                f"Peak at m/z {mz:.4f} not found in experimental spectrum "
                f"(5 ppm tolerance). Spectrum has {len(spectrum.mz)} peaks."
            ),
            tool_called=None,
            trace_summary=f"Peak at m/z {mz:.4f} absent from experimental spectrum",
            tool_evidence=None,
        )

    candidate_info = _resolve_candidate_smiles_and_formula(claim, source_report)
    if candidate_info is None:
        return _unverifiable(claim, "No candidate with SMILES available")
    candidate_smiles, candidate_formula = candidate_info

    claimed_nl = (
        claim.extracted_fields.neutral_loss
        or claim.neutral_loss
        or _extract_neutral_loss(claim.claim_text)
    )

    sirius_result, sirius_evidence = _run_sirius(
        spectrum=spectrum,
        mz=mz,
        claimed_nl=claimed_nl,
        candidate_formula=candidate_formula,
        sirius_fn=sirius_fn,
    )

    cfmid_result, cfmid_evidence = _run_cfmid(
        spectrum=spectrum,
        mz=mz,
        claimed_nl=claimed_nl,
        candidate_smiles=candidate_smiles,
        cfmid_fn=cfmid_fn,
    )

    verdict, consensus_label, rationale = _consensus(sirius_result, cfmid_result)

    tool_evidence: dict[str, Any] = {
        "sirius": sirius_evidence,
        "cfmid": cfmid_evidence,
        "consensus": consensus_label,
        "rationale": rationale,
    }

    correction = _maybe_correction(
        verdict=verdict,
        sirius_result=sirius_result,
        sirius_evidence=sirius_evidence,
        claimed_nl=claimed_nl,
    )

    tool_called = _tool_called_label(sirius_result, cfmid_result)

    evidence_text = _evidence_summary(
        mz=mz,
        verdict=verdict,
        sirius_result=sirius_result,
        sirius_evidence=sirius_evidence,
        cfmid_result=cfmid_result,
        cfmid_evidence=cfmid_evidence,
    )

    source_field = (
        "experimental_spectrum + sirius_fragmentation_tree + cfmid_predicted_spectrum"
        if verdict == ClaimVerdict.SUPPORTED
        else None
    )

    return _build_verdict(
        claim,
        verdict=verdict,
        evidence=evidence_text,
        tool_called=tool_called,
        trace_summary=rationale,
        tool_evidence=tool_evidence,
        correction=correction,
        source_field=source_field,
    )


def reset_cfmid_cache() -> None:
    """Clear the per-process CFM-ID cache. Public so tests stay isolated."""
    _CFMID_CACHE.clear()


# ---------------------------------------------------------------------------
# SIRIUS arm
# ---------------------------------------------------------------------------


def _run_sirius(
    *,
    spectrum,
    mz: float,
    claimed_nl: str | None,
    candidate_formula: str,
    sirius_fn: SiriusAnnotator | None,
) -> tuple[ToolResult, dict[str, Any]]:
    """Run SIRIUS, apply the NM-001 sanity check, then map to a ToolResult."""
    evidence: dict[str, Any] = {"result": ToolResult.NO_DATA.value}

    if sirius_fn is None:
        try:
            from tools.sirius import SiriusAnnotateRequest, sirius_annotate
        except ModuleNotFoundError as exc:
            evidence["error"] = f"sirius import failed: {exc.name!r}"
            return ToolResult.NO_DATA, evidence
        request = SiriusAnnotateRequest(spectrum=spectrum)
        sirius_fn = sirius_annotate
    else:
        request = SimpleNamespace(spectrum=spectrum)

    try:
        sirius_resp = sirius_fn(request)
    except Exception as exc:
        if _is_exception_named(exc, "SiriusNotInstalledError"):
            evidence["error"] = "SIRIUS not available in this environment"
            return ToolResult.NO_DATA, evidence
        if _is_exception_named(exc, "SiriusNoFormulaError"):
            evidence["error"] = (
                "SIRIUS could not assign a formula (spectrum too noisy or too few peaks)"
            )
            return ToolResult.NO_DATA, evidence
        if _is_exception_named(exc, "SiriusTimeoutError"):
            evidence["error"] = "SIRIUS timed out"
            return ToolResult.NO_DATA, evidence
        if _is_exception_named(exc, "SiriusParseError"):
            evidence["error"] = f"SIRIUS produced unparseable output: {exc}"
            return ToolResult.NO_DATA, evidence
        raise

    sirius_formula = getattr(sirius_resp, "predicted_formula", None)
    evidence["predicted_formula"] = sirius_formula
    evidence["candidate_formula"] = candidate_formula
    evidence["tree_node_count"] = getattr(sirius_resp, "tree_node_count", None)

    sane = _sirius_sanity_check(sirius_formula, candidate_formula)
    evidence["sanity_check_passed"] = sane

    if not sane:
        evidence["result"] = ToolResult.LOW_CONFIDENCE.value
        evidence["sanity_diff"] = _formula_diff(sirius_formula, candidate_formula)
        return ToolResult.LOW_CONFIDENCE, evidence

    annotation = sirius_resp.lookup_fragment(mz=mz, tolerance_ppm=5.0)
    if annotation is None:
        evidence["result"] = ToolResult.NOT_FOUND.value
        evidence["fragment_found"] = False
        evidence["reason"] = (
            f"SIRIUS fragmentation tree has no fragment at m/z {mz:.4f} ± 5 ppm."
        )
        return ToolResult.NOT_FOUND, evidence

    evidence["fragment_found"] = True
    evidence["fragment_formula"] = getattr(annotation, "formula", None)
    sirius_nl = getattr(annotation, "neutral_loss_formula", None) or getattr(
        annotation, "neutral_loss", None
    )
    evidence["neutral_loss_formula"] = sirius_nl

    if claimed_nl is None:
        evidence["result"] = ToolResult.MATCHES.value
        return ToolResult.MATCHES, evidence

    if _neutral_loss_matches(claimed=claimed_nl, sirius_nl=sirius_nl):
        evidence["result"] = ToolResult.MATCHES.value
        return ToolResult.MATCHES, evidence

    evidence["result"] = ToolResult.MISMATCHES.value
    evidence["claimed_neutral_loss"] = claimed_nl
    evidence["reason"] = (
        f"SIRIUS assigns neutral loss {sirius_nl!r}, claim asserts {claimed_nl!r}."
    )
    return ToolResult.MISMATCHES, evidence


def _sirius_sanity_check(
    sirius_predicted_formula: str | None,
    candidate_formula: str,
) -> bool:
    """Return True if SIRIUS' top formula is plausibly close to the candidate.

    NM-001 mitigation: when SIRIUS' formula differs from the candidate's
    formula by more than ``_SIRIUS_SANITY_MAX_ATOM_DIFF`` in any single
    element, the fragmentation tree is built on a wrong precursor and
    its annotations should be treated as low-confidence.

    Returns False (sanity failed) when either formula cannot be parsed —
    we'd rather be conservative than trust unparseable input.
    """
    if not sirius_predicted_formula:
        return False
    sirius_counts = _parse_formula(sirius_predicted_formula)
    cand_counts = _parse_formula(candidate_formula)
    if sirius_counts is None or cand_counts is None:
        return False
    elements = set(sirius_counts) | set(cand_counts)
    for el in elements:
        diff = abs(sirius_counts.get(el, 0) - cand_counts.get(el, 0))
        if diff > _SIRIUS_SANITY_MAX_ATOM_DIFF:
            return False
    return True


def _formula_diff(
    formula_a: str | None, formula_b: str | None
) -> dict[str, int] | None:
    """Element-wise (a − b) atom-count diff, populated into evidence dumps."""
    if not formula_a or not formula_b:
        return None
    a = _parse_formula(formula_a)
    b = _parse_formula(formula_b)
    if a is None or b is None:
        return None
    elements = set(a) | set(b)
    return {el: a.get(el, 0) - b.get(el, 0) for el in sorted(elements)}


def _parse_formula(formula: str) -> dict[str, int] | None:
    """Parse a Hill-style formula string into element counts.

    Returns None for empty input, strings starting with a non-letter, or
    strings with unexpected characters (parens, charges, isotope tags).
    Implicit '1' counts are expanded ('CH4' → {C:1, H:4}).
    """
    if not formula:
        return None
    stripped = formula.strip()
    if not stripped or not stripped[0].isalpha():
        return None
    counts: dict[str, int] = {}
    pos = 0
    for match in _FORMULA_TOKEN_RE.finditer(stripped):
        if match.start() != pos:
            return None
        element, count = match.group(1), match.group(2)
        if not element:
            break
        counts[element] = counts.get(element, 0) + (int(count) if count else 1)
        pos = match.end()
    if pos != len(stripped):
        return None
    return counts or None


# ---------------------------------------------------------------------------
# CFM-ID arm
# ---------------------------------------------------------------------------


def _run_cfmid(
    *,
    spectrum,
    mz: float,
    claimed_nl: str | None,
    candidate_smiles: str,
    cfmid_fn: CfmidPredictor | None,
) -> tuple[ToolResult, dict[str, Any]]:
    """Predict spectrum via CFM-ID and check whether the claim matches.

    All exceptions from CFM-ID (missing tool, container down, invalid
    SMILES, timeout, etc.) are caught and produce ``NO_DATA`` so the
    consensus can still draw from SIRIUS alone.
    """
    evidence: dict[str, Any] = {"result": ToolResult.NO_DATA.value}

    adduct = spectrum.adduct
    ionization_mode = spectrum.ionization_mode

    cache_key = (candidate_smiles, adduct)
    cached = _CFMID_CACHE.get(cache_key)
    if cached is _CFMID_FAILED:
        evidence["error"] = "CFM-ID previously failed for this (smiles, adduct)"
        return ToolResult.NO_DATA, evidence

    if cached is None:
        try:
            cached = _invoke_cfmid(
                smiles=candidate_smiles,
                adduct=adduct,
                ionization_mode=ionization_mode,
                cfmid_fn=cfmid_fn,
            )
        except Exception as exc:
            _CFMID_CACHE[cache_key] = _CFMID_FAILED
            evidence["error"] = f"CFM-ID call failed: {type(exc).__name__}: {exc}"
            return ToolResult.NO_DATA, evidence
        _CFMID_CACHE[cache_key] = cached

    predicted = getattr(cached, "predicted", None)
    if predicted is None or not getattr(predicted, "mz", None):
        evidence["error"] = "CFM-ID returned no predicted peaks"
        return ToolResult.NO_DATA, evidence

    predicted_mzs = list(predicted.mz)
    evidence["predicted_peak_count"] = len(predicted_mzs)
    evidence["model_version"] = getattr(cached, "model_version", None)

    matched = _find_within_ppm(predicted_mzs, mz, _CFMID_PPM)
    evidence["matched_mz"] = matched
    evidence["claim_mz"] = mz

    if matched is None:
        evidence["result"] = ToolResult.NOT_FOUND.value
        evidence["reason"] = (
            f"No predicted peak within {_CFMID_PPM} ppm of m/z {mz:.4f} "
            f"({len(predicted_mzs)} peaks predicted)."
        )
        return ToolResult.NOT_FOUND, evidence

    if claimed_nl is None:
        evidence["result"] = ToolResult.MATCHES.value
        return ToolResult.MATCHES, evidence

    nl_info = _loss_info(claimed_nl)
    if nl_info is None:
        evidence["result"] = ToolResult.MATCHES.value
        evidence["nl_check"] = "skipped: claimed NL could not be parsed"
        return ToolResult.MATCHES, evidence

    _, nl_mass = nl_info
    precursor_mz = float(getattr(predicted, "precursor_mz", 0.0))
    delta = abs(precursor_mz - matched)
    evidence["precursor_to_fragment_delta"] = delta
    evidence["claimed_nl_mass"] = nl_mass

    if abs(delta - nl_mass) <= _CFMID_NL_MASS_TOL_DA:
        evidence["result"] = ToolResult.MATCHES.value
        return ToolResult.MATCHES, evidence

    evidence["result"] = ToolResult.MISMATCHES.value
    evidence["reason"] = (
        f"Precursor−fragment delta {delta:.4f} Da does not match claimed "
        f"NL mass {nl_mass:.4f} Da (±{_CFMID_NL_MASS_TOL_DA} Da)."
    )
    return ToolResult.MISMATCHES, evidence


def _invoke_cfmid(
    *,
    smiles: str,
    adduct: str,
    ionization_mode: str,
    cfmid_fn: CfmidPredictor | None,
) -> Any:
    """Build a CFM-ID request and call it. Tests inject ``cfmid_fn``."""
    if cfmid_fn is None:
        return _default_cfmid_fn(
            SimpleNamespace(
                smiles=smiles,
                adduct=adduct,
                ionization_mode=ionization_mode,
                collision_energies=[10.0, 20.0, 40.0],
                top_n_peaks=50,
            )
        )
    request = SimpleNamespace(
        smiles=smiles,
        adduct=adduct,
        ionization_mode=ionization_mode,
        collision_energies=[10.0, 20.0, 40.0],
        top_n_peaks=50,
    )
    return cfmid_fn(request)


def _default_cfmid_fn(req_namespace: SimpleNamespace) -> Any:
    """Real CFM-ID call. Wrapped in its own function so tests can
    monkey-patch it to bypass the live Docker shim."""
    from schemas.spectrum import PredictSpectrumRequest
    from tools.spectrum_predict import predict_spectrum

    request = PredictSpectrumRequest(
        smiles=req_namespace.smiles,
        adduct=req_namespace.adduct,
        ionization_mode=req_namespace.ionization_mode,
        collision_energies=list(req_namespace.collision_energies),
        top_n_peaks=req_namespace.top_n_peaks,
    )
    return predict_spectrum(request)


def _find_within_ppm(mzs: list[float], target: float, ppm: float) -> float | None:
    """Return the closest m/z within ``ppm`` of ``target``, or None."""
    if not mzs or target <= 0:
        return None
    tolerance_da = target * ppm / 1_000_000.0
    best: float | None = None
    best_delta = float("inf")
    for x in mzs:
        delta = abs(x - target)
        if delta <= tolerance_da and delta < best_delta:
            best = x
            best_delta = delta
    return best


# ---------------------------------------------------------------------------
# Consensus — 5 × 5 = 25 cells, exhaustive
# ---------------------------------------------------------------------------


def _consensus(
    sirius: ToolResult, cfmid: ToolResult
) -> tuple[ClaimVerdict, str, str]:
    """Apply cross-validation rules. Returns (verdict, label, rationale).

    Disagreements between two queryable tools always escalate to
    ``NEEDS_HUMAN_REVIEW`` — never silent arbitration.
    """
    return _CONSENSUS_TABLE[(sirius, cfmid)]


_M = ToolResult.MATCHES
_X = ToolResult.MISMATCHES
_F = ToolResult.NOT_FOUND
_N = ToolResult.NO_DATA
_L = ToolResult.LOW_CONFIDENCE


_CONSENSUS_TABLE: dict[
    tuple[ToolResult, ToolResult], tuple[ClaimVerdict, str, str]
] = {
    # ----- SIRIUS = MATCHES -----
    (_M, _M): (
        ClaimVerdict.SUPPORTED,
        "agree_supported",
        "Both SIRIUS and CFM-ID confirm the claim.",
    ),
    (_M, _X): (
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
        "tools_disagree",
        "SIRIUS supports but CFM-ID contradicts; escalating rather than arbitrating.",
    ),
    (_M, _F): (
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
        "tools_disagree",
        "SIRIUS supports but CFM-ID has no peak at the claimed m/z; escalating.",
    ),
    (_M, _N): (
        ClaimVerdict.SUPPORTED,
        "sirius_only_supported",
        "SIRIUS confirms; CFM-ID unavailable for cross-check.",
    ),
    (_M, _L): (
        ClaimVerdict.SUPPORTED,
        "sirius_drives_low_confidence_cfmid",
        "CFM-ID low-confidence; SIRIUS supports the claim.",
    ),
    # ----- SIRIUS = MISMATCHES -----
    (_X, _M): (
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
        "tools_disagree",
        "SIRIUS contradicts but CFM-ID supports; escalating rather than arbitrating.",
    ),
    (_X, _X): (
        ClaimVerdict.CONTRADICTED,
        "agree_contradicted",
        "Both SIRIUS and CFM-ID contradict the claim.",
    ),
    (_X, _F): (
        ClaimVerdict.CONTRADICTED,
        "sirius_contradicts_cfmid_not_found",
        "SIRIUS contradicts the claim; CFM-ID has no peak at the claimed m/z (consistent).",
    ),
    (_X, _N): (
        ClaimVerdict.CONTRADICTED,
        "sirius_only_contradicted",
        "SIRIUS contradicts; CFM-ID unavailable for cross-check.",
    ),
    (_X, _L): (
        ClaimVerdict.CONTRADICTED,
        "sirius_drives_low_confidence_cfmid",
        "CFM-ID low-confidence; SIRIUS contradicts the claim.",
    ),
    # ----- SIRIUS = NOT_FOUND -----
    (_F, _M): (
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
        "tools_disagree",
        "CFM-ID supports the claim but SIRIUS has no fragment at the claimed m/z.",
    ),
    (_F, _X): (
        ClaimVerdict.CONTRADICTED,
        "cfmid_contradicts_sirius_not_found",
        "CFM-ID contradicts the claim; SIRIUS has no fragment at the claimed m/z (consistent).",
    ),
    (_F, _F): (
        ClaimVerdict.UNSUPPORTED,
        "agree_not_found",
        "Both tools ran but neither found the claimed fragment.",
    ),
    (_F, _N): (
        ClaimVerdict.UNSUPPORTED,
        "sirius_only_not_found",
        "SIRIUS has no fragment at the claimed m/z; CFM-ID unavailable for cross-check.",
    ),
    (_F, _L): (
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
        "low_confidence_no_corroboration",
        "SIRIUS has no fragment and CFM-ID is low-confidence; no reliable basis.",
    ),
    # ----- SIRIUS = NO_DATA -----
    (_N, _M): (
        ClaimVerdict.SUPPORTED,
        "cfmid_only_supported",
        "CFM-ID confirms the claim; SIRIUS unavailable for cross-check.",
    ),
    (_N, _X): (
        ClaimVerdict.CONTRADICTED,
        "cfmid_only_contradicted",
        "CFM-ID contradicts the claim; SIRIUS unavailable for cross-check.",
    ),
    (_N, _F): (
        ClaimVerdict.UNSUPPORTED,
        "cfmid_only_not_found",
        "CFM-ID has no peak at the claimed m/z; SIRIUS unavailable for cross-check.",
    ),
    (_N, _N): (
        ClaimVerdict.UNVERIFIABLE_V0,
        "neither_available",
        "Neither SIRIUS nor CFM-ID could check this claim.",
    ),
    (_N, _L): (
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
        "cfmid_low_confidence_no_sirius",
        "CFM-ID low-confidence and SIRIUS unavailable; no reliable basis.",
    ),
    # ----- SIRIUS = LOW_CONFIDENCE -----
    (_L, _M): (
        ClaimVerdict.SUPPORTED,
        "cfmid_drives_low_confidence_sirius",
        "SIRIUS sanity check failed (likely wrong precursor formula); "
        "deferring to CFM-ID, which supports the claim.",
    ),
    (_L, _X): (
        ClaimVerdict.CONTRADICTED,
        "cfmid_drives_low_confidence_sirius",
        "SIRIUS sanity check failed; deferring to CFM-ID, which contradicts the claim.",
    ),
    (_L, _F): (
        ClaimVerdict.UNSUPPORTED,
        "cfmid_drives_low_confidence_sirius",
        "SIRIUS sanity check failed; deferring to CFM-ID, which has no peak at the claimed m/z.",
    ),
    (_L, _N): (
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
        "sirius_low_confidence_no_cfmid",
        "SIRIUS sanity check failed and CFM-ID unavailable; no reliable basis for a verdict.",
    ),
    (_L, _L): (
        ClaimVerdict.NEEDS_HUMAN_REVIEW,
        "both_low_confidence",
        "Both tools low-confidence; escalating to human review.",
    ),
}


# ---------------------------------------------------------------------------
# Result construction helpers
# ---------------------------------------------------------------------------


def _maybe_correction(
    *,
    verdict: ClaimVerdict,
    sirius_result: ToolResult,
    sirius_evidence: dict[str, Any],
    claimed_nl: str | None,
) -> str | None:
    """Populate ``correction`` only when SIRIUS named a single right answer.

    A correction is meaningful when both tools agree the claim is wrong
    AND SIRIUS observed a specific fragment / neutral-loss formula at
    the claimed m/z that disagreed with the LLM. Tools-disagree cases
    return ``None`` because there is no single right answer to write
    back into the rewritten output.
    """
    if verdict != ClaimVerdict.CONTRADICTED:
        return None
    if sirius_result != ToolResult.MISMATCHES:
        return None
    if not claimed_nl:
        return None
    return sirius_evidence.get("neutral_loss_formula")


def _evidence_summary(
    *,
    mz: float,
    verdict: ClaimVerdict,
    sirius_result: ToolResult,
    sirius_evidence: dict[str, Any],
    cfmid_result: ToolResult,
    cfmid_evidence: dict[str, Any],
) -> str:
    sirius_part = _tool_summary("SIRIUS", sirius_result, sirius_evidence)
    cfmid_part = _tool_summary("CFM-ID", cfmid_result, cfmid_evidence)
    return (
        f"Cross-validation at m/z {mz:.4f}: {sirius_part}; {cfmid_part}. "
        f"Consensus: {verdict.value}."
    )


def _tool_summary(name: str, result: ToolResult, evidence: dict[str, Any]) -> str:
    if result == ToolResult.MATCHES:
        nl = evidence.get("neutral_loss_formula")
        if nl:
            return f"{name} matches (neutral loss {nl})"
        return f"{name} matches"
    if result == ToolResult.MISMATCHES:
        reason = evidence.get("reason") or "tool's evidence does not support claim"
        return f"{name} mismatches ({reason})"
    if result == ToolResult.NOT_FOUND:
        reason = evidence.get("reason") or "tool found no peak at the claimed m/z"
        return f"{name} not_found ({reason})"
    if result == ToolResult.LOW_CONFIDENCE:
        return (
            f"{name} low_confidence (predicted formula "
            f"{evidence.get('predicted_formula')!r} differs from candidate "
            f"{evidence.get('candidate_formula')!r}; element diff "
            f"{evidence.get('sanity_diff')})"
        )
    err = evidence.get("error") or "no data"
    return f"{name} unavailable ({err})"


def _tool_called_label(sirius: ToolResult, cfmid: ToolResult) -> str | None:
    sirius_ran = sirius != ToolResult.NO_DATA
    cfmid_ran = cfmid != ToolResult.NO_DATA
    if sirius_ran and cfmid_ran:
        return "sirius+cfmid"
    if sirius_ran:
        return "sirius"
    if cfmid_ran:
        return "cfmid"
    return None


def _build_verdict(
    claim: ClassifiedClaim,
    *,
    verdict: ClaimVerdict,
    evidence: str,
    tool_called: str | None,
    trace_summary: str,
    tool_evidence: dict[str, Any] | None,
    correction: str | None = None,
    source_field: str | None = None,
) -> VerifiedClaim:
    return VerifiedClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        claim_type=ClaimType.PEAK_MECHANISTIC,
        claim_subtype=claim.claim_subtype,
        subject=claim.subject,
        subject_kind=claim.subject_kind,
        candidate_ref=claim.candidate_ref,
        verdict=verdict,
        evidence=evidence,
        source_field=source_field,
        correction=correction,
        extracted_fields=claim.extracted_fields,
        verifier_layer="peak_mechanistic",
        tool_called=tool_called,
        trace_summary=trace_summary,
        tool_evidence=tool_evidence,
    )


def _resolve_candidate_smiles_and_formula(
    claim: ClassifiedClaim, source_report: IdentificationReport
) -> tuple[str, str] | None:
    """Return (smiles, molecular_formula) for the top candidate, or None.

    Prefers a formula already attached to ``prefilter_match`` (cheap,
    canonical). Falls back to RDKit ``CalcMolFormula`` on the SMILES.
    """
    smiles: str | None = None
    formula: str | None = None

    if claim.candidate_ref is not None and claim.candidate_ref.smiles:
        smiles = claim.candidate_ref.smiles
    elif source_report.candidates:
        top = source_report.candidates[0]
        smiles = top.candidate.smiles or None
        if top.prefilter_match is not None and top.prefilter_match.molecular_formula:
            formula = top.prefilter_match.molecular_formula

    if not smiles:
        return None

    if formula is None:
        formula = _formula_from_smiles(smiles)
    if not formula:
        return None
    return smiles, formula


def _formula_from_smiles(smiles: str) -> str | None:
    try:
        from rdkit import Chem
        from rdkit.Chem import rdMolDescriptors
    except ImportError:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:
        return None
    if mol is None:
        return None
    try:
        return rdMolDescriptors.CalcMolFormula(mol)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers retained from the pre-cross-validation implementation
# ---------------------------------------------------------------------------


def _get_top_candidate(claim: ClassifiedClaim, source_report: IdentificationReport):
    """Legacy accessor — kept for callers that only need a yes/no on
    candidate availability. Not used by the new flow."""
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
    # Try interpreting the input as an arbitrary chemical formula and
    # computing its monoisotopic mass. This catches LLM-emitted losses
    # like 'C2H2O5' that are not in COMMON_NEUTRAL_LOSSES — important
    # for Layer F's CFM-ID precursor-delta check, which would otherwise
    # silently skip NL verification on unparseable strings.
    parsed = _parse_formula(value)
    if parsed is not None:
        mass = _formula_to_monoisotopic_mass(parsed)
        if mass is not None:
            return value.strip(), mass
    m = _MASS_RE.search(norm)
    if m:
        return None, float(m.group(1))
    return None


# Monoisotopic atomic masses (CODATA / NIST). Restricted to elements
# that plausibly appear in MS/MS neutral losses; an unsupported element
# returns None so we conservatively fall back to skip-NL behaviour.
_MONOISOTOPIC_MASS_DA: dict[str, float] = {
    "H": 1.007825,
    "C": 12.000000,
    "N": 14.003074,
    "O": 15.994915,
    "F": 18.998403,
    "Na": 22.989770,
    "P": 30.973762,
    "S": 31.972071,
    "Cl": 34.968853,
    "K": 38.963707,
    "Br": 78.918337,
    "I": 126.904473,
}


def _formula_to_monoisotopic_mass(counts: dict[str, int]) -> float | None:
    total = 0.0
    for element, count in counts.items():
        mass = _MONOISOTOPIC_MASS_DA.get(element)
        if mass is None:
            return None
        total += mass * count
    return total


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
