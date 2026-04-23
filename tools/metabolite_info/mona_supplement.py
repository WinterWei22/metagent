"""Optional MoNA-HMDB metadata supplement for fetch_metabolite_info.

MoNA-export-HMDB.json is a ~54 MB dump curated by the Fiehn lab that carries
compound-level metadata (SMILES, InChIKey, molecular formula, exact mass,
chemical class) for ~7400 HMDB compounds. For our purposes it is a pure
metadata source — we do NOT surface its spectrum fields — so it fills gaps
when the local HMDB SQLite is either incomplete or not available.

The loader in common/mona_loader.py yields one record per MS/MS entry in
the dump, and the dump has many spectra per compound. We collapse these
into one record per HMDB ID, keeping the first non-None field we see per
compound (which in practice is consistent across entries for that HMDB ID).

The cache is populated lazily on first use and keyed by file path, so swapping
METAGENT_MONA_PATH between tests (or processes) rebuilds cleanly.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MONA_ENV_VAR = "METAGENT_MONA_PATH"


@dataclass
class MonaCompound:
    """Compound-level rollup of all MoNA records for one HMDB ID.

    Every field is either a value we observed in the dump or None. The empty
    string is never substituted for None — absence is absence.
    """

    hmdb_id: str
    primary_name: str | None
    smiles: str | None
    inchikey: str | None
    molecular_formula: str | None
    exact_mass: float | None


# Cache: path -> dict[hmdb_id -> MonaCompound]
_CACHE: dict[str, dict[str, MonaCompound]] = {}


def resolve_mona_path(explicit: str | os.PathLike | None = None) -> Path | None:
    if explicit is not None:
        p = Path(explicit)
        return p if p.exists() else None
    env = os.environ.get(MONA_ENV_VAR)
    if not env:
        return None
    p = Path(env)
    return p if p.exists() else None


def _build_index(path: str | os.PathLike) -> dict[str, MonaCompound]:
    """Stream the MoNA dump once and collapse into HMDB-keyed compound rows."""
    from common.mona_loader import iter_records

    index: dict[str, MonaCompound] = {}
    for rec in iter_records(path):
        if not rec.hmdb_id:
            continue
        existing = index.get(rec.hmdb_id)
        if existing is None:
            index[rec.hmdb_id] = MonaCompound(
                hmdb_id=rec.hmdb_id,
                primary_name=rec.compound_name,
                smiles=rec.smiles,
                inchikey=rec.inchikey,
                molecular_formula=rec.molecular_formula,
                exact_mass=rec.exact_mass,
            )
        else:
            # Fill-in-only merge: never overwrite a previously-seen value.
            # MoNA entries for the same HMDB ID sometimes carry partial
            # metadata (e.g. one entry missing SMILES, another providing it).
            if existing.primary_name is None:
                existing.primary_name = rec.compound_name
            if existing.smiles is None:
                existing.smiles = rec.smiles
            if existing.inchikey is None:
                existing.inchikey = rec.inchikey
            if existing.molecular_formula is None:
                existing.molecular_formula = rec.molecular_formula
            if existing.exact_mass is None:
                existing.exact_mass = rec.exact_mass
    logger.info("MoNA supplement: indexed %d HMDB compounds from %s", len(index), path)
    return index


def get_index(path: str | os.PathLike | None = None) -> dict[str, MonaCompound] | None:
    """Return the HMDB-keyed compound index, or None if MoNA is unavailable.

    Lazily loads and caches; subsequent calls with the same resolved path
    skip the ~54 MB parse.
    """
    resolved = resolve_mona_path(path)
    if resolved is None:
        return None
    key = str(resolved.resolve())
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    index = _build_index(resolved)
    _CACHE[key] = index
    return index


def lookup_by_hmdb(
    hmdb_id: str,
    *,
    path: str | os.PathLike | None = None,
) -> MonaCompound | None:
    from tools.metabolite_info.id_detect import normalise_hmdb

    index = get_index(path)
    if index is None:
        return None
    return index.get(normalise_hmdb(hmdb_id.strip()))


def lookup_by_inchikey(
    inchikey: str,
    *,
    path: str | os.PathLike | None = None,
) -> MonaCompound | None:
    index = get_index(path)
    if index is None:
        return None
    needle = inchikey.strip()
    for row in index.values():
        if row.inchikey == needle:
            return row
    return None


def clear_cache() -> None:
    """Drop the in-memory index. Intended for tests."""
    _CACHE.clear()
