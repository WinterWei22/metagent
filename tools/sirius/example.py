"""Example invocation for ``sirius_annotate``."""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from schemas.common import Spectrum
from tools.sirius import MockSiriusRunner, SiriusAnnotateRequest, sirius_annotate
from tools.sirius.errors import SiriusNotInstalledError


def _glucose_spectrum() -> Spectrum:
    return Spectrum(
        mz=[61.0284, 73.0284, 85.0284, 109.0284, 127.0390, 145.0495, 163.0601],
        intensity=[0.09, 0.12, 0.18, 0.25, 0.38, 0.42, 1.0],
        precursor_mz=181.0707,
        adduct="[M+H]+",
        ionization_mode="positive",
        collision_energy=20.0,
    )


if __name__ == "__main__":
    request = SiriusAnnotateRequest(spectrum=_glucose_spectrum())
    try:
        response = sirius_annotate(request)
    except SiriusNotInstalledError:
        response = sirius_annotate(request, runner=MockSiriusRunner())
    print(response.model_dump_json(indent=2))
