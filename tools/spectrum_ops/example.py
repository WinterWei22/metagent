"""Minimal demo: preprocess a glucose-style spectrum and print the response.

Run from repo root: `python tools/spectrum_ops/example.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from schemas.spectrum import PreprocessRequest  # noqa: E402
from tools.spectrum_ops import preprocess  # noqa: E402

req = PreprocessRequest(
    raw_mz=[163.0601, 145.0495, 127.0390, 109.0284, 85.0284, 73.0284, 61.0284],
    raw_intensity=[1000.0, 420.0, 380.0, 250.0, 180.0, 120.0, 90.0],
    precursor_mz=181.0707,
    adduct="[M+H]+",
    ionization_mode="positive",
    collision_energy=20.0,
)
print(preprocess(req).model_dump_json(indent=2))
