"""Unit tests for the persistent docker R session manager (W5 D1).

All tests skip if image not built or docker daemon not reachable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.wrappers._docker_r_session import (
    DEFAULT_CONTAINER,
    DEFAULT_IMAGE,
    DockerNotAvailable,
    DockerRSession,
    _detect_docker_invocation,
    _shell_quote,
)


def _docker_image_present(image: str) -> bool:
    try:
        prefix = _detect_docker_invocation()
        if prefix[0] == "docker":
            import subprocess
            r = subprocess.run(["docker", "images", "-q", image],
                               capture_output=True, timeout=10)
            return bool(r.stdout.strip())
        else:
            import subprocess
            r = subprocess.run(["sg", "docker", "-c", f"docker images -q {image}"],
                               capture_output=True, timeout=10)
            return bool(r.stdout.strip())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_image_present(DEFAULT_IMAGE),
    reason=f"docker image {DEFAULT_IMAGE!r} not built — run docker build first",
)


# ---------------------------------------------------------------------------
# Pure-Python helpers (no docker needed)
# ---------------------------------------------------------------------------


def test_shell_quote_basic():
    assert _shell_quote("foo") == "foo"
    assert _shell_quote("hello world") == "'hello world'"
    assert _shell_quote("it's") == "'it'\"'\"'s'"


# ---------------------------------------------------------------------------
# Docker-dependent integration
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def session():
    s = DockerRSession(container_name="concord_r_test_session")
    yield s
    try:
        s.shutdown()
    except Exception:
        pass


def test_docker_invocation_detect():
    """Detect docker prefix — should be either ['docker'] or ['sg', 'docker', '-c']."""
    prefix = _detect_docker_invocation()
    assert prefix in (["docker"], ["sg", "docker", "-c"])


def test_session_ensure_running(session):
    """Start a fresh container, verify state."""
    session.shutdown()  # cleanup any prior
    session.ensure_running()
    assert session._container_state() == "running"


def test_session_self_test(session):
    """Run entrypoint.R --self-test inside the container.

    Verifies package presence + KEGG data ready state.
    """
    import subprocess
    from concord.wrappers._docker_r_session import _run_docker
    r = _run_docker(
        ["exec", session.container_name, "Rscript",
         session.entrypoint_path, "--self-test"],
        prefix=session.docker_prefix, timeout=60,
    )
    stdout = r.stdout.decode("utf-8", errors="replace").strip()
    last_line = stdout.rsplit("\n", 1)[-1] if stdout else ""
    import json
    data = json.loads(last_line)
    assert data["self_test"] == "done"
    assert "packages" in data
    # FELLA + MetaboAnalystR should be installed
    assert data["packages"].get("FELLA") is True
    assert data["packages"].get("MetaboAnalystR") is True


def test_session_exec_unknown_method(session):
    """A bogus method dispatches to entrypoint's 'unknown method' branch."""
    resp = session.exec_request({"method": "no_such_method_zzz"}, timeout=30)
    assert resp.exit_code == 1
    assert "unknown" in (resp.data.get("error") or "").lower()


def test_session_shutdown(session):
    """Shutdown removes the container."""
    session.shutdown()
    assert session._container_state() == "missing"
