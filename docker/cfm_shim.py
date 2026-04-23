"""FastAPI shim in front of CFM-ID 4.0's ``cfm-predict`` binary.

Lives inside the container built from ``cfm_id.Dockerfile``. Designed to be
tiny and dependency-free beyond FastAPI/uvicorn/pydantic so the image stays
small and the attack surface stays trivially auditable.

Request/response shapes are documented in both the Dockerfile header and in
``tools/spectrum_predict/cfm_client.py``. Keep all three in sync.

The binary takes its input as an ``.ms`` file; we write the SMILES to a tmp
file, invoke ``cfm-predict``, and return stdout verbatim. Intensity parsing
lives in the Python tool (``tools.spectrum_predict.parser``), not here — the
shim is only a transport.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

CFM_BIN = os.environ.get("CFM_PREDICT_BIN", "/opt/cfm/bin/cfm-predict")
CFM_MODEL_DIR = os.environ.get("CFM_MODEL_DIR", "/trained_models_cfmid4.0")
CFM_VERSION = os.environ.get("CFM_VERSION", "cfm-id-4.4.7")

# cfm-predict separates positive and negative ESI model directories by
# convention. Update if the upstream image changes its layout.
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


app = FastAPI(title="metagent-cfm-id", version=CFM_VERSION)


@app.get("/healthz")
def healthz() -> dict:
    """Liveness probe used by the Python client's integration test gate."""
    return {"status": "ok", "model_version": CFM_VERSION}


@app.post("/predict", response_model=PredictOut)
def predict(req: PredictIn) -> PredictOut:
    if not Path(CFM_BIN).exists():
        # 500 so the client translates this into CfmUnavailableError — the
        # image is mis-configured and an operator has to fix it.
        raise HTTPException(
            status_code=500,
            detail=f"cfm-predict binary not found at {CFM_BIN}",
        )
    model_dir = Path(CFM_MODEL_DIR) / _MODEL_SUBDIR[req.ionization_mode]
    param_file = model_dir / "param_output.log"
    config_file = model_dir / "param_config.txt"
    if not param_file.exists() or not config_file.exists():
        raise HTTPException(
            status_code=500,
            detail=f"CFM-ID model files missing under {model_dir}",
        )

    # cfm-predict CLI (verified against v4.4.7):
    #   cfm-predict <smiles_or_inchi> <prob_thresh> <param> <config>
    # The binary is invoked via argv (no shell) so SMILES escaping is safe.
    cmd = [
        CFM_BIN,
        req.smiles,
        "0.001",            # prob_thresh_for_prune (default)
        str(param_file),    # trained parameters
        str(config_file),   # model config
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
        # Return 504 so the client maps this to PredictionTimeoutError.
        # requests-level timeout in the client is the primary guard; this
        # is a second line of defence if the client socket timeout is
        # longer than the shim's process timeout.
        raise HTTPException(status_code=504, detail="cfm-predict timed out")

    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=(
                f"cfm-predict exited {completed.returncode}: "
                f"{completed.stderr[-500:]}"
            ),
        )

    return PredictOut(
        model_version=CFM_VERSION,
        cfm_stdout=completed.stdout,
    )
