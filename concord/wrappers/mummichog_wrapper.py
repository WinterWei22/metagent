"""Outer mummichog wrapper — runs Py3.13 main concord side, spawns Py3.10
venv subprocess that invokes ``_mummichog_runner.py`` (W4 D1).

Architecture:
    main py3.13 ──subprocess──> py3.10 venv ──> mummichog 2.7.0
                  (JSON stdin)                  (TSV file + stdout JSON)

This split is forced by mummichog's Python 3.7-3.10 compatibility ceiling —
we cannot import mummichog from Py3.13 directly.

Usage:
    >>> from concord.wrappers.mummichog_wrapper import run_mummichog
    >>> from concord.schema.peak import PeakRecord
    >>> peaks = [PeakRecord(mz=180.0634, p_value=0.001, t_score=4.5),
    ...          PeakRecord(mz=181.0712, p_value=0.7,  t_score=0.3)]
    >>> result = run_mummichog(peaks, mode="positive")
    >>> result["pathways"][0]["pathway_id"]
    'KEGG:Alanine and Aspartate Metabolism'   # human_mfn name → KEGG: namespace

NOTE: mummichog 2.7.0 outputs pathway names from `human_mfn` (not stable KEGG
mapIDs). D2 normalizer converts these to v0.3 EnrichmentResult with
``pathway_id_native`` carrying the original mfn name.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from concord.schema.peak import PeakRecord

logger = logging.getLogger(__name__)

# Py3.10 conda env from Session 2 (mummichog 2.7.0 installed)
DEFAULT_VENV_PYTHON = Path("/home/weiwentao/miniconda3/envs/mummichog_py310/bin/python")
DEFAULT_RUNNER = Path(__file__).resolve().parent / "_mummichog_runner.py"
DEFAULT_TIMEOUT_SEC = 180


class MummichogVenvMissing(FileNotFoundError):
    """Py3.10 mummichog venv not found at expected path."""

    def __init__(self, venv_python: Path):
        super().__init__(
            f"Mummichog Py3.10 venv python not found at {venv_python}. "
            f"Install via:\n"
            f"  conda create -n mummichog_py310 python=3.10 -y\n"
            f"  /home/weiwentao/miniconda3/envs/mummichog_py310/bin/pip install "
            f"mummichog setuptools<80 tqdm"
        )


class MummichogSubprocessError(RuntimeError):
    """mummichog subprocess returned non-zero or surfaced runner-level errors."""


def run_mummichog(
    peaks: list[PeakRecord],
    *,
    mode: Literal["positive", "negative"] = "positive",
    ref_db: Literal["mfn", "hmdb", "kegg"] = "mfn",
    permutations: int = 100,
    instrument_ppm: int = 10,
    force_primary_ion: bool = True,
    venv_python: Path = DEFAULT_VENV_PYTHON,
    runner_script: Path = DEFAULT_RUNNER,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run mummichog v2.7.0 in a Py3.10 venv subprocess.

    Args:
        peaks: list of PeakRecord (m/z + p-value + optional t-score / RT).
        mode: ionization polarity for mummichog. positive | negative.
        ref_db: reference network model. Only "mfn" (human_mfn) is shipped with
            mummichog 2.7.0 out of the box; "hmdb"/"kegg" would require custom
            JSON metabolic models (W5+ task).
        permutations: mummichog permutation count for null distribution.
            Default 100 (D1 quick path uses 20-50; Sprint uses 100).
        instrument_ppm: instrument mass accuracy.
        force_primary_ion: mummichog -z flag.
        venv_python: path to Py3.10 venv's python executable.
        runner_script: path to _mummichog_runner.py (this dir by default).
        timeout_sec: hard subprocess timeout.

    Returns:
        dict with keys:
          - "pathways": list of pathway hits (pathway_id, p_value, hits_kegg_ids, …)
          - "empirical_compounds": list of EmpCompound records
          - "stats": dict (wall_time_sec, n_significant, n_pathways_tested)
          - "errors": list[str] — runner-level errors (non-fatal warnings)
          - "wall_time_sec": float — total wall on the outer call (incl. subprocess overhead)
          - "tool_version": "mummichog-2.7.0"
          - "parameters": dict echo of inputs

    Raises:
        ValueError on invalid input.
        MummichogVenvMissing if venv_python doesn't exist.
        TimeoutError if subprocess exceeds timeout_sec.
        MummichogSubprocessError on non-zero exit + recoverable errors list.
    """
    if not isinstance(peaks, list):
        raise ValueError(f"peaks must be a list, got {type(peaks).__name__}")
    if mode not in ("positive", "negative"):
        raise ValueError(f"mode must be positive|negative, got {mode!r}")
    if ref_db not in ("mfn", "hmdb", "kegg"):
        raise ValueError(f"ref_db must be mfn|hmdb|kegg, got {ref_db!r}")
    if not venv_python.exists():
        raise MummichogVenvMissing(venv_python)
    if not runner_script.exists():
        raise FileNotFoundError(f"runner script not found: {runner_script}")

    # Empty peaks list: short-circuit (don't bother subprocess)
    if not peaks:
        return {
            "pathways": [], "empirical_compounds": [],
            "stats": {"n_features_in": 0, "n_significant": 0,
                      "n_pathways_tested": 0, "wall_time_sec": 0.0},
            "errors": [], "wall_time_sec": 0.0,
            "tool_version": "mummichog-2.7.0",
            "parameters": {
                "mode": mode, "ref_db": ref_db, "permutations": permutations,
                "instrument_ppm": instrument_ppm,
                "force_primary_ion": force_primary_ion,
            },
        }

    request = {
        "peaks": [asdict(p) for p in peaks],
        "mode": mode,
        "ref_db": ref_db,
        "permutations": permutations,
        "instrument_ppm": instrument_ppm,
        "force_primary_ion": force_primary_ion,
    }
    payload = json.dumps(request).encode("utf-8")

    t0 = time.time()
    try:
        proc = subprocess.run(
            [str(venv_python), str(runner_script)],
            input=payload, capture_output=True, timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        raise TimeoutError(
            f"mummichog subprocess exceeded {timeout_sec}s timeout"
        ) from e

    wall = time.time() - t0
    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()

    # Parse runner JSON
    try:
        result = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as e:
        raise MummichogSubprocessError(
            f"Runner stdout not valid JSON (exit={proc.returncode}, wall={wall:.1f}s): {e}\n"
            f"stdout head: {stdout[:300]}\n"
            f"stderr head: {stderr[:300]}"
        ) from e

    errors = result.get("errors") or []
    if proc.returncode not in (0, 1):
        # 1 = runner reported errors but produced partial result; tolerate
        raise MummichogSubprocessError(
            f"Runner exit {proc.returncode}. Errors: {errors[:3]}. "
            f"stderr: {stderr[:300]}"
        )

    result["wall_time_sec"] = wall
    result["tool_version"] = "mummichog-2.7.0"
    result["parameters"] = {
        "mode": mode, "ref_db": ref_db, "permutations": permutations,
        "instrument_ppm": instrument_ppm,
        "force_primary_ion": force_primary_ion,
    }
    return result
