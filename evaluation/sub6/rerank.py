"""Reranker for Sub-6A real-id v2: SIRIUS sanity gate + CFM-ID predicted-spectrum cosine.

Phase 6.2 reranks the top-K library_search candidates by recomputing the
schema-defined ``compute_evidence_score`` (0.4 modcos + 0.3 cfmid_cosine +
0.2 mass_match + 0.1 pathway_presence) and applying a SIRIUS-formula sanity
gate (×0.5 if the candidate's molecular formula disagrees with SIRIUS's
top-1 predicted formula).

The reranker is **purely additive**: when ``use_sirius`` and ``use_cfmid``
are both False, ``rerank_with_sirius_cfmid`` returns the candidate list
unchanged in order, with a peak_evidence dict that only mirrors the
modified-cosine scores. Identification.py's existing default path is
unaffected.

CFM-ID predictions are file-cached by ``hash(canonical_smiles, adduct,
ionization_mode, energies_tuple)`` under ``data/cache/cfmid/`` so that
(a) the SIRIUS-only and full configs share work, (b) verifier Layer F can
re-use the cache later, and (c) the run survives interrupts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from common.rdkit_utils import canonicalize_smiles, molecular_formula
from schemas.common import Candidate, Spectrum
from schemas.report import CandidateReport
from schemas.spectrum import (
    PredictSpectrumRequest,
    PredictSpectrumResponse,
)

compute_evidence_score = CandidateReport.compute_evidence_score

logger = logging.getLogger(__name__)

# Default disk cache for CFM-ID predictions.
DEFAULT_CFMID_CACHE_DIR = Path("data/cache/cfmid")

# matchms ModifiedCosine uses absolute Da tolerance. 10 ppm at fragment
# masses 50-500 Da is 0.5-5 mDa; we set 0.01 Da (a conservative envelope)
# so peaks are matched generously when comparing experimental against the
# CFM-ID predicted union spectrum.
_PREDICTED_COSINE_DA_TOL = 0.01

# Mass-match indicator (Phase A used 10 ppm for library_search precursor
# narrowing; the schema's mass_match is a binary 0/1 indicator). The
# evidence_score formula treats this as already-binary, so we require the
# candidate's formula-derived exact mass to be within 5 ppm of the query
# precursor before crediting it.
_MASS_MATCH_PPM = 5.0

# SIRIUS sanity gate: when SIRIUS's top-1 formula disagrees with the
# candidate's RDKit-derived formula, multiply evidence_score by this.
# 0.5 = "downweight, don't reject" — Phase 6.2 wants soft demotion so
# false-negative SIRIUS calls don't kill correct candidates.
_SIRIUS_GATE_FACTOR = 0.5

# Auto-relogin throttle: SIRIUS academic license rejects too-frequent
# logins, so we cap relogin attempts to once per N seconds (process-wide).
_SIRIUS_RELOGIN_MIN_INTERVAL = 30.0
_LAST_RELOGIN_TS = 0.0
_RELOGIN_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RerankResult:
    """Per-candidate scoring artefacts used by the reranker."""

    smiles: str
    name: str | None
    source_id: str | None
    formula: str | None
    modcos: float
    predicted_cosine: float
    mass_match: float
    pathway_presence: float
    sirius_match: float  # 1.0 if formula matches SIRIUS top-1 else 0.0
    sirius_gate_applied: bool
    evidence_score: float


@dataclass
class PeakEvidence:
    """Per-spectrum bundle written to disk per the Phase 6.2 schema (D5)."""

    spectrum_id: str
    experimental_peaks: list[list[float]]
    sirius: dict[str, Any] = field(default_factory=dict)
    cfmid_top1: dict[str, Any] = field(default_factory=dict)
    candidates_evaluated: list[dict[str, Any]] = field(default_factory=list)
    rerank_config: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spectrum_id": self.spectrum_id,
            "experimental_peaks": self.experimental_peaks,
            "sirius": self.sirius,
            "cfmid_top1": self.cfmid_top1,
            "candidates_evaluated": self.candidates_evaluated,
            "rerank_config": self.rerank_config,
            "timing": self.timing,
        }


# ---------------------------------------------------------------------------
# CFM-ID disk cache
# ---------------------------------------------------------------------------


def _cfmid_cache_key(smiles: str, adduct: str, ion_mode: str, energies: tuple[float, ...]) -> str:
    canon = canonicalize_smiles(smiles) or smiles
    payload = f"{canon}|{adduct}|{ion_mode}|{','.join(f'{e:.1f}' for e in energies)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _cfmid_cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def _cfmid_cache_load(cache_dir: Path, key: str) -> PredictSpectrumResponse | None:
    path = _cfmid_cache_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        return PredictSpectrumResponse.model_validate(raw)
    except Exception as exc:
        logger.warning("cfmid cache read failed for %s: %s", path, exc)
        return None


def _cfmid_cache_store(cache_dir: Path, key: str, resp: PredictSpectrumResponse) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cfmid_cache_path(cache_dir, key)
    try:
        path.write_text(json.dumps(resp.model_dump(mode="json"), indent=2))
    except Exception as exc:
        logger.warning("cfmid cache write failed for %s: %s", path, exc)


def predict_with_cache(
    request: PredictSpectrumRequest,
    *,
    predict_fn: Callable[[PredictSpectrumRequest], PredictSpectrumResponse],
    cache_dir: Path,
) -> tuple[PredictSpectrumResponse, bool]:
    """Run CFM-ID with disk-cache. Returns (response, cache_hit)."""
    key = _cfmid_cache_key(
        request.smiles,
        request.adduct,
        request.ionization_mode,
        tuple(request.collision_energies),
    )
    cached = _cfmid_cache_load(cache_dir, key)
    if cached is not None:
        return cached, True
    resp = predict_fn(request)
    _cfmid_cache_store(cache_dir, key, resp)
    return resp, False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spectrum_peaks(spec: Spectrum) -> list[list[float]]:
    return [[float(mz), float(intensity)] for mz, intensity in zip(spec.mz, spec.intensity)]


def _formula_exact_mass(formula: str) -> float | None:
    """Compute monoisotopic exact mass from a Hill-style formula via RDKit."""
    if not formula:
        return None
    try:
        from rdkit.Chem import rdMolDescriptors
        from rdkit.Chem.rdMolDescriptors import CalcExactMolWt  # type: ignore
        from rdkit.Chem.AllChem import MolFromSmiles  # noqa: F401
    except Exception:
        return None
    # Build a minimal molecule from formula: easiest path is rdkit's
    # Chem.rdMolDescriptors._CalcMolFormula reverse — but rdkit doesn't
    # ship a public formula→mass parser. We compute element-wise from a
    # tiny dictionary; sufficient for CHNOPS + halogens that cover ~99%
    # of HMDB.
    return _formula_to_mass(formula)


# Monoisotopic masses (Da) — IUPAC 2021 values, sufficient for ppm-level checks.
_MONOISOTOPIC = {
    "H": 1.00782503207, "C": 12.0, "N": 14.0030740048, "O": 15.99491461956,
    "P": 30.97376163, "S": 31.97207100, "F": 18.99840322, "Cl": 34.96885268,
    "Br": 78.9183371, "I": 126.904473, "Si": 27.9769265, "Na": 22.98976928,
    "K": 38.96370668,
}


def _formula_to_mass(formula: str) -> float | None:
    import re
    if not formula:
        return None
    parts = re.findall(r"([A-Z][a-z]?)(\d*)", formula)
    total = 0.0
    seen = False
    for elem, count in parts:
        if not elem:
            continue
        if elem not in _MONOISOTOPIC:
            return None
        n = int(count) if count else 1
        total += _MONOISOTOPIC[elem] * n
        seen = True
    return total if seen else None


def _mass_match_indicator(precursor_mz: float, formula: str | None, *, ppm: float = _MASS_MATCH_PPM) -> float:
    """Binary 0/1: 1 if formula's neutral exact mass + a proton is within ppm of precursor.

    For [M+H]+ the precursor is M+1.00728. We don't know the adduct here,
    so we accept either ±H within tolerance (covers [M+H]+ and [M-H]- and
    plain [M]). This is intentionally generous: the indicator is only a
    0.2-weight contribution, not a primary filter.
    """
    if not formula or precursor_mz <= 0:
        return 0.0
    mass = _formula_to_mass(formula)
    if mass is None or mass <= 0:
        return 0.0
    proton = 1.00728
    deltas = [abs(precursor_mz - mass), abs(precursor_mz - (mass + proton)), abs(precursor_mz - (mass - proton))]
    best = min(deltas)
    if (best / precursor_mz) * 1e6 <= ppm:
        return 1.0
    return 0.0


def _predicted_cosine(experimental: Spectrum, cfm_response: PredictSpectrumResponse) -> float:
    """Modified-cosine between experimental spectrum and CFM-ID union spectrum."""
    from tools.library_search.scoring import modified_cosine_score
    pred = cfm_response.predicted
    if not pred.mz or not pred.intensity:
        return 0.0
    return modified_cosine_score(
        query_mz=list(experimental.mz),
        query_intensity=list(experimental.intensity),
        query_precursor_mz=float(experimental.precursor_mz),
        ref_mz=list(pred.mz),
        ref_intensity=list(pred.intensity),
        ref_precursor_mz=float(pred.precursor_mz or experimental.precursor_mz),
        tolerance=_PREDICTED_COSINE_DA_TOL,
    )


# ---------------------------------------------------------------------------
# Public reranker
# ---------------------------------------------------------------------------


def rerank_with_sirius_cfmid(
    spectrum_id: str,
    experimental: Spectrum,
    candidates: list[Candidate],
    *,
    top_k_for_rerank: int = 5,
    use_sirius: bool = True,
    use_cfmid: bool = True,
    cfmid_cache_dir: Path = DEFAULT_CFMID_CACHE_DIR,
    sirius_fn: Callable[..., Any] | None = None,
    cfmid_fn: Callable[[PredictSpectrumRequest], PredictSpectrumResponse] | None = None,
) -> tuple[list[Candidate], PeakEvidence]:
    """Rerank top-K candidates and emit per-spectrum peak evidence.

    Args:
      spectrum_id: stable id used for the per-spectrum JSON filename.
      experimental: Spectrum from the source task (post-conversion).
      candidates: ``surviving`` list from library_search (already
        sorted by modified-cosine descending). Tail (>top_k_for_rerank)
        is preserved verbatim after the reranked head.
      top_k_for_rerank: Apply SIRIUS+CFM-ID to the first K candidates.
      use_sirius: Run SIRIUS once and apply formula sanity gate.
      use_cfmid: Run CFM-ID per candidate SMILES (with disk cache).
      cfmid_cache_dir: Disk cache for CFM-ID predictions.
      sirius_fn / cfmid_fn: Dependency injection for tests.

    Returns:
      reranked candidates (same length, reordered head) + PeakEvidence.
    """
    timing: dict[str, float] = {}
    sirius_top1_formula: str | None = None
    sirius_evidence: dict[str, Any] = {}
    if use_sirius:
        sirius_top1_formula, sirius_evidence, sirius_t = _run_sirius(experimental, sirius_fn)
        timing["sirius"] = sirius_t

    head = candidates[: top_k_for_rerank]
    tail = candidates[top_k_for_rerank:]

    cfmid_predict = cfmid_fn or _default_cfmid_predict
    rerank_results: list[RerankResult] = []
    cfmid_top1_view: dict[str, Any] = {}
    t_cfm_total = 0.0
    cfmid_cache_hits = 0

    ion_mode = (experimental.ionization_mode or "positive").lower()
    if ion_mode not in ("positive", "negative"):
        ion_mode = "positive"
    adduct = experimental.adduct or ("[M+H]+" if ion_mode == "positive" else "[M-H]-")

    for i, cand in enumerate(head):
        formula = molecular_formula(cand.smiles) if cand.smiles else None
        modcos = float(getattr(cand, "score", 0.0) or 0.0)
        mass_match = _mass_match_indicator(experimental.precursor_mz, formula)

        predicted_cosine = 0.0
        cfm_resp: PredictSpectrumResponse | None = None
        if use_cfmid and cand.smiles:
            t0 = time.time()
            try:
                req = PredictSpectrumRequest(
                    smiles=cand.smiles,
                    adduct=adduct,
                    ionization_mode=ion_mode,
                    collision_energies=[10.0, 20.0, 40.0],
                )
                cfm_resp, hit = predict_with_cache(req, predict_fn=cfmid_predict, cache_dir=cfmid_cache_dir)
                cfmid_cache_hits += int(hit)
                predicted_cosine = _predicted_cosine(experimental, cfm_resp)
            except Exception as exc:  # noqa: BLE001
                logger.warning("CFM-ID failed for spectrum=%s cand=%s: %s", spectrum_id, cand.smiles, exc)
            t_cfm_total += time.time() - t0

        # Sub-6 sub6a does not pass pathway_context to the reranker; leave 0.
        pathway_presence = 0.0

        evidence = compute_evidence_score(
            candidate_score=modcos,
            predicted_spectrum_cosine=predicted_cosine,
            mass_match_indicator=mass_match,
            pathway_presence_indicator=pathway_presence,
        )

        # SIRIUS sanity gate
        sirius_match = 0.0
        sirius_gate_applied = False
        if use_sirius and sirius_top1_formula and formula:
            if formula == sirius_top1_formula:
                sirius_match = 1.0
            else:
                evidence *= _SIRIUS_GATE_FACTOR
                sirius_gate_applied = True

        rerank_results.append(RerankResult(
            smiles=cand.smiles,
            name=getattr(cand, "name", None),
            source_id=getattr(cand, "source_id", None),
            formula=formula,
            modcos=modcos,
            predicted_cosine=predicted_cosine,
            mass_match=mass_match,
            pathway_presence=pathway_presence,
            sirius_match=sirius_match,
            sirius_gate_applied=sirius_gate_applied,
            evidence_score=evidence,
        ))

        if i == 0 and cfm_resp is not None:
            cfmid_top1_view = {
                "smiles": cand.smiles,
                "predicted_peaks": _spectrum_peaks(cfm_resp.predicted),
                "cosine_vs_experimental": predicted_cosine,
                "model_version": cfm_resp.model_version,
            }

    if use_cfmid:
        timing["cfmid_total"] = t_cfm_total
        timing["cfmid_cache_hits"] = float(cfmid_cache_hits)

    # Reorder head by evidence_score descending, then concat with tail.
    rerank_results_sorted = sorted(rerank_results, key=lambda r: -r.evidence_score)
    smiles_to_cand = {c.smiles: c for c in head}
    reranked_head = [smiles_to_cand[r.smiles] for r in rerank_results_sorted]
    reranked = reranked_head + tail

    # Build PeakEvidence
    candidates_evaluated = []
    for rank_after, r in enumerate(rerank_results_sorted, start=1):
        candidates_evaluated.append({
            "smiles": r.smiles,
            "name": r.name,
            "source_id": r.source_id,
            "formula": r.formula,
            "modcos": r.modcos,
            "predicted_cosine": r.predicted_cosine,
            "mass_match": r.mass_match,
            "pathway_presence": r.pathway_presence,
            "sirius_match": r.sirius_match,
            "sirius_gate_applied": r.sirius_gate_applied,
            "evidence_score": r.evidence_score,
            "rank_after_rerank": rank_after,
        })

    pe = PeakEvidence(
        spectrum_id=spectrum_id,
        experimental_peaks=_spectrum_peaks(experimental),
        sirius=sirius_evidence,
        cfmid_top1=cfmid_top1_view,
        candidates_evaluated=candidates_evaluated,
        rerank_config={
            "top_k_for_rerank": top_k_for_rerank,
            "use_sirius": use_sirius,
            "use_cfmid": use_cfmid,
            "predicted_cosine_da_tol": _PREDICTED_COSINE_DA_TOL,
            "mass_match_ppm": _MASS_MATCH_PPM,
            "sirius_gate_factor": _SIRIUS_GATE_FACTOR,
        },
        timing=timing,
    )
    return reranked, pe


# ---------------------------------------------------------------------------
# SIRIUS arm (lazy import to keep tools/sirius optional)
# ---------------------------------------------------------------------------


def _default_sirius_annotate(spec: Spectrum) -> Any:
    from tools.sirius import SiriusAnnotateRequest, sirius_annotate
    req = SiriusAnnotateRequest(spectrum=spec, instrument_preset="orbitrap", timeout_seconds=180)
    return sirius_annotate(req)


def _is_sirius_login_error(exc: Exception) -> bool:
    """Detect SIRIUS errors caused by an expired/invalid login session."""
    msg = str(exc).lower()
    return any(token in msg for token in (
        "requires login",
        "not logged in",
        "no valid refresh token",
        "401",
    ))


def _maybe_relogin_sirius() -> bool:
    """Try to refresh the SIRIUS login when env credentials are present.

    Reads ``METAGENT_SIRIUS_USER`` and ``METAGENT_SIRIUS_PASS`` and shells
    out to ``sirius login --user-env=... --password-env=...``. Throttled
    to once per :data:`_SIRIUS_RELOGIN_MIN_INTERVAL` seconds so a 459-task
    batch can't hammer the license server.

    Returns True iff the login subprocess reports success.
    """
    user_var = "METAGENT_SIRIUS_USER"
    pass_var = "METAGENT_SIRIUS_PASS"
    if not os.environ.get(user_var) or not os.environ.get(pass_var):
        return False
    global _LAST_RELOGIN_TS
    now = time.time()
    with _RELOGIN_LOCK:
        if now - _LAST_RELOGIN_TS < _SIRIUS_RELOGIN_MIN_INTERVAL:
            return False
        _LAST_RELOGIN_TS = now
    sirius_bin = os.environ.get("METAGENT_SIRIUS_PATH") or "sirius"
    try:
        result = subprocess.run(
            [sirius_bin, "login",
             f"--user-env={user_var}", f"--password-env={pass_var}"],
            capture_output=True, text=True, timeout=90,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("SIRIUS relogin subprocess error: %s", exc)
        return False
    combined = (result.stdout or "") + (result.stderr or "")
    if "Login successful!" in combined:
        logger.warning("SIRIUS relogin succeeded (auto)")
        return True
    logger.warning("SIRIUS relogin FAILED: %s", combined.splitlines()[-1] if combined else "(no output)")
    return False


def _run_sirius(spec: Spectrum, sirius_fn: Callable[..., Any] | None) -> tuple[str | None, dict[str, Any], float]:
    """Run SIRIUS once and return (top1_formula, evidence_dict, wall_seconds).

    On a login-related failure, attempts a single auto-relogin (subject to
    :data:`_SIRIUS_RELOGIN_MIN_INTERVAL` throttle) and retries once.
    """
    fn = sirius_fn or _default_sirius_annotate
    t0 = time.time()
    try:
        resp = fn(spec)
    except Exception as exc:  # noqa: BLE001
        if _is_sirius_login_error(exc) and _maybe_relogin_sirius():
            try:
                resp = fn(spec)
            except Exception as exc2:  # noqa: BLE001
                logger.warning("SIRIUS failed after relogin retry: %s", exc2)
                return None, {"error": f"{type(exc2).__name__}: {exc2}", "relogin_retried": True}, time.time() - t0
        else:
            logger.warning("SIRIUS failed: %s", exc)
            return None, {"error": f"{type(exc).__name__}: {exc}"}, time.time() - t0
    top1 = getattr(resp, "predicted_formula", None)
    fragments = getattr(resp, "fragments", []) or []
    tree: dict[str, dict[str, Any]] = {}
    for frag in fragments:
        key = f"{getattr(frag, 'mz_observed', 0):.4f}"
        tree[key] = {
            "formula": getattr(frag, "formula", ""),
            "neutral_loss": getattr(frag, "neutral_loss", ""),
            "neutral_loss_formula": getattr(frag, "neutral_loss_formula", ""),
            "intensity": getattr(frag, "intensity", 0.0),
            "depth": getattr(frag, "depth", 0),
        }
    evidence = {
        "top_formulas": [
            {"formula": top1 or "", "score": float(getattr(resp, "formula_score", 0.0) or 0.0)},
        ] if top1 else [],
        "fragmentation_tree": tree,
        "tree_node_count": int(getattr(resp, "tree_node_count", len(fragments))),
        "sirius_version": getattr(resp, "sirius_version", "unknown"),
    }
    return top1, evidence, time.time() - t0


def _default_cfmid_predict(req: PredictSpectrumRequest) -> PredictSpectrumResponse:
    from tools.spectrum_predict import predict_spectrum
    return predict_spectrum(req)
