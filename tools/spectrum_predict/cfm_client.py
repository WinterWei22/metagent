"""HTTP client for the CFM-ID 4.0 container.

The container (see ``docker/cfm_id.Dockerfile``) wraps ``cfm-predict`` with a
minimal FastAPI shim. This module is the *only* place that speaks HTTP; the
rest of the tool operates on parsed peak lists so that swapping the transport
(e.g. gRPC, stdin pipe) later does not ripple through the package.

Shim contract (v0) — ``POST /predict`` with JSON body::

    {
        "smiles": "<canonical SMILES>",
        "adduct": "[M+H]+",
        "ionization_mode": "positive",
        "timeout_seconds": 60
    }

Returns JSON::

    {
        "model_version": "cfm-id-4.0.0",
        "cfm_stdout": "energy0\\n...\\nenergy1\\n...\\nenergy2\\n..."
    }

The client deliberately does NOT parse ``cfm_stdout`` — that is ``parser.py``.
This separation lets the parser be tested against raw text fixtures lifted
straight from the CFM-ID documentation.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import requests

from tools.spectrum_predict.errors import CfmUnavailableError, PredictionTimeoutError

DEFAULT_URL = "http://localhost:8088"
DEFAULT_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class CfmResponse:
    """Raw container response; parsing happens in ``parser.py``."""

    model_version: str
    cfm_stdout: str


def _base_url() -> str:
    """Pick up ``METAGENT_CFM_URL`` at call time (not import time).

    Reading the env var lazily lets tests flip the URL between test cases
    without re-importing the module.
    """
    return os.environ.get("METAGENT_CFM_URL", DEFAULT_URL).rstrip("/")


def predict(
    *,
    smiles: str,
    adduct: str,
    ionization_mode: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> CfmResponse:
    """Call the CFM-ID shim. Raise typed errors on transport failure.

    The shim is expected to run a single ``cfm-predict`` invocation per
    request. CFM-ID always produces three energy ramps internally regardless
    of the user's requested labels, so ``collision_energies`` is not sent —
    the tool layer maps indices onto eV labels after parsing.

    Any error short of a successful 200 with the documented JSON body is
    translated into a ``ToolError`` subclass so the orchestrator can react
    on error codes rather than string-matching exception messages.
    """
    url = _base_url() + "/predict"
    payload = {
        "smiles": smiles,
        "adduct": adduct,
        "ionization_mode": ionization_mode,
        "timeout_seconds": timeout_s,
    }

    try:
        resp = requests.post(url, json=payload, timeout=timeout_s)
    except requests.exceptions.Timeout as e:
        raise PredictionTimeoutError(
            f"CFM-ID did not respond within {timeout_s:.0f}s for SMILES={smiles!r}."
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise CfmUnavailableError(
            f"CFM-ID shim at {url} is unreachable: {e}. "
            "Start the container (see docker/README_CFM.md) or set METAGENT_CFM_URL."
        ) from e

    if resp.status_code >= 500:
        # Treat 5xx as container-side unavailability — the shim is running
        # but its backend died. Same operator response as a refused
        # connection: restart or replace the container.
        raise CfmUnavailableError(
            f"CFM-ID shim at {url} returned HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    if resp.status_code >= 400:
        # 4xx from the shim means it rejected our inputs (e.g. adduct not
        # in its table). Surface as a regular error — not a ToolError
        # subclass, because this is a programming bug in the tool layer,
        # not a condition the orchestrator should try to route around.
        raise RuntimeError(
            f"CFM-ID shim rejected request (HTTP {resp.status_code}): "
            f"{resp.text[:300]}"
        )

    try:
        body = resp.json()
    except ValueError as e:
        raise CfmUnavailableError(
            f"CFM-ID shim returned non-JSON body: {resp.text[:300]}"
        ) from e

    stdout = body.get("cfm_stdout")
    version = body.get("model_version")
    if not isinstance(stdout, str) or not isinstance(version, str) or not version:
        raise CfmUnavailableError(
            f"CFM-ID shim response missing required fields "
            f"(model_version, cfm_stdout): got keys={list(body.keys())}"
        )

    return CfmResponse(model_version=version, cfm_stdout=stdout)
