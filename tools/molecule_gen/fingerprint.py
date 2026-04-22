"""Fingerprinter layer for molecule_generate.

Stage 1 of the pipeline: convert an MS/MS spectrum into a 4096-bit molecular
fingerprint (a list of "on" bit indices) that MS-BART's decoder consumes.

Implementations of the same `Fingerprinter` Protocol:

  * `SiriusFingerprinter` — shells out to SIRIUS CLI (CSI:FingerID style).
    Produces a substructure-space fingerprint that does NOT match MS-BART's
    Morgan training distribution; an adapter layer would be needed.
  * `CandidateFusionFingerprinter` — takes a list[Candidate] from an upstream
    retrieval module (e.g. Track B `library_search`), soft-votes their Morgan
    fingerprints, and (optionally) fuses with a base fingerprint per the
    training protocol in `MS-BART/preprocess/create_fused_fps.py`.
  * `GroundTruthFingerprinter` — preset fingerprint; for oracle tests and
    decoder-side bypass.
  * `MockFingerprinter` — constant output for unit tests.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Protocol

from schemas.common import Candidate, Spectrum
from tools.molecule_gen.errors import FingerprinterError


SIRIUS_BIN_ENV = "METAGENT_SIRIUS_BIN"
SIRIUS_TIMEOUT_SECONDS = int(os.environ.get("METAGENT_SIRIUS_TIMEOUT", "300"))


class Fingerprinter(Protocol):
    def predict(self, spectrum: Spectrum) -> list[int]:
        """Return the list of 'on' fingerprint bit indices for the spectrum.

        Indices follow MS-BART's vocabulary convention: a 4096-bit Morgan
        fingerprint (radius=2), tokenized as 4-digit zero-padded '<fpNNNN>'
        for positions 0..4095. Implementations that produce fingerprints in a
        different space (e.g. CSI:FingerID substructure bits) need an adapter
        to map into the Morgan space before MS-BART consumes them.
        """
        ...


# ---------------------------------------------------------------------------
# Real SIRIUS adapter
# ---------------------------------------------------------------------------


def _write_ms_file(spectrum: Spectrum, path: Path) -> None:
    """Write a minimal SIRIUS-compatible .ms file.

    SIRIUS .ms format supports multiple MS2 collision energies; for v0 we
    only ship what the Spectrum schema carries (one MS2 block, one CE).
    """
    ce = spectrum.collision_energy if spectrum.collision_energy is not None else 0.0
    lines = [
        f">compound unknown",
        f">parentmass {spectrum.precursor_mz}",
        f">ionization {spectrum.adduct}",
        f">ms2",
        f"#collision_energy {ce}",
    ]
    for mz, intensity in zip(spectrum.mz, spectrum.intensity):
        lines.append(f"{mz:.6f} {intensity:.6f}")
    path.write_text("\n".join(lines) + "\n")


class SiriusFingerprinter:
    """Shells out to SIRIUS to obtain a CSI:FingerID fingerprint.

    Requires either a `sirius` binary on PATH or `METAGENT_SIRIUS_BIN` pointing
    at one. The Docker route is documented in docker/molecule_gen.Dockerfile;
    the container bakes in SIRIUS and exposes `sirius` as its entrypoint.
    """

    def __init__(
        self,
        *,
        sirius_bin: str | None = None,
        timeout_seconds: int = SIRIUS_TIMEOUT_SECONDS,
    ):
        self.sirius_bin = sirius_bin or os.environ.get(SIRIUS_BIN_ENV, "sirius")
        self.timeout_seconds = timeout_seconds

    def predict(self, spectrum: Spectrum) -> list[int]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ms_file = tmp_path / "query.ms"
            out_dir = tmp_path / "out"
            _write_ms_file(spectrum, ms_file)
            cmd = [
                self.sirius_bin,
                "-i", str(ms_file),
                "-o", str(out_dir),
                "formula", "fingerprint",
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except FileNotFoundError as e:
                raise FingerprinterError(
                    f"SIRIUS binary not found at '{self.sirius_bin}'. "
                    f"Set {SIRIUS_BIN_ENV} or deploy docker/molecule_gen.Dockerfile."
                ) from e
            except subprocess.TimeoutExpired as e:
                raise FingerprinterError(
                    f"SIRIUS timed out after {self.timeout_seconds}s."
                ) from e
            if proc.returncode != 0:
                raise FingerprinterError(
                    f"SIRIUS failed (rc={proc.returncode}): "
                    f"{proc.stderr.strip()[-1000:]}"
                )
            return _parse_sirius_fingerprint(out_dir)


def _parse_sirius_fingerprint(out_dir: Path) -> list[int]:
    """Walk a SIRIUS output directory and collect the 'on' fingerprint bits.

    SIRIUS writes one CSV per formula candidate under
    `<out_dir>/<sample>/fingerprints/<formula>.fpt`; the top-ranked formula
    (lowest-numbered directory) is taken. The .fpt file is one probability
    per line; we threshold at 0.5 to get bit indices.
    """
    candidates: list[Path] = sorted(out_dir.rglob("fingerprints/*.fpt"))
    if not candidates:
        raise FingerprinterError(
            f"No fingerprints produced by SIRIUS under {out_dir}."
        )
    fpt = candidates[0]
    probs: list[float] = []
    for line in fpt.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            probs.append(float(line.split()[0]))
        except ValueError:
            continue
    return [i for i, p in enumerate(probs) if p >= 0.5]


# ---------------------------------------------------------------------------
# Ground-truth injection (decoder-side testing bypass)
# ---------------------------------------------------------------------------


_FP_TOKEN_RE = re.compile(r"<fp(\d+)>")

MORGAN_NBITS = 4096
MORGAN_RADIUS = 2


class GroundTruthFingerprinter:
    """Returns a preset fingerprint regardless of spectrum.

    Use this while CSI:FingerID deployment is in flight: feed MS-BART a
    deterministic Morgan fingerprint derived from the known SMILES (oracle
    test), or the `fps` column from the MassSpecGym test set (MIST-predicted
    proxy).
    """

    def __init__(self, bits: list[int]):
        self._bits = list(bits)

    @classmethod
    def from_token_string(cls, fps: str) -> "GroundTruthFingerprinter":
        """Parse a '<fp0042><fp0249>...' token string into bit indices."""
        return cls([int(m) for m in _FP_TOKEN_RE.findall(fps)])

    @classmethod
    def from_smiles(
        cls,
        smiles: str,
        *,
        n_bits: int = MORGAN_NBITS,
        radius: int = MORGAN_RADIUS,
    ) -> "GroundTruthFingerprinter":
        """Compute the Morgan fingerprint of a SMILES and use its ON bits.

        Matches MS-BART's training-time featurization
        (`AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=4096)`).
        Use this for oracle-mode smoke tests where we want to verify the
        decoder's upper-bound recovery rate.
        """
        from rdkit import Chem
        from rdkit.Chem import AllChem

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise FingerprinterError(f"Unparseable SMILES: {smiles!r}")
        bitvec = AllChem.GetMorganFingerprintAsBitVect(
            mol, radius=radius, nBits=n_bits
        )
        bits = [i for i in range(n_bits) if bitvec.GetBit(i)]
        return cls(bits)

    def predict(self, spectrum: Spectrum) -> list[int]:
        return list(self._bits)


# ---------------------------------------------------------------------------
# Retrieval-driven fusion fingerprinter
# ---------------------------------------------------------------------------


FusionStrategy = Literal[
    "retrieved_only_60",
    "retrieved_only_80",
    "topn_60",
    "topn_80",
]


def _parse_strategy(strategy: FusionStrategy) -> tuple[str, int]:
    """Split 'topn_60' -> ('topn', 60); 'retrieved_only_80' -> ('retrieved_only', 80)."""
    if strategy.startswith("retrieved_only_"):
        return "retrieved_only", int(strategy.rsplit("_", 1)[1])
    if strategy.startswith("topn_"):
        return "topn", int(strategy.rsplit("_", 1)[1])
    raise ValueError(f"Unknown fusion strategy: {strategy!r}")


class CandidateFusionFingerprinter:
    """Fuse a list of retrieval candidates into a Morgan-4096 fingerprint.

    Mirrors `MS-BART/preprocess/create_fused_fps.py` so that inference-time
    fingerprints stay within the distribution the fused-FPS checkpoints were
    trained on. Ignores the spectrum — fusion is purely over candidate
    structures and the optional `base_fingerprint`.

    Strategy semantics:
      - retrieved_only_N: take the top-N bits of the mean-voted Morgan FP
        across candidates.
      - topn_N: score[bit] = mist_weight * base_binary[bit] + retrieved_vote[bit],
        take top-N bits. If `base_fingerprint` is None, the base term is zero
        (equivalent to retrieved_only_N).

    Candidate scores are NOT used as vote weights — the training pipeline
    uses an unweighted mean, and we stay consistent to avoid distribution
    drift at inference time.
    """

    N_BITS = 4096
    RADIUS = 2

    def __init__(
        self,
        candidates: list[Candidate],
        *,
        base_fingerprint: list[int] | None = None,
        strategy: FusionStrategy = "retrieved_only_60",
        mist_weight: float = 2.0,
    ):
        if not candidates:
            raise FingerprinterError(
                "CandidateFusionFingerprinter requires at least one candidate."
            )
        self._candidates = list(candidates)
        self._base_bits = list(base_fingerprint) if base_fingerprint else []
        self._mode, self._n_bits = _parse_strategy(strategy)
        self._mist_weight = float(mist_weight)
        self._strategy = strategy

    def predict(self, spectrum: Spectrum) -> list[int]:
        import numpy as np

        retrieved_fps: list[np.ndarray] = []
        for c in self._candidates:
            fp = _morgan_bitvec(c.smiles, n_bits=self.N_BITS, radius=self.RADIUS)
            if fp is not None:
                retrieved_fps.append(fp)

        if not retrieved_fps:
            raise FingerprinterError(
                f"All {len(self._candidates)} candidate SMILES failed RDKit parsing; "
                "cannot fuse a fingerprint."
            )

        retrieved_vote = np.mean(np.stack(retrieved_fps), axis=0)

        if self._mode == "retrieved_only":
            scores = retrieved_vote
        else:  # topn
            base = np.zeros(self.N_BITS, dtype=np.float32)
            for b in self._base_bits:
                if 0 <= b < self.N_BITS:
                    base[b] = 1.0
            scores = self._mist_weight * base + retrieved_vote

        # Take top-N bits. argsort ascending; tail has the largest.
        top = np.argsort(scores)[-self._n_bits:]
        # Drop zero-score bits so we don't emit meaningless ON bits when
        # fewer than N bits carry any signal.
        top = [int(i) for i in top if scores[i] > 0]
        return sorted(top)


def _morgan_bitvec(smiles: str, *, n_bits: int, radius: int):
    """Return a float32 numpy vector of length n_bits, or None on parse fail.

    Empty or zero-atom molecules are rejected — RDKit accepts an empty string
    as a valid empty Mol, which would otherwise leak through as a useless
    all-zeros vector.
    """
    import numpy as np
    from rdkit import Chem
    from rdkit.Chem import AllChem

    if not smiles or not smiles.strip():
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    bv = AllChem.GetMorganFingerprintAsBitVect(mol, radius=radius, nBits=n_bits)
    arr = np.zeros(n_bits, dtype=np.float32)
    for i in bv.GetOnBits():
        arr[i] = 1.0
    return arr


# ---------------------------------------------------------------------------
# Unit-test mock
# ---------------------------------------------------------------------------


class MockFingerprinter:
    """Constant-output fingerprinter used by the test suite."""

    DEFAULT_BITS: list[int] = [42, 249, 389, 656, 1088, 1162, 1239, 1380]

    def __init__(self, bits: list[int] | None = None):
        self._bits = list(bits) if bits is not None else list(self.DEFAULT_BITS)

    def predict(self, spectrum: Spectrum) -> list[int]:
        return list(self._bits)
