"""Scoring primitives for library_search.

Three concerns live here:

1. Modified-cosine similarity between a query spectrum and a single reference
   spectrum via ``matchms.similarity.ModifiedCosine``. Native range already
   ``[0, 1]`` so no rescaling is required.

2. In-house (ms-clip) score calibration. The raw model emits global cosine
   similarity in ``[-1, 1]``; we rescale to ``[0, 1]`` using a calibration curve
   persisted at ``tools/library_search/calibration.json``. If the file is
   missing we fall back to a linear ``(x + 1) / 2`` mapping and log a warning —
   the contract says a proper min-max should be computed over 100 library
   entries, but in v0 the linear fallback is documented-and-safe.

3. Score fusion across the two sub-scorers per candidate.

   -----------------------------------------------------------------
   Fusion choice: ``max(normalized_modcos, normalized_inhouse)``
   -----------------------------------------------------------------
   We default to element-wise max instead of a weighted sum because the two
   signals differ semantically:
     * modified cosine requires the candidate to have an actual GNPS reference
       spectrum, and measures peak overlap with that specific reference.
     * ms-clip's global similarity compares the query spectrum against a
       SMILES-derived mol embedding, independent of any reference spectrum.
   A candidate with only one available signal (e.g. not in GNPS → no modcos,
   or outside ms-clip's training domain → unreliable inhouse) should not be
   penalised for the absence of the other. Taking the max gives each scorer
   veto-free promotion power while keeping the range in ``[0, 1]``.
   This choice is intentionally simple for v0; tune with calibration once real
   evaluation numbers land.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CALIBRATION_PATH = Path(__file__).with_name("calibration.json")


# ---------------------------------------------------------------------------
# Modified-cosine wrapper
# ---------------------------------------------------------------------------


def modified_cosine_score(
    query_mz: list[float],
    query_intensity: list[float],
    query_precursor_mz: float,
    ref_mz: list[float],
    ref_intensity: list[float],
    ref_precursor_mz: float,
    *,
    tolerance: float = 0.1,
    mz_power: float = 0.0,
    intensity_power: float = 1.0,
) -> float:
    """Return the modified-cosine score in ``[0, 1]`` between two spectra.

    Thin wrapper so the tool does not import matchms everywhere. Handles the
    matchms Spectrum construction and score unpacking. On any matchms error we
    return 0.0 rather than propagate — a single pair failing should not kill a
    batch of hundreds.
    """
    import numpy as np
    from matchms import Spectrum

    # matchms 0.32 renamed ModifiedCosine -> ModifiedCosineGreedy AND changed
    # `pair()` return type from a numpy structured object (indexable by
    # 'score' / 'matches') to a plain ``Tuple[float, int]``. Compat shim
    # below covers both vintages so this file imports + scores correctly
    # against matchms ∈ {<0.32 (ModifiedCosine), ≥0.32 (ModifiedCosineGreedy)}.
    try:
        from matchms.similarity import ModifiedCosine  # type: ignore[attr-defined]
    except ImportError:  # matchms ≥ 0.32
        from matchms.similarity import ModifiedCosineGreedy as ModifiedCosine

    try:
        # matchms Spectrum requires mz ascending. Sort the (mz, intensity)
        # pairs together before construction.
        q_pairs = sorted(zip(query_mz, query_intensity), key=lambda p: p[0])
        r_pairs = sorted(zip(ref_mz, ref_intensity), key=lambda p: p[0])
        q = Spectrum(
            mz=np.asarray([p[0] for p in q_pairs], dtype=float),
            intensities=np.asarray([p[1] for p in q_pairs], dtype=float),
            metadata={"precursor_mz": float(query_precursor_mz)},
        )
        r = Spectrum(
            mz=np.asarray([p[0] for p in r_pairs], dtype=float),
            intensities=np.asarray([p[1] for p in r_pairs], dtype=float),
            metadata={"precursor_mz": float(ref_precursor_mz)},
        )
    except Exception as exc:
        logger.debug("matchms Spectrum construction failed: %s", exc)
        return 0.0

    try:
        scorer = ModifiedCosine(
            tolerance=tolerance, mz_power=mz_power, intensity_power=intensity_power
        )
        result = scorer.pair(q, r)
        # matchms 0.32+ returns ``Tuple[float, int]``; older versions a
        # numpy structured array indexable by 'score'. Try the common
        # extraction paths in turn.
        if isinstance(result, tuple):
            score = float(result[0])
        elif hasattr(result, "__getitem__"):
            try:
                score = float(result["score"])
            except (TypeError, KeyError, IndexError, ValueError):
                # numpy 0-d / generic array → fall back to int-index
                score = float(result[0])
        else:
            score = float(result)
    except Exception as exc:
        logger.debug("modified cosine pair scoring failed: %s", exc)
        return 0.0

    if score != score:  # NaN guard
        return 0.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


# ---------------------------------------------------------------------------
# In-house score calibration
# ---------------------------------------------------------------------------


def _load_calibration() -> dict[str, Any]:
    """Load the calibration JSON from disk, or return a safe linear fallback.

    Expected schema::

        {
          "method": "minmax",
          "min": <float>,
          "max": <float>,
          "n_samples": <int>,
          "note": "<free-text provenance>"
        }
    """
    if not _CALIBRATION_PATH.exists():
        logger.warning(
            "library_search calibration.json missing at %s; falling back to "
            "linear (x + 1) / 2 rescaling. Compute real calibration on first "
            "real run (see tool_description.md).",
            _CALIBRATION_PATH,
        )
        return {"method": "linear_pm1", "min": -1.0, "max": 1.0}

    with open(_CALIBRATION_PATH) as f:
        data = json.load(f)
    if data.get("method") not in ("minmax", "linear_pm1"):
        logger.warning(
            "Unknown calibration method %r in %s; using linear fallback.",
            data.get("method"),
            _CALIBRATION_PATH,
        )
        return {"method": "linear_pm1", "min": -1.0, "max": 1.0}
    return data


_CALIBRATION_CACHE: dict[str, Any] | None = None


def rescale_inhouse_score(raw: float) -> float:
    """Map a raw ms-clip global-similarity score to ``[0, 1]``.

    Raw ms-clip outputs are dot products of L2-normalised embeddings, so they
    live in ``[-1, 1]``. We clamp after rescaling so the Pydantic ``Candidate``
    constructor never sees an out-of-range value.
    """
    global _CALIBRATION_CACHE
    if _CALIBRATION_CACHE is None:
        _CALIBRATION_CACHE = _load_calibration()
    cal = _CALIBRATION_CACHE

    lo = float(cal.get("min", -1.0))
    hi = float(cal.get("max", 1.0))
    if hi <= lo:
        hi = lo + 1e-6
    scaled = (float(raw) - lo) / (hi - lo)
    if scaled != scaled:  # NaN guard
        return 0.0
    if scaled < 0.0:
        return 0.0
    if scaled > 1.0:
        return 1.0
    return scaled


def reload_calibration_for_tests() -> None:
    """Drop the cached calibration so tests can swap calibration.json on disk."""
    global _CALIBRATION_CACHE
    _CALIBRATION_CACHE = None


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


def fuse_scores(modcos: float | None, inhouse_rescaled: float | None) -> float:
    """Combine the two per-candidate signals into one normalised score.

    See the module-level block comment on why ``max`` is the v0 default. Either
    input may be ``None`` (signal unavailable). If both are ``None`` we return
    ``0.0`` — callers should filter such candidates upstream rather than rely
    on the score alone.
    """
    vals: list[float] = []
    if modcos is not None:
        vals.append(max(0.0, min(1.0, float(modcos))))
    if inhouse_rescaled is not None:
        vals.append(max(0.0, min(1.0, float(inhouse_rescaled))))
    if not vals:
        return 0.0
    return max(vals)
