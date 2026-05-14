"""§2.1 — exercise spectrum_preprocess on the two negative-mode fixtures.

Acceptance has already validated this on glucose_neg.json. We verify the
same code path on RIKEN-derived fixtures (citric acid, glutamyl-tyrosine).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.spectrum import PreprocessRequest  # noqa: E402
from tools.spectrum_ops.tool import preprocess  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "spectra" / "negative_mode"
FIXTURES = ["citric_acid_neg.json", "glutamyltyrosine_neg.json"]


def run_one(fname: str) -> dict:
    with (FIXTURE_DIR / fname).open() as f:
        fx = json.load(f)
    raw_mz = [p[0] for p in fx["peaks"]]
    raw_int = [p[1] for p in fx["peaks"]]
    req = PreprocessRequest(
        raw_mz=raw_mz,
        raw_intensity=raw_int,
        precursor_mz=fx["precursor_mz"],
        adduct=fx["adduct"],
        ionization_mode=fx["ionization_mode"],
        collision_energy=fx.get("collision_energy"),
    )
    t0 = time.perf_counter()
    try:
        resp = preprocess(req)
    except Exception as e:
        return {
            "fixture": fname,
            "crashed": True,
            "error_type": type(e).__name__,
            "error_msg": str(e),
        }
    dt = time.perf_counter() - t0

    return {
        "fixture": fname,
        "crashed": False,
        "wall_seconds": round(dt, 4),
        "n_in": resp.n_peaks_in,
        "n_out": resp.n_peaks_out,
        "base_peak_mz": resp.base_peak_mz,
        "base_peak_intensity": resp.base_peak_intensity,
        "quality_flag": resp.quality_flag,
        "spectrum_ion_mode": resp.spectrum.ionization_mode,
        "spectrum_adduct": resp.spectrum.adduct,
        "spectrum_max_intensity": max(resp.spectrum.intensity),
        "spectrum_n_peaks": len(resp.spectrum.mz),
        "explain": resp.explain,
    }


def main() -> None:
    print("§2.1 spectrum_preprocess on negative-mode fixtures")
    print("-" * 60)
    for fname in FIXTURES:
        result = run_one(fname)
        print(f"\n{fname}")
        for k, v in result.items():
            if k == "fixture":
                continue
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
