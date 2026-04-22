"""Shared fixtures for the day-1 end-to-end integration tests.

Responsibilities kept narrow on purpose:

- Put the repo root on sys.path once (tracks' unit tests each do this
  themselves; the integration suite does it centrally).
- Expose the three JSON fixture spectra under ``tests/fixtures/spectra/``
  as parametrised pytest fixtures with their ground-truth metadata.
- Build canonical ``PreprocessRequest`` objects from those fixtures so
  each e2e test starts from the same deterministic raw input.
- Register the skip markers used by the pipeline tests
  (``requires_gnps``, ``requires_pubchem_lite``, ``requires_inhouse_model``)
  so pytest does not complain about unknown marks.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "spectra"
_FIXTURE_NAMES = ["glucose_pos", "caffeine_pos", "lcarnitine_pos"]


@dataclass(frozen=True)
class FixtureSpectrum:
    """One parsed spectrum fixture + its ground-truth metadata.

    The JSON on disk stores peaks as ``[[mz, raw_intensity], ...]``; we
    flatten them into the two arrays ``PreprocessRequest`` expects.
    """

    name: str
    compound_name: str
    smiles: str
    inchikey: str
    hmdb_id: str
    precursor_mz: float
    adduct: str
    ionization_mode: str
    collision_energy: float | None
    raw_mz: list[float]
    raw_intensity: list[float]

    @classmethod
    def from_json(cls, path: Path) -> "FixtureSpectrum":
        data = json.loads(path.read_text())
        peaks = data["peaks"]
        return cls(
            name=path.stem,
            compound_name=data["compound_name"],
            smiles=data["smiles"],
            inchikey=data["inchikey"],
            hmdb_id=data["hmdb_id"],
            precursor_mz=float(data["precursor_mz"]),
            adduct=data["adduct"],
            ionization_mode=data["ionization_mode"],
            collision_energy=(
                float(data["collision_energy"])
                if data.get("collision_energy") is not None
                else None
            ),
            raw_mz=[float(p[0]) for p in peaks],
            raw_intensity=[float(p[1]) for p in peaks],
        )

    def to_preprocess_request(self):
        """Build a schemas.PreprocessRequest matching this fixture."""
        from schemas import PreprocessRequest

        return PreprocessRequest(
            raw_mz=self.raw_mz,
            raw_intensity=self.raw_intensity,
            precursor_mz=self.precursor_mz,
            adduct=self.adduct,
            ionization_mode=self.ionization_mode,
            collision_energy=self.collision_energy,
        )


def pytest_configure(config):
    """Register the env-gated marks so pytest does not warn."""
    for mark in ("requires_gnps", "requires_pubchem_lite", "requires_inhouse_model"):
        config.addinivalue_line(
            "markers",
            f"{mark}: integration test that requires an external resource "
            f"(env var / checkpoint). Skipped by default when the resource is absent.",
        )


@pytest.fixture(params=_FIXTURE_NAMES)
def fixture_spectrum(request) -> FixtureSpectrum:
    """Parametrised: yields each of the three fixture spectra in turn."""
    return FixtureSpectrum.from_json(_FIXTURE_DIR / f"{request.param}.json")


@pytest.fixture
def all_fixtures() -> list[FixtureSpectrum]:
    """All three fixtures as a list — used by the top-10 union assertion."""
    return [FixtureSpectrum.from_json(_FIXTURE_DIR / f"{n}.json") for n in _FIXTURE_NAMES]


@pytest.fixture
def has_gnps_env() -> bool:
    return bool(os.environ.get("METAGENT_GNPS_PATH"))


@pytest.fixture
def has_pubchem_lite_env() -> bool:
    return bool(os.environ.get("METAGENT_PUBCHEM_LITE_PATH"))


@pytest.fixture
def has_inhouse_model_env() -> bool:
    """True iff at least one of the real model checkpoints is configured."""
    return bool(os.environ.get("METAGENT_MSCLIP_CKPT")) or bool(
        os.environ.get("METAGENT_MSBART_CKPT")
    )
