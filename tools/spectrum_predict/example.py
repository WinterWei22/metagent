"""Minimal demo: predict a glucose spectrum via a running CFM-ID container.

Run from repo root: ``python tools/spectrum_predict/example.py``.

Requires ``METAGENT_CFM_URL`` to point at a live CFM-ID shim. See
``docker/README_CFM.md`` for how to start the container.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from schemas.spectrum import PredictSpectrumRequest  # noqa: E402
from tools.spectrum_predict import predict_spectrum  # noqa: E402

req = PredictSpectrumRequest(
    smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
    adduct="[M+H]+",
    ionization_mode="positive",
)
print(predict_spectrum(req).model_dump_json(indent=2))
