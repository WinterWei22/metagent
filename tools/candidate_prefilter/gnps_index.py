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
from typing import Iterator

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
    ion_mode: str                    # "positive" | "negative" — drives mode-aware queries


def inchikey_first_block(inchikey: str | None) -> str | None:
    """Return the connectivity-only (first 14-char) block of an InChIKey.

    Cross-pool `has_reference_spectrum` stamping must match on the first
    block, not the full InChIKey: same compound can have different stereo
    assignments across HMDB / PubChem / GNPS (alpha vs beta sugars, racemic
    vs enantiopure, etc.) yielding different middle blocks but identical
    connectivity. MS/MS cannot distinguish stereoisomers, so first-block
    matching is the correct semantic for candidate pool cross-referencing.
    PubChemLite itself uses this principle (collapses CIDs by FirstBlock).

    Returns None if the input is None or empty; otherwise the leading
    segment before the first dash. Accepts already-first-block strings too.
    """
    if not inchikey:
        return None
    return inchikey.split("-", 1)[0]


_SUPPORTED_MODES: tuple[str, ...] = ("positive", "negative")


class GnpsIndex:
    """Mass-sorted, mode-partitioned index over GNPS records.

    GNPS contains both positive- and negative-mode reference spectra. Track B
    (library_search) cannot meaningfully score a query of one mode against a
    reference of the other mode, so this index keeps separate per-mode
    indices. Mass queries (search) and `has_reference_spectrum` cross-stamping
    (inchikey_set_for) are mode-aware: callers pass the query's ion mode
    and only same-mode GNPS data is consulted.

    Records with unknown / empty ion_mode are dropped at construction (no
    way to know which mode they'd answer for).
    """

    def __init__(self, records: list[GnpsIndexRecord]):
        # Drop records with unknown ion_mode upfront — they can't answer any
        # mode-specific query, so they're dead weight.
        usable = [r for r in records if r.ion_mode in _SUPPORTED_MODES]

        # Per-mode mass-sorted lists. We materialise both even if one mode is
        # empty so callers don't have to guard.
        self._records_by_mode: dict[str, list[GnpsIndexRecord]] = {
            mode: sorted(
                (r for r in usable if r.ion_mode == mode),
                key=lambda r: r.exact_mass,
            )
            for mode in _SUPPORTED_MODES
        }
        self._masses_by_mode: dict[str, list[float]] = {
            mode: [r.exact_mass for r in self._records_by_mode[mode]]
            for mode in _SUPPORTED_MODES
        }

        # First-block sets per mode: see inchikey_first_block() for why we
        # match on the first 14 chars rather than the full InChIKey.
        self._inchikey_first_block_set_by_mode: dict[str, frozenset[str]] = {
            mode: frozenset(
                b for b in (
                    inchikey_first_block(r.inchikey)
                    for r in self._records_by_mode[mode]
                ) if b
            )
            for mode in _SUPPORTED_MODES
        }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return sum(len(v) for v in self._records_by_mode.values())

    def count_for(self, mode: str) -> int:
        """Number of records in the given mode (0 if unknown mode)."""
        return len(self._records_by_mode.get(mode, []))

    def inchikey_set_for(self, mode: str) -> frozenset[str]:
        """Connectivity-only (first 14-char) InChIKey blocks of GNPS records
        in the given ion mode.

        Used by candidate_prefilter to set `has_reference_spectrum=True` on
        candidates from other pools whose structure shares connectivity with
        a same-mode GNPS entry. Returns an empty set for unknown modes.
        """
        return self._inchikey_first_block_set_by_mode.get(mode, frozenset())

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def search(
        self,
        neutral_mass: float,
        tolerance_ppm: float,
        ion_mode: str,
        formula: str | None = None,
    ) -> list[PrefilteredCandidate]:
        """Return GNPS candidates in `ion_mode` whose exact mass is within
        tolerance of `neutral_mass`. If `formula` is given, also filter by
        exact formula string match.

        Mode is REQUIRED — there is no sensible "any mode" answer because the
        downstream library_search cannot bridge modes anyway.

        Candidates are returned with `source_pool="gnps"`,
        `has_reference_spectrum=True` (every GNPS record has a spectrum, and
        we already filtered to the caller's mode). `source_id` is the
        CCMSLIB accession. mass_error_ppm is the absolute ppm deviation.
        """
        if neutral_mass <= 0:
            return []
        if ion_mode not in _SUPPORTED_MODES:
            return []

        records = self._records_by_mode[ion_mode]
        masses = self._masses_by_mode[ion_mode]
        if not records:
            return []

        abs_tol = tolerance_ppm * 1e-6 * neutral_mass
        lo, hi = neutral_mass - abs_tol, neutral_mass + abs_tol

        from bisect import bisect_left, bisect_right

        i = bisect_left(masses, lo)
        j = bisect_right(masses, hi)

        out: list[PrefilteredCandidate] = []
        for rec in records[i:j]:
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
    if SMILES can't be parsed / mass can't be computed / ion_mode is unknown.

    RDKit import is local so this module stays importable without RDKit
    installed (the tool raises at query time instead).
    """
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors

    if not record.smiles:
        return None
    if record.ion_mode not in _SUPPORTED_MODES:
        # GnpsRecord.ion_mode is already normalised to "positive"/"negative"/None
        # by common.gnps_loader. Unknown mode → drop (can't answer mode-specific
        # has_reference_spectrum questions).
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
        ion_mode=record.ion_mode,
    )


def build_index_from_path(path: str | Path) -> GnpsIndex:
    """Load the v0-usable GNPS subset from `path`, build and return an index.

    Dispatches on file extension:
      - .json → common.gnps_loader.load_v0_usable (GNPS2 ALL_GNPS_NO_PROPOGATED dump)
      - .csv  → _parse_gnps_csv (GNPS2 ALL_GNPS_cleaned_enriched dump)

    Both paths apply the same v0 filter: positive ion mode, soft ionisation,
    valid RDKit-parseable SMILES. Records whose SMILES RDKit can't parse are
    dropped with a debug log.
    """
    path = Path(path)
    ext = path.suffix.lower()

    if ext == ".json":
        from common.gnps_loader import load_v0_usable

        records = load_v0_usable(path)
        indexed: list[GnpsIndexRecord] = []
        for rec in records:
            ir = _index_record_from_gnps(rec)
            if ir is not None:
                indexed.append(ir)
        logger.info(
            "GnpsIndex: %d indexed records out of %d usable (from %s)",
            len(indexed), len(records), path.name,
        )
        return GnpsIndex(indexed)

    if ext == ".csv":
        indexed = list(_parse_gnps_csv(path))
        logger.info("GnpsIndex: %d indexed records (from %s)", len(indexed), path.name)
        return GnpsIndex(indexed)

    raise ValueError(
        f"Unsupported GNPS file extension {ext!r} at {path}. "
        f"Expected .json (ALL_GNPS_NO_PROPOGATED dump) or .csv "
        f"(ALL_GNPS_cleaned_enriched dump)."
    )


# ---------------------------------------------------------------------------
# CSV path — GNPS2 "ALL_GNPS_cleaned_enriched.csv" format
# ---------------------------------------------------------------------------
#
# Source: https://external.gnps2.org/gnpslibrary — the enriched-CSV alternative
# to ALL_GNPS_NO_PROPOGATED.json. The CSV omits peak data (peaks live in the
# companion .mgf file used by library_search) but keeps every field we need
# for candidate_prefilter's structural index: spectrum_id, Smiles,
# InChIKey_smiles, Precursor_MZ, ExactMass, Ion_Mode, Adduct, msIonisation.
#
# Column header observed 2026-04:
#   scan, spectrum_id, collision_energy, Adduct, Compound_Source,
#   Compound_Name, Precursor_MZ, ExactMass, Charge, Ion_Mode, Smiles, INCHI,
#   InChIKey_smiles, msManufacturer, msMassAnalyzer, msIonisation,
#   msDissociationMethod, GNPS_library_membership, ppmBetweenExpAndThMass,
#   classyfire_*, np_classifier_nplikeness

_CSV_REJECT_IONISATION = {"MALDI", "EI", "GC", "APCI-MALDI"}


def _parse_gnps_csv(csv_path: str | Path) -> Iterator[GnpsIndexRecord]:
    """Yield GnpsIndexRecords from a GNPS2 enriched CSV.

    Filters:
      - Ion_Mode in {"positive", "negative"} (unknown / empty → reject)
      - msIonisation is soft (not MALDI / EI / GC)
      - SMILES parses in RDKit

    Both positive and negative modes are kept; the GnpsIndex partitions
    them so mode-aware queries (search / inchikey_set_for) only see the
    relevant slice.

    For each kept row, (molecular_formula, exact_mass, inchikey) are all
    recomputed via RDKit so values are canonical and consistent with what
    pubchem_lite rows produce. CSV-provided ExactMass and InChIKey_smiles
    are ignored (would be near-identical but not guaranteed identical).
    """
    import csv
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors

    path = Path(csv_path)
    n_seen = 0
    n_kept = {"positive": 0, "negative": 0}
    n_rejected_mode = 0
    n_rejected_ionisation = 0
    n_rejected_smiles = 0

    # The CSV has long INCHI strings; bump field size limit.
    csv.field_size_limit(10_000_000)

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            n_seen += 1

            ion_mode = (row.get("Ion_Mode") or "").strip().lower()
            if ion_mode not in _SUPPORTED_MODES:
                n_rejected_mode += 1
                continue

            ms_ion = (row.get("msIonisation") or "").strip().upper()
            if ms_ion in _CSV_REJECT_IONISATION:
                n_rejected_ionisation += 1
                continue

            smiles = (row.get("Smiles") or "").strip()
            if not smiles:
                n_rejected_smiles += 1
                continue

            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                n_rejected_smiles += 1
                continue

            try:
                exact_mass = float(Descriptors.ExactMolWt(mol))
                formula = rdMolDescriptors.CalcMolFormula(mol)
                inchikey = Chem.MolToInchiKey(mol) or None
            except Exception as e:
                logger.debug("RDKit failed on SMILES %r: %s", smiles, e)
                n_rejected_smiles += 1
                continue

            if exact_mass <= 0:
                n_rejected_smiles += 1
                continue

            compound_name = (row.get("Compound_Name") or "").strip() or None
            spectrum_id = (row.get("spectrum_id") or "").strip()

            n_kept[ion_mode] += 1
            yield GnpsIndexRecord(
                spectrum_id=spectrum_id,
                compound_name=compound_name,
                smiles=smiles,
                inchikey=inchikey,
                molecular_formula=formula,
                exact_mass=exact_mass,
                ion_mode=ion_mode,
            )

    logger.info(
        "GNPS CSV parse: %d rows; kept_positive=%d, kept_negative=%d, "
        "rejected_ion_mode=%d, rejected_ionisation=%d, rejected_smiles=%d",
        n_seen, n_kept["positive"], n_kept["negative"],
        n_rejected_mode, n_rejected_ionisation, n_rejected_smiles,
    )


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
