"""Track A1 — `spectrum_preprocess`.

Public entry point: `preprocess(req: PreprocessRequest) -> PreprocessResponse`.
Signature is locked by `schemas/spectrum.py`; this module only supplies the
implementation. Deterministic signal processing — no LLM, no I/O.

Pipeline:
  1. Guard against the v0-unsupported negative ion mode.
  2. Capture base-peak m/z and intensity in the ORIGINAL scale (needed in the
     response even though the output spectrum is later renormalised).
  3. Sort peaks by m/z ascending (matchms requires sorted input).
  4. Normalise intensities so the base peak = 1.0 (matchms).
  5. Drop peaks below `min_relative_intensity` (matchms filter on normalised
     scale — safe because intensities are now in [0, 1]).
  6. Merge near-duplicate peaks within `mz_tolerance_ppm` (intensity-weighted
     centroid for m/z, summed intensity).
  7. Re-normalise: merging can raise the surviving maximum above 1.0 if two
     large peaks fell within tolerance.
  8. Assign quality_flag and raise InvalidSpectrumError if < 3 peaks survive.
"""
from __future__ import annotations

import numpy as np
from matchms import Spectrum as MatchmsSpectrum
from matchms.filtering import normalize_intensities, select_by_relative_intensity

from schemas.common import Spectrum
from schemas.spectrum import PreprocessRequest, PreprocessResponse
from tools.spectrum_ops.errors import InvalidSpectrumError
from tools.spectrum_ops.filters import merge_peaks_within_ppm


def preprocess(req: PreprocessRequest) -> PreprocessResponse:
    if req.ionization_mode == "negative":
        raise NotImplementedError(
            "spectrum_preprocess v0 supports positive ionization only."
        )

    raw_mz = np.asarray(req.raw_mz, dtype=float)
    raw_int = np.asarray(req.raw_intensity, dtype=float)

    # Belt-and-suspenders: Pydantic also enforces equal lengths, but a hand-built
    # request could still slip through if someone bypasses validation.
    if raw_mz.size != raw_int.size:
        raise InvalidSpectrumError(
            f"raw_mz and raw_intensity length mismatch: "
            f"{raw_mz.size} vs {raw_int.size}"
        )

    n_peaks_in = int(raw_mz.size)

    # Base peak in ORIGINAL scale (required field of the response).
    base_idx = int(np.argmax(raw_int))
    base_peak_mz = float(raw_mz[base_idx])
    base_peak_intensity = float(raw_int[base_idx])
    if base_peak_intensity <= 0:
        raise InvalidSpectrumError(
            "All peak intensities are non-positive; spectrum has no signal."
        )

    # matchms requires mz sorted ascending at Spectrum construction.
    order = np.argsort(raw_mz)
    mz_sorted = raw_mz[order]
    int_sorted = raw_int[order]

    ms_spec: MatchmsSpectrum | None = MatchmsSpectrum(
        mz=mz_sorted, intensities=int_sorted
    )
    ms_spec = normalize_intensities(ms_spec)
    ms_spec = select_by_relative_intensity(
        ms_spec, intensity_from=req.min_relative_intensity
    )

    if ms_spec is None or ms_spec.peaks.mz.size == 0:
        raise InvalidSpectrumError(
            "All peaks removed by relative-intensity filter; nothing left to process."
        )

    mz_f = np.asarray(ms_spec.peaks.mz, dtype=float)
    int_f = np.asarray(ms_spec.peaks.intensities, dtype=float)

    mz_m, int_m = merge_peaks_within_ppm(mz_f, int_f, req.mz_tolerance_ppm)

    # Re-normalise so the base peak is exactly 1.0 after merging.
    max_int = float(int_m.max()) if int_m.size else 0.0
    if max_int > 0:
        int_m = int_m / max_int

    n_peaks_out = int(mz_m.size)

    if n_peaks_out < 3:
        raise InvalidSpectrumError(
            f"Only {n_peaks_out} peak(s) survived filtering (need ≥ 3); "
            f"quality=invalid."
        )

    total_int = float(int_m.sum())
    top_frac = float(int_m.max() / total_int) if total_int > 0 else 0.0

    if n_peaks_out <= 9:
        quality_flag = "sparse"
    elif top_frac > 0.9:
        quality_flag = "noisy"
    else:
        quality_flag = "good"

    spectrum = Spectrum(
        mz=mz_m.tolist(),
        intensity=int_m.tolist(),
        precursor_mz=req.precursor_mz,
        adduct=req.adduct,
        ionization_mode=req.ionization_mode,
        collision_energy=req.collision_energy,
    )

    n_dropped = n_peaks_in - n_peaks_out
    explain = (
        f"Preprocessed {n_peaks_in} input peaks → {n_peaks_out} "
        f"(dropped {n_dropped}) after relative-intensity filter "
        f"≥ {req.min_relative_intensity:g} and {req.mz_tolerance_ppm:g} ppm "
        f"merge; base peak at m/z {base_peak_mz:.4f}; quality={quality_flag}."
    )

    return PreprocessResponse(
        spectrum=spectrum,
        n_peaks_in=n_peaks_in,
        n_peaks_out=n_peaks_out,
        base_peak_mz=base_peak_mz,
        base_peak_intensity=base_peak_intensity,
        quality_flag=quality_flag,
        explain=explain,
    )
