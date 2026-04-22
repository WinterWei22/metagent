"""In-house ms-clip retriever wrapper.

The model's real entry point is a Hydra-driven batch CLI at
``ms_clip.inference.predict_smi`` in the ``ms-pred`` repo. Per maintainer, it
only consumes ``raw_spec`` (m/z + intensity) and ``prec_mz`` from the JSON
input — MAGMa DAG structure is not required.

Isolation strategy: shell out via ``conda run -n diffms python -m ...`` so
ms-clip's torch / lightning / DGL deps never touch the orchestrator env. Same
pattern as Track C's ``MSBartGenerator``.

Test strategy: the ``InHouseRetriever`` ``Protocol`` lets tests inject a
``MockInHouseRetriever`` so ``library_search`` can be validated with zero
torch installation.
"""
from __future__ import annotations

import json
import logging
import os
import pickle
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tools.library_search.errors import InHouseModelError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

DEFAULT_CKPT_ENV = "METAGENT_MSCLIP_CKPT"
DEFAULT_CKPT_PATH = (
    "/data/weiwentao/reconstruct/ms-clip/results/"
    "chemformer_v4_large_ep3unfroze_20260420_235720/version_0/best.ckpt"
)
DEFAULT_MSCLIP_REPO = os.environ.get(
    "METAGENT_MSCLIP_REPO", "/home/weiwentao/workspace/reconstruct/ms-pred"
)
DEFAULT_CONDA_ENV = os.environ.get("METAGENT_MSCLIP_ENV", "diffms")
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("METAGENT_MSCLIP_TIMEOUT", "1800"))


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InHouseScore:
    """One raw in-house prediction, before calibration."""

    smiles: str
    raw_global_sim: float  # native ms-clip output in [-1, 1]


class InHouseRetriever(Protocol):
    """Abstract interface for the in-house retrieval model.

    Implementations: ``MSClipRetriever`` (real, shells out to the conda env)
    and ``MockInHouseRetriever`` (tests, deterministic).
    """

    def score_candidates(
        self,
        *,
        query_mz: list[float],
        query_intensity: list[float],
        query_precursor_mz: float,
        adduct: str,
        candidate_smiles: list[str],
    ) -> list[InHouseScore]:
        """Return one ``InHouseScore`` per input SMILES, in the SAME ORDER.

        When the model cannot score a given SMILES (e.g. it fails to parse),
        implementations must still return a placeholder ``InHouseScore`` with
        ``raw_global_sim = -1.0`` so downstream fusion sees a usable slot.
        """
        ...


# ---------------------------------------------------------------------------
# Real adapter: ms-clip via subprocess
# ---------------------------------------------------------------------------


def _resolve_ckpt_path() -> str:
    ckpt = os.environ.get(DEFAULT_CKPT_ENV, DEFAULT_CKPT_PATH)
    if not ckpt:
        raise InHouseModelError("ms-clip checkpoint path is empty")
    return ckpt


class MSClipRetriever:
    """Real ``InHouseRetriever`` backed by the ms-clip ``predict_smi`` CLI.

    Each call stages inputs in a tmpdir (one spec JSON, one TSV of candidates),
    invokes the CLI via ``conda run``, and parses the emitted pickle. The conda
    env is ``diffms`` by default (overridable via ``METAGENT_MSCLIP_ENV``).

    On any subprocess / parse failure we raise ``InHouseModelError``. The
    orchestrator (or the tool's fusion layer) is expected to downgrade to
    modified-cosine-only rather than surface the error to the user.
    """

    def __init__(
        self,
        *,
        checkpoint: str | None = None,
        conda_env: str = DEFAULT_CONDA_ENV,
        repo_root: str = DEFAULT_MSCLIP_REPO,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        batch_size: int = 128,
        num_workers: int = 4,
    ):
        self.checkpoint = checkpoint or _resolve_ckpt_path()
        self.conda_env = conda_env
        self.repo_root = repo_root
        self.timeout_seconds = timeout_seconds
        self.batch_size = batch_size
        self.num_workers = num_workers

    def score_candidates(
        self,
        *,
        query_mz: list[float],
        query_intensity: list[float],
        query_precursor_mz: float,
        adduct: str,
        candidate_smiles: list[str],
    ) -> list[InHouseScore]:
        if not candidate_smiles:
            return []

        canonical_adduct = _canonicalise_adduct_for_msclip(adduct)
        if canonical_adduct is None:
            raise InHouseModelError(
                f"Adduct {adduct!r} is not in the ms-clip MSG ion vocabulary",
                recoverable=True,
            )

        spec_name = f"metagent_query_{uuid.uuid4().hex[:10]}"
        with tempfile.TemporaryDirectory(prefix="metagent_msclip_") as td:
            workdir = Path(td)
            magma_folder = workdir / "magma"
            magma_folder.mkdir()
            data_dir = workdir / "data_dir"
            data_dir.mkdir()
            save_dir = workdir / "save"
            save_dir.mkdir()

            # 1. Write the spec JSON (only raw_spec + prec_mz are read by the
            #    CLIPSmiDataset; the rest of the MAGMa tree fields are unused).
            spec_json = {
                "raw_spec": [
                    [float(mz), float(it)]
                    for mz, it in zip(query_mz, query_intensity)
                ],
                "prec_mz": float(query_precursor_mz),
            }
            (magma_folder / f"pred_{spec_name}.json").write_text(json.dumps(spec_json))

            # 2. Write the TSV of (spec, smiles, ionization, label) rows.
            labels_file = "candidates.tsv"
            with open(data_dir / labels_file, "w") as f:
                f.write("spec\tsmiles\tionization\tlabel\n")
                for smi in candidate_smiles:
                    f.write(f"{spec_name}\t{smi}\t{canonical_adduct}\tFalse\n")

            # 3. Shell out to predict_smi.
            env = os.environ.copy()
            env["HYDRA_FULL_ERROR"] = "1"
            cmd = [
                "conda", "run", "-n", self.conda_env, "--no-capture-output",
                "python", "-m", "ms_clip.inference.predict_smi",
                f"inference.checkpoint={self.checkpoint}",
                f"inference.save_dir={save_dir}",
                f"inference.batch_size={self.batch_size}",
                f"inference.num_workers={self.num_workers}",
                f"data.data_dir={data_dir}",
                f"data.labels_file={labels_file}",
                f"data.magma_dag_folder={magma_folder}",
                f"hydra.run.dir={save_dir}",
            ]
            logger.info("ms-clip: launching predict_smi (n_candidates=%d)", len(candidate_smiles))
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=self.repo_root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise InHouseModelError(
                    f"ms-clip subprocess timed out after {self.timeout_seconds}s"
                ) from exc
            if proc.returncode != 0:
                raise InHouseModelError(
                    f"ms-clip subprocess failed (exit {proc.returncode}): "
                    f"{proc.stderr[-2000:]}"
                )

            # 4. Parse the emitted pickle.
            out_pkl = save_dir / f"{labels_file}.pkl"
            if not out_pkl.exists():
                raise InHouseModelError(
                    f"ms-clip did not produce expected pickle at {out_pkl}"
                )
            try:
                with open(out_pkl, "rb") as f:
                    payload = pickle.load(f)
            except Exception as exc:
                raise InHouseModelError(f"failed to load ms-clip pickle: {exc}") from exc

        return _align_scores_by_smiles(payload, candidate_smiles)


def _canonicalise_adduct_for_msclip(adduct: str) -> str | None:
    """Route the incoming adduct through ``ms_clip.common.ions.standardize_adduct``.

    Returns the canonical MSG ion string, or None when the adduct is outside
    the model's vocabulary (caller should skip the ms-clip pass for that query).
    """
    try:
        from ms_clip.common.ions import standardize_adduct
    except Exception as exc:
        logger.debug("ms_clip.common.ions unavailable: %s", exc)
        return None
    try:
        return standardize_adduct(adduct)
    except Exception:
        return None


def _align_scores_by_smiles(
    payload: dict, candidate_smiles: list[str]
) -> list[InHouseScore]:
    """Re-order the pickle's ``cosine_similarity`` rows to match the input SMILES.

    ``predict_smi`` preserves order, but rows can be silently dropped when a
    sample fails (``CLIPSmiDataset.__getitem__`` returns ``None``). We key on
    SMILES so a dropped candidate still gets a sentinel score.
    """
    out_smiles = payload.get("smiles") or []
    cos_sim = payload.get("cosine_similarity")
    if cos_sim is None:
        raise InHouseModelError("ms-clip pickle missing 'cosine_similarity' field")

    scored: dict[str, float] = {}
    for smi, val in zip(out_smiles, _flatten_similarity(cos_sim)):
        if smi not in scored:  # first occurrence wins
            scored[smi] = float(val)

    result: list[InHouseScore] = []
    for smi in candidate_smiles:
        if smi in scored:
            result.append(InHouseScore(smiles=smi, raw_global_sim=scored[smi]))
        else:
            logger.warning("ms-clip dropped SMILES %s; emitting sentinel -1.0", smi)
            result.append(InHouseScore(smiles=smi, raw_global_sim=-1.0))
    return result


def _flatten_similarity(sim) -> list[float]:
    """Flatten a (N, 1) numpy array (or list) into a 1-D Python list."""
    try:
        import numpy as np

        arr = np.asarray(sim).reshape(-1)
        return arr.astype(float).tolist()
    except Exception:
        return [float(x) for x in sim]


# ---------------------------------------------------------------------------
# Mock retriever for tests
# ---------------------------------------------------------------------------


class MockInHouseRetriever:
    """Deterministic test retriever.

    By default every SMILES receives ``raw_global_sim=0.0``. Tests can pass a
    ``smiles_to_score`` dict to pin specific candidates high / low, which is
    the mechanism used to verify that ``library_search`` ranks correctly.
    """

    def __init__(self, smiles_to_score: dict[str, float] | None = None, default: float = 0.0):
        self.smiles_to_score = dict(smiles_to_score or {})
        self.default = default
        self.calls: list[dict] = []  # capture args for test assertions

    def score_candidates(
        self,
        *,
        query_mz: list[float],
        query_intensity: list[float],
        query_precursor_mz: float,
        adduct: str,
        candidate_smiles: list[str],
    ) -> list[InHouseScore]:
        self.calls.append(
            {
                "query_mz": list(query_mz),
                "query_intensity": list(query_intensity),
                "query_precursor_mz": float(query_precursor_mz),
                "adduct": adduct,
                "candidate_smiles": list(candidate_smiles),
            }
        )
        return [
            InHouseScore(smiles=smi, raw_global_sim=self.smiles_to_score.get(smi, self.default))
            for smi in candidate_smiles
        ]
