"""In-memory mass index over GNPS library records.

Loads the v0-usable subset of GNPS once (via common.gnps_loader), computes each
record's neutral exact mass + molecular formula from SMILES via RDKit, and
serves mass-window queries in under a millisecond per query.

Two roles:
  1. Contributes candidates to the "gnps" sub-pool of candidate_prefilter.
  2. Supplies a set of InChIKeys used to stamp has_reference_spectrum=True
     on candidates from OTHER pools (e.g. pubchem_lite / HMDB) whose structure
     has a reference spectrum available.

Module-level singleton pattern mirrors common.llm_client.set_mock: tests call
`set_default_index()` to inject a small hand-built index; production code
calls `get_default_index()` which lazily loads from METAGENT_GNPS_PATH.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from schemas.common import PrefilteredCandidate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GnpsIndexRecord:
    """One row in the in-memory GNPS index.

    Frozen so it's hashable and cheap to copy into candidate objects. Holds
    only the fields candidate_prefilter needs — the full MS/MS peak list
    stays inside common.gnps_loader's GnpsRecord, which library_search uses
    but prefilter does not.
    """

    spectrum_id: str                 # GNPS CCMSLIB ID — goes into source_id
    compound_name: str | None
    smiles: str
    inchikey: str | None             # canonical InChIKey if RDKit could compute one
    molecular_formula: str           # canonical Hill form from RDKit
    exact_mass: float                # neutral monoisotopic mass in Da


class GnpsIndex:
    """Mass-sorted index over GNPS records for fast window queries.

    Internally stores records in a list sorted by exact_mass ascending; mass
    queries run in O(log n + k) via bisect. For the v0 GNPS v0-usable set
    (~100k records after filtering), linear scan would also be fine, but
    bisect is free to implement and scales.
    """

    def __init__(self, records: list[GnpsIndexRecord]):
        self._records: list[GnpsIndexRecord] = sorted(records, key=lambda r: r.exact_mass)
        self._masses: list[float] = [r.exact_mass for r in self._records]
        self._inchikey_set: frozenset[str] = frozenset(
            r.inchikey for r in self._records if r.inchikey
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    @property
    def inchikey_set(self) -> frozenset[str]:
        """InChIKeys of every GNPS record with a computable InChIKey.

        Used by candidate_prefilter to set `has_reference_spectrum=True` on
        candidates from other pools whose structure is also in GNPS.
        """
        return self._inchikey_set

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def search(
        self,
        neutral_mass: float,
        tolerance_ppm: float,
        formula: str | None = None,
    ) -> list[PrefilteredCandidate]:
        """Return GNPS candidates whose exact mass is within tolerance of
        `neutral_mass`. If `formula` is given, also filter by exact formula
        string match.

        Candidates are returned with `source_pool="gnps"`,
        `has_reference_spectrum=True` (every GNPS record by definition has
        a spectrum). `source_id` is the CCMSLIB accession. mass_error_ppm
        is the absolute ppm deviation from `neutral_mass`.
        """
        if neutral_mass <= 0:
            return []

        abs_tol = tolerance_ppm * 1e-6 * neutral_mass
        lo, hi = neutral_mass - abs_tol, neutral_mass + abs_tol

        from bisect import bisect_left, bisect_right

        i = bisect_left(self._masses, lo)
        j = bisect_right(self._masses, hi)

        out: list[PrefilteredCandidate] = []
        for rec in self._records[i:j]:
            if formula is not None and rec.molecular_formula != formula:
                continue
            ppm_err = abs(rec.exact_mass - neutral_mass) / neutral_mass * 1e6
            out.append(
                PrefilteredCandidate(
                    smiles=rec.smiles,
                    name=rec.compound_name,
                    source_pool="gnps",
                    source_id=rec.spectrum_id,
                    molecular_formula=rec.molecular_formula,
                    exact_mass=rec.exact_mass,
                    mass_error_ppm=ppm_err,
                    has_reference_spectrum=True,
                )
            )
        return out


# ---------------------------------------------------------------------------
# Building from common.gnps_loader output
# ---------------------------------------------------------------------------


def _index_record_from_gnps(record) -> GnpsIndexRecord | None:
    """Turn a common.gnps_loader.GnpsRecord into a GnpsIndexRecord, or None
    if SMILES can't be parsed / mass can't be computed.

    RDKit import is local so this module stays importable without RDKit
    installed (the tool raises at query time instead).
    """
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors

    if not record.smiles:
        return None
    mol = Chem.MolFromSmiles(record.smiles)
    if mol is None:
        return None
    try:
        exact_mass = Descriptors.ExactMolWt(mol)
        formula = rdMolDescriptors.CalcMolFormula(mol)
    except Exception as e:
        logger.debug("RDKit failed on SMILES %r: %s", record.smiles, e)
        return None
    if exact_mass <= 0:
        return None

    inchikey = record.inchikey
    if not inchikey:
        try:
            inchikey = Chem.MolToInchiKey(mol) or None
        except Exception:
            inchikey = None

    return GnpsIndexRecord(
        spectrum_id=record.spectrum_id,
        compound_name=record.compound_name,
        smiles=record.smiles,
        inchikey=inchikey,
        molecular_formula=formula,
        exact_mass=float(exact_mass),
    )


def build_index_from_path(path: str | Path) -> GnpsIndex:
    """Load the v0-usable GNPS subset from `path`, build and return an index.

    Delegates filtering to common.gnps_loader.load_v0_usable. Records whose
    SMILES RDKit can't parse are dropped with a debug log.
    """
    from common.gnps_loader import load_v0_usable

    records = load_v0_usable(path)
    indexed: list[GnpsIndexRecord] = []
    for rec in records:
        ir = _index_record_from_gnps(rec)
        if ir is not None:
            indexed.append(ir)
    logger.info("GnpsIndex: %d indexed records out of %d usable", len(indexed), len(records))
    return GnpsIndex(indexed)


# ---------------------------------------------------------------------------
# Module-level default index (lazy, overridable for tests)
# ---------------------------------------------------------------------------


_DEFAULT_INDEX: GnpsIndex | None = None


def get_default_index() -> GnpsIndex:
    """Return the cached process-wide GNPS index.

    First call reads METAGENT_GNPS_PATH and loads from disk. If the env var is
    unset or the file doesn't exist, we return an EMPTY index (instead of
    raising) so tools can still produce pubchem_lite candidates without GNPS
    — has_reference_spectrum will just be False everywhere. Emits a warning
    once so operators notice.
    """
    global _DEFAULT_INDEX
    if _DEFAULT_INDEX is not None:
        return _DEFAULT_INDEX

    path = os.environ.get("METAGENT_GNPS_PATH")
    if not path or not Path(path).exists():
        if path:
            logger.warning(
                "METAGENT_GNPS_PATH=%r does not exist; GNPS pool will be empty "
                "and has_reference_spectrum will be False everywhere.",
                path,
            )
        else:
            logger.warning(
                "METAGENT_GNPS_PATH not set; GNPS pool will be empty and "
                "has_reference_spectrum will be False everywhere."
            )
        _DEFAULT_INDEX = GnpsIndex([])
        return _DEFAULT_INDEX

    _DEFAULT_INDEX = build_index_from_path(path)
    return _DEFAULT_INDEX


def set_default_index(index: GnpsIndex | None) -> None:
    """Replace the cached default index.

    Use for test setUp/tearDown. Passing None resets back to lazy load.
    """
    global _DEFAULT_INDEX
    _DEFAULT_INDEX = index
