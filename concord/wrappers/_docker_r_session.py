"""Persistent Docker R session manager (W5 D1).

Manages a long-lived container that hosts the ConcordMet R runtime
(MetaboAnalystR + FELLA + KEGG graph pre-warmed). Calls go via
``docker exec`` to avoid per-call 3-5s ``docker run`` startup overhead.

Container lifecycle:
    - ensure_running(): start container if not running; restart if dead
    - exec_request(): JSON request → stdin to entrypoint.R → stdout JSON response
    - shutdown(): docker rm -f (test cleanup)

W5 environment workaround:
    Current Bash session was started before user was added to docker group,
    so ``docker`` commands return permission denied. ``sg docker -c "..."`` is
    used to switch group context for each call. Detected via env or fallback.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_IMAGE = "concord-r:RELEASE_3_19"
DEFAULT_CONTAINER = "concord_r_persistent"
DEFAULT_ENTRYPOINT_PATH = "/opt/entrypoint.R"
DEFAULT_EXEC_TIMEOUT = 120


class DockerNotAvailable(RuntimeError):
    """Docker daemon or `sg docker` not usable."""


class ContainerNotRunning(RuntimeError):
    """Persistent container is not running; auto-restart may have failed."""


@dataclass
class RResponse:
    ok: bool
    data: dict[str, Any]
    stderr: str
    wall_time_sec: float
    exit_code: int


def _detect_docker_invocation() -> list[str]:
    """Decide how to invoke docker on the current shell.

    Returns a command prefix list. Two options tried in order:
      1. Plain ``docker`` (if current process has docker group)
      2. ``sg docker -c "<full command>"`` (workaround for stale shell groups)

    Test via ``docker ps`` once at startup.
    """
    plain = subprocess.run(
        ["docker", "ps"], capture_output=True, text=True, timeout=10,
    )
    if plain.returncode == 0:
        return ["docker"]
    if "permission denied" in plain.stderr.lower():
        # Try sg docker
        sg_check = subprocess.run(
            ["sg", "docker", "-c", "docker ps"],
            capture_output=True, text=True, timeout=10,
        )
        if sg_check.returncode == 0:
            return ["sg", "docker", "-c"]
        raise DockerNotAvailable(
            f"docker daemon access failed via both plain `docker` and "
            f"`sg docker -c`. sg stderr: {sg_check.stderr[:200]}"
        )
    raise DockerNotAvailable(
        f"docker ps failed (rc={plain.returncode}): {plain.stderr[:200]}"
    )


def _run_docker(args: list[str], *, prefix: list[str], timeout: int = 60,
                input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    """Run a docker subcommand using the detected prefix.

    plain docker:    docker <args...>
    sg workaround:   sg docker -c "docker <args...>"
    """
    if prefix[0] == "docker":
        cmd = prefix + args
        return subprocess.run(cmd, capture_output=True, timeout=timeout,
                              input=input_bytes)
    # sg path: prefix is ["sg", "docker", "-c"], wrap full command as one string
    quoted = " ".join(_shell_quote(a) for a in args)
    cmd = prefix + [f"docker {quoted}"]
    return subprocess.run(cmd, capture_output=True, timeout=timeout,
                          input=input_bytes)


def _shell_quote(s: str) -> str:
    if not s or any(c in s for c in " \t\n\"'$\\&|;<>(){}[]*?#"):
        return "'" + s.replace("'", "'\"'\"'") + "'"
    return s


class DockerRSession:
    """Persistent ``docker exec``-driven R session."""

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        container_name: str = DEFAULT_CONTAINER,
        entrypoint_path: str = DEFAULT_ENTRYPOINT_PATH,
        exec_timeout: int = DEFAULT_EXEC_TIMEOUT,
    ) -> None:
        self.image = image
        self.container_name = container_name
        self.entrypoint_path = entrypoint_path
        self.exec_timeout = exec_timeout
        self._docker_prefix: list[str] | None = None

    @property
    def docker_prefix(self) -> list[str]:
        """Lazily detected docker invocation prefix (cached)."""
        if self._docker_prefix is None:
            self._docker_prefix = _detect_docker_invocation()
        return self._docker_prefix

    # ---- container lifecycle -----------------------------------------

    def _container_state(self) -> str:
        """Return docker container status:'running' / 'exited' / 'missing'."""
        r = _run_docker(
            ["inspect", "-f", "{{.State.Status}}", self.container_name],
            prefix=self.docker_prefix, timeout=10,
        )
        out = r.stdout.decode("utf-8", errors="replace").strip()
        if r.returncode != 0:
            return "missing"
        return out or "missing"

    def _image_present(self) -> bool:
        r = _run_docker(["images", "-q", self.image],
                        prefix=self.docker_prefix, timeout=10)
        return bool(r.stdout.strip())

    def ensure_running(self, *, force_restart: bool = False) -> None:
        """Make sure container is up. Start / restart as needed."""
        if not self._image_present():
            raise DockerNotAvailable(
                f"Docker image {self.image!r} not found. Build it via:\n"
                f"  cd data/investigation/docker_r && "
                f"docker build -t {self.image} ."
            )

        state = self._container_state()
        if state == "running" and not force_restart:
            return

        if state in ("exited", "running"):
            # Existing container; either restart or remove + recreate
            if force_restart or state == "exited":
                _run_docker(["rm", "-f", self.container_name],
                            prefix=self.docker_prefix, timeout=20)

        # Spawn fresh persistent container.
        # ``--entrypoint sleep`` is required: the image's Dockerfile sets
        # ``ENTRYPOINT ["Rscript", "/opt/entrypoint.R"]``, so without an
        # override any positional args (``tail -f /dev/null``) become
        # arguments to entrypoint.R — which makes PID 1 a stuck R process
        # that refuses subsequent ``docker exec`` invocations with
        # "OCI runtime exec failed: read init-p: connection reset by peer".
        r = _run_docker(
            ["run", "-d", "--name", self.container_name,
             "--entrypoint", "sleep", self.image, "infinity"],
            prefix=self.docker_prefix, timeout=30,
        )
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", errors="replace")[:200]
            raise ContainerNotRunning(
                f"Failed to start container {self.container_name}: {err}"
            )

    def shutdown(self) -> None:
        """Stop + remove the container."""
        _run_docker(["rm", "-f", self.container_name],
                    prefix=self.docker_prefix, timeout=20)

    # ---- exec --------------------------------------------------------

    def exec_request(
        self,
        request: dict[str, Any],
        *,
        timeout: int | None = None,
        auto_restart: bool = True,
    ) -> RResponse:
        """Run one R request via ``docker exec``. JSON in, JSON out.

        If container is dead and auto_restart=True, restart once and retry.
        """
        timeout = timeout or self.exec_timeout
        payload = json.dumps(request, default=str).encode("utf-8")

        # Ensure container is up (cheap if already running)
        try:
            self.ensure_running()
        except ContainerNotRunning:
            if not auto_restart:
                raise
            self.ensure_running(force_restart=True)

        t0 = time.time()
        try:
            proc = _run_docker(
                ["exec", "-i", self.container_name,
                 "Rscript", self.entrypoint_path],
                prefix=self.docker_prefix, timeout=timeout,
                input_bytes=payload,
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError(
                f"docker exec {self.container_name} Rscript timeout "
                f"after {timeout}s"
            )

        wall = time.time() - t0
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()

        # Last line of stdout should be the JSON response
        last_line = stdout.rsplit("\n", 1)[-1] if stdout else ""
        try:
            data = json.loads(last_line) if last_line else {"error": "empty stdout"}
        except json.JSONDecodeError as e:
            data = {
                "error": f"stdout last line not JSON: {e}",
                "stdout_tail": stdout[-500:],
            }

        ok = (proc.returncode == 0) and (data.get("error") is None)

        # Auto-restart path: container died mid-call → retry once
        if (not ok and auto_restart and self._container_state() != "running"
                and "error" in data
                and ("Container is not running" in data.get("error", "")
                     or "no such container" in data.get("error", "").lower())):
            logger.warning("container %r died during exec; restarting once",
                           self.container_name)
            self.ensure_running(force_restart=True)
            return self.exec_request(request, timeout=timeout, auto_restart=False)

        return RResponse(ok=ok, data=data, stderr=stderr,
                         wall_time_sec=wall, exit_code=proc.returncode)
