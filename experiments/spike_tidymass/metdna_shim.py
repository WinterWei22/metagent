"""Python → docker → MetDNA2 R script shim (spike only, not production).

Mirrors the design of docker/cfm_shim_host.py: subprocess docker run, JSON
I/O via a bind-mounted directory. No FastAPI here — spike calls are
one-shot, not a long-running service.
"""
from __future__ import annotations

import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

SPIKE_DIR = Path(__file__).resolve().parent
IO_DIR = SPIKE_DIR / "io"
DATA_DIR = SPIKE_DIR / "data"
IMAGE = "metagent-metdna2-spike:r423-bioc316"


def run_metdna2(
    spectrum: dict[str, Any],
    organism: str = "hsa",
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """Run a single Spectrum through MetDNA2 inside the spike container."""
    IO_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex[:8]
    in_path = IO_DIR / f"in_{job_id}.json"
    out_path = IO_DIR / f"out_{job_id}.json"
    in_path.write_text(json.dumps(spectrum), encoding="utf-8")

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{DATA_DIR}:/spike/data:ro",
        "-v", f"{IO_DIR}:/spike/io",
        IMAGE,
        "/spike/scripts/run_metdna.R",
        "--input", f"/spike/io/in_{job_id}.json",
        "--output", f"/spike/io/out_{job_id}.json",
        "--organism", organism,
        "--polarity", spectrum.get("ion_mode", "positive"),
    ]

    t0 = time.time()
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=timeout_seconds, check=False,
    )
    wall = time.time() - t0

    if proc.returncode != 0:
        raise RuntimeError(
            f"metdna shim exit {proc.returncode}\n"
            f"STDOUT:\n{proc.stdout}\n"
            f"STDERR:\n{proc.stderr}"
        )

    result = json.loads(out_path.read_text(encoding="utf-8"))
    result["_shim_wall_seconds"] = wall
    result["_shim_stdout"] = proc.stdout
    return result


if __name__ == "__main__":
    import sys
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(run_metdna2(payload), indent=2))
