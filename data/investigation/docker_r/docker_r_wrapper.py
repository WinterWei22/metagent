"""ConcordMet Docker R subprocess wrapper — Q-03 (A) Python side.

Provides a clean Python API for calling MetaboAnalystR / FELLA inside the
`concordmet-r` Docker image,绕过 host conda env native-compile 限制
(R-NEW-14 root cause)。

Usage(Sprint W4-W5 normalize_*_output() 实施时):
    >>> from data.investigation.docker_r import docker_r_wrapper as drw
    >>> response = drw.call_r({"method": "fella_rwr",
    ...                        "params": {"compounds": ["C00031", "C00022"],
    ...                                   "organism": "hsa"}})
    >>> response  # JSON-loaded dict

Concurrency(Sprint W5 D3 spike):
    Use `concurrent.futures.ThreadPoolExecutor` with `max_workers=K`,each
    worker spawns its own `docker exec`(or `docker run --rm`)— shells out
    via subprocess so GIL is released. K=10 baseline.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_IMAGE = "concordmet-r:v0.1"
DEFAULT_TIMEOUT_SEC = 120  # FELLA RWR single call ~5-15s, give 8x headroom


@dataclass
class RResponse:
    ok: bool
    data: dict[str, Any]
    stderr: str
    wall_time_sec: float
    exit_code: int


def call_r(
    request: dict[str, Any],
    *,
    image: str = DEFAULT_IMAGE,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    use_run: bool = True,  # False → docker exec on persistent container (W5+ optimization)
) -> RResponse:
    """Call concordmet-r entrypoint with a JSON request.

    Args:
        request: dict;will be JSON-serialized to subprocess stdin.
                 Must contain "method" key.
        image: docker image tag,default concordmet-r:v0.1
        timeout_sec: hard timeout(SIGKILL after)
        use_run: True → `docker run --rm -i <image>` per call(simple,~2-3s startup);
                 False → `docker exec` on a long-lived container(W5+ for K=10 spike performance)

    Returns:
        RResponse with ok flag, parsed data, stderr, wall time, exit code.
    """
    if "method" not in request:
        raise ValueError("request must contain 'method' key")

    t0 = time.time()
    payload = json.dumps(request).encode("utf-8")

    if use_run:
        cmd = ["docker", "run", "--rm", "-i", image]
    else:
        raise NotImplementedError(
            "docker exec path not yet wired (W5 D3 optimization)"
        )

    try:
        proc = subprocess.run(
            cmd,
            input=payload,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        return RResponse(
            ok=False, data={"error": "timeout", "timeout_sec": timeout_sec},
            stderr=(e.stderr or b"").decode("utf-8", errors="replace"),
            wall_time_sec=time.time() - t0, exit_code=-1,
        )

    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()
    wall = time.time() - t0

    try:
        data = json.loads(stdout) if stdout else {"error": "empty stdout"}
    except json.JSONDecodeError as e:
        data = {"error": f"stdout not JSON: {e}", "stdout_raw": stdout[:500]}

    ok = (proc.returncode == 0) and (data.get("error") is None)
    return RResponse(
        ok=ok, data=data, stderr=stderr,
        wall_time_sec=wall, exit_code=proc.returncode,
    )


def self_test(image: str = DEFAULT_IMAGE) -> RResponse:
    """Run the entrypoint self-test inside the docker image."""
    t0 = time.time()
    proc = subprocess.run(
        ["docker", "run", "--rm", image, "--self-test"],
        capture_output=True, timeout=60, check=False,
    )
    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()
    # Last line should be JSON
    last_line = stdout.split("\n")[-1] if stdout else ""
    try:
        data = json.loads(last_line)
    except json.JSONDecodeError:
        data = {"error": "self-test stdout last line not JSON",
                "stdout_tail": stdout[-500:]}
    return RResponse(
        ok=(proc.returncode == 0),
        data=data, stderr=stderr,
        wall_time_sec=time.time() - t0,
        exit_code=proc.returncode,
    )


def check_image_built(image: str = DEFAULT_IMAGE) -> bool:
    """Quick check: is the concordmet-r image built locally?"""
    proc = subprocess.run(
        ["docker", "images", "-q", image],
        capture_output=True, timeout=10, check=False,
    )
    return bool(proc.stdout.strip())


if __name__ == "__main__":
    # Smoke test: image build check + self-test if built
    import sys
    print(f"Image '{DEFAULT_IMAGE}' built locally: {check_image_built()}", flush=True)
    if check_image_built():
        print("Running self-test ...", flush=True)
        r = self_test()
        print(f"  ok: {r.ok}  exit: {r.exit_code}  wall: {r.wall_time_sec:.1f}s")
        print(f"  data: {r.data}")
    else:
        print(f"Image not built. Build it via:")
        print(f"  cd {Path(__file__).parent}")
        print(f"  docker build -t {DEFAULT_IMAGE} .")
        sys.exit(2)
