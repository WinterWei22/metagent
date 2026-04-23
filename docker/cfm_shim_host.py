"""Host-side FastAPI shim — the rootless fallback when the container
runtime can't build a Dockerfile (e.g. ``udocker``, which is a runner, not a
builder).

Why this file exists
--------------------
The primary deployment path is ``docker/cfm_id.Dockerfile``: a built image
that carries Python, FastAPI, and ``cfm_shim.py`` inside it, so the Python
tool talks HTTP to a service the container itself runs. That requires
Docker or Podman to build the image.

On hosts where only ``udocker`` is available (no Docker daemon access, no
root), the base image ``wishartlab/cfmid:latest`` is usable as-is but
contains no Python interpreter — we cannot run FastAPI inside it. This
module is the same shim, inverted: it runs on the **host**, and every
``/predict`` call shells out to ``udocker run <container> cfm-predict ...``
to do the actual work.

The client in ``tools/spectrum_predict/cfm_client.py`` cannot tell the
difference between the two deployments; the shim contract is identical.

Environment knobs
-----------------
- ``CFM_UDOCKER_CONTAINER`` — name of the pre-created udocker container
  (see ``README_CFM.md``). Default ``metagent-cfmid``.
- ``CFM_UDOCKER_BIN`` — path to the ``udocker`` executable. Default picks
  up ``udocker`` from PATH.
- ``CFM_VERSION`` — reported in the response. Default ``cfm-id-4.4.7``.
- ``CFM_PREDICT_BIN_IN_CONTAINER`` — binary path inside the udocker image.
  Default ``/opt/cfm/bin/cfm-predict`` (verified against the 2026-04
  ``wishartlab/cfmid:latest``).
- ``CFM_MODEL_DIR_IN_CONTAINER`` — model dir inside the image. Default
  ``/trained_models_cfmid4.0``.

Run
---
    /opt/shim/bin/uvicorn cfm_shim_host:app --host 0.0.0.0 --port 8088

Requires ``fastapi``, ``uvicorn``, ``pydantic`` on the host. A pinned
``requirements.txt`` for just the shim is included alongside this file.
"""
from __future__ import annotations

import os
import subprocess
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

UDOCKER_BIN = os.environ.get("CFM_UDOCKER_BIN", "udocker")
CONTAINER = os.environ.get("CFM_UDOCKER_CONTAINER", "metagent-cfmid")
CFM_VERSION = os.environ.get("CFM_VERSION", "cfm-id-4.4.7")
CFM_BIN_INSIDE = os.environ.get(
    "CFM_PREDICT_BIN_IN_CONTAINER", "/opt/cfm/bin/cfm-predict"
)
CFM_MODEL_DIR_INSIDE = os.environ.get(
    "CFM_MODEL_DIR_IN_CONTAINER", "/trained_models_cfmid4.0"
)

# cfm-predict expects the adduct-specific model directory as the last two
# args (``param_output.log`` + ``param_config.txt``). The directory names
# literally contain the adduct strings with special characters, which is
# why they must be quoted when typed in a shell — but here we pass them as
# argv elements and do not invoke a shell, so no escaping is needed.
_MODEL_SUBDIR = {
    "positive": "[M+H]+",
    "negative": "[M-H]-",
}


class PredictIn(BaseModel):
    smiles: str = Field(..., min_length=1)
    adduct: str = Field(..., description="e.g. '[M+H]+'")
    ionization_mode: Literal["positive", "negative"]
    timeout_seconds: float = Field(60.0, gt=0, le=600)


class PredictOut(BaseModel):
    model_version: str
    cfm_stdout: str


app = FastAPI(title="metagent-cfm-id-host-shim", version=CFM_VERSION)


@app.get("/healthz")
def healthz() -> dict:
    """Liveness probe. Also confirms the udocker container is reachable —
    we invoke ``udocker ps`` and check the target container is listed.
    """
    try:
        out = subprocess.run(
            [UDOCKER_BIN, "ps"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f"udocker binary not found at {UDOCKER_BIN!r}: {e}",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="`udocker ps` hung")
    if CONTAINER not in out.stdout:
        raise HTTPException(
            status_code=500,
            detail=(
                f"udocker container {CONTAINER!r} not found. "
                f"Run `udocker create --name={CONTAINER} wishartlab/cfmid:latest`."
            ),
        )
    return {"status": "ok", "model_version": CFM_VERSION, "container": CONTAINER}


@app.post("/predict", response_model=PredictOut)
def predict(req: PredictIn) -> PredictOut:
    subdir = _MODEL_SUBDIR[req.ionization_mode]
    param_in_container = f"{CFM_MODEL_DIR_INSIDE}/{subdir}/param_output.log"
    config_in_container = f"{CFM_MODEL_DIR_INSIDE}/{subdir}/param_config.txt"

    # argv form: no shell, so user-supplied SMILES cannot escape into
    # command injection. udocker does not need `-c bash` here because
    # ``run <container> <prog> [args...]`` is the supported form.
    cmd = [
        UDOCKER_BIN,
        "run",
        CONTAINER,
        CFM_BIN_INSIDE,
        req.smiles,
        "0.001",
        param_in_container,
        config_in_container,
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=req.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="cfm-predict timed out")
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f"udocker binary not found at {UDOCKER_BIN!r}: {e}",
        )

    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=(
                f"cfm-predict exited {completed.returncode}: "
                f"{completed.stderr[-500:]}"
            ),
        )

    # udocker prints a banner before (and after) the container program's
    # stdout. The banner starts with the line
    #   ``****************************************************************************``
    # followed by ``STARTING <container-id>`` and ends with ``executing: <cmd>``.
    # Strip the leading banner so the client sees only cfm-predict output.
    stdout = _strip_udocker_banner(completed.stdout)
    return PredictOut(model_version=CFM_VERSION, cfm_stdout=stdout)


def _strip_udocker_banner(text: str) -> str:
    """Remove udocker's leading/trailing banner lines around the inner
    program's stdout.

    udocker prints a framed ``STARTING <id>`` / ``executing: ...`` banner.
    In v1.3.x the banner sometimes lands *after* the program's stdout when
    the program writes line-buffered — so the safe approach is to drop any
    line that matches the known banner patterns, not slice by position.
    """
    kept: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            kept.append(line)
            continue
        if s.startswith("*") and s.endswith("*"):
            continue
        if s.startswith("STARTING "):
            continue
        if s.startswith("executing:"):
            continue
        kept.append(line)
    return "\n".join(kept).strip() + "\n"
