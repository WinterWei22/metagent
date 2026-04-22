"""Generator layer for molecule_generate.

The tool's core generation is delegated behind a `Generator` Protocol so that
the real MS-BART adapter and the mock used in tests share one surface. The
real adapter shells out into the `ms-bart` conda env via `conda run` — this
keeps MS-BART's torch/transformers versions isolated from the orchestrator's
env, per maintainer direction.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Protocol

from tools.molecule_gen.errors import ModelLoadError


DEFAULT_CKPT_ENV = "METAGENT_MSBART_CKPT"
DEFAULT_CKPT_PATH = (
    "/home/weiwentao/workspace/mol_gen/MS-BART/data/MassSpecGym/"
    "MS-BART-MassSpecGym/csyanghan/MS-BART-MassSpecGym"
)
MSBART_CONDA_ENV = os.environ.get("METAGENT_MSBART_ENV", "ms-bart")
MSBART_TIMEOUT_SECONDS = int(os.environ.get("METAGENT_MSBART_TIMEOUT", "900"))


@dataclass(frozen=True)
class RawGeneration:
    """One raw sample emitted by a Generator, pre-validation."""

    smiles: str
    seq_log_prob: float
    rank: int


class Generator(Protocol):
    def sample(
        self,
        fingerprint: list[int],
        formula: str | None,
        n: int,
    ) -> list[RawGeneration]:
        """Return n raw candidates (may include invalid SMILES).

        `fingerprint` is a list of fingerprint bit indices (CSI:FingerID
        output). `formula` is optional; the real MS-BART adapter uses it for
        post-hoc sorting, the tool layer still applies it as a hard filter.
        Implementations MUST return up to n items; fewer is allowed if the
        model emits fewer. Empty is allowed.
        """
        ...


# ---------------------------------------------------------------------------
# MS-BART adapter (subprocess into conda env ms-bart)
# ---------------------------------------------------------------------------


class MSBartGenerator:
    """Real adapter. Shells out to _runner.py inside the ms-bart conda env.

    Heavy imports (torch, transformers, selfies) happen in the child process,
    never in the parent, so the orchestrator env stays light.
    """

    def __init__(
        self,
        *,
        checkpoint_path: str | None = None,
        temperature: float = 0.4,
        conda_env: str = MSBART_CONDA_ENV,
        timeout_seconds: int = MSBART_TIMEOUT_SECONDS,
    ):
        self.checkpoint_path = (
            checkpoint_path
            or os.environ.get(DEFAULT_CKPT_ENV)
            or DEFAULT_CKPT_PATH
        )
        self.temperature = temperature
        self.conda_env = conda_env
        self.timeout_seconds = timeout_seconds

    def sample(
        self,
        fingerprint: list[int],
        formula: str | None,
        n: int,
    ) -> list[RawGeneration]:
        if n <= 0:
            return []
        if not os.path.isdir(self.checkpoint_path):
            raise ModelLoadError(
                f"MS-BART checkpoint not found at {self.checkpoint_path}. "
                f"Set {DEFAULT_CKPT_ENV} or place the checkpoint there."
            )

        payload = {
            "fingerprint": list(fingerprint),
            "formula": formula,
            "n_candidates": int(n),
            "checkpoint_path": self.checkpoint_path,
            "temperature": self.temperature,
        }

        cmd = [
            "conda", "run", "-n", self.conda_env, "--no-capture-output",
            "python", "-m", "tools.molecule_gen._runner",
        ]
        repo_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        try:
            proc = subprocess.run(
                cmd,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=repo_root,
                check=False,
            )
        except FileNotFoundError as e:
            raise ModelLoadError(
                "`conda` not found on PATH; cannot dispatch into ms-bart env."
            ) from e
        except subprocess.TimeoutExpired as e:
            raise ModelLoadError(
                f"MS-BART inference timed out after {self.timeout_seconds}s."
            ) from e

        if proc.returncode != 0:
            raise ModelLoadError(
                f"MS-BART runner failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()[-1000:]}"
            )

        try:
            result = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as e:
            raise ModelLoadError(
                f"Could not parse runner output as JSON: {proc.stdout[-500:]}"
            ) from e

        return [
            RawGeneration(
                smiles=item["smiles"],
                seq_log_prob=float(item["seq_log_prob"]),
                rank=int(item["rank"]),
            )
            for item in result.get("candidates", [])
        ]


# ---------------------------------------------------------------------------
# Mock used in tests and for decoder-side work before SIRIUS is ready
# ---------------------------------------------------------------------------


class MockGenerator:
    """Deterministic generator that returns a preset list of candidates.

    Tests construct this with a hand-picked list of (smiles, log_prob) pairs.
    The mock ignores `fingerprint` and `formula` — the tool layer applies
    filtering, so the mock's job is just to emit the raw batch.
    """

    def __init__(self, emissions: list[tuple[str, float]]):
        self._emissions = list(emissions)

    def sample(
        self,
        fingerprint: list[int],
        formula: str | None,
        n: int,
    ) -> list[RawGeneration]:
        if n <= 0:
            return []
        take = self._emissions[:n]
        return [
            RawGeneration(smiles=s, seq_log_prob=lp, rank=i)
            for i, (s, lp) in enumerate(take)
        ]
