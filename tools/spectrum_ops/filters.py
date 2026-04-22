"""Low-level signal-processing helpers for spectrum_preprocess.

Kept separate from tool.py to make the pure numeric ops easy to unit-test and
to keep tool.py focused on request/response orchestration.
"""
from __future__ import annotations

import numpy as np


def merge_peaks_within_ppm(
    mz: np.ndarray,
    intensity: np.ndarray,
    tolerance_ppm: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Merge adjacent peaks whose m/z are within `tolerance_ppm`.

    Input mz MUST be sorted ascending. Merging is greedy left-to-right: a peak
    joins the current cluster when its mz is within `tolerance_ppm` of the
    cluster's running intensity-weighted centroid. Cluster output uses the
    weighted centroid for m/z and the summed intensity.
    """
    if mz.size == 0:
        return mz, intensity
    if mz.size == 1:
        return mz.copy(), intensity.copy()

    out_mz: list[float] = []
    out_int: list[float] = []

    cur_weighted_mz = float(mz[0] * intensity[0])
    cur_int = float(intensity[0])
    cur_centroid = float(mz[0])

    for i in range(1, mz.size):
        gap_ppm = (float(mz[i]) - cur_centroid) / cur_centroid * 1e6
        if gap_ppm <= tolerance_ppm:
            cur_weighted_mz += float(mz[i] * intensity[i])
            cur_int += float(intensity[i])
            cur_centroid = cur_weighted_mz / cur_int if cur_int > 0 else float(mz[i])
        else:
            out_mz.append(cur_weighted_mz / cur_int if cur_int > 0 else cur_centroid)
            out_int.append(cur_int)
            cur_weighted_mz = float(mz[i] * intensity[i])
            cur_int = float(intensity[i])
            cur_centroid = float(mz[i])

    out_mz.append(cur_weighted_mz / cur_int if cur_int > 0 else cur_centroid)
    out_int.append(cur_int)

    return np.asarray(out_mz, dtype=float), np.asarray(out_int, dtype=float)
