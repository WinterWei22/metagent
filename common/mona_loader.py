"""MoNA JSON export loader — now repositioned as a compound-metadata source.

Originally intended for library_search, but the MoNA-export-HMDB.json dump turned
out to contain primarily GC-EI historical spectra with no precursor m/z or
adduct fields, making it unusable for LC-MS/MS library matching. The primary
spectrum library for library_search is GNPS — see common/gnps_loader.py.

This loader is retained because the MoNA-HMDB dump still has high-quality
*compound-level* metadata (SMILES, InChIKey, HMDB ID, molecular formula, exact
mass, chemical classification) that can supplement fetch_metabolite_info for
~7400 HMDB compounds. Track C (fetch_metabolite_info) MAY import from here.

The filter helpers (is_lcms_positive, has_mssms_essentials) are kept in case
a future MoNA LC-MS/MS dump becomes available, but are not used by any v0 tool.

Quirks preserved for documentation:

1. Each record's `spectrum` field is a SPACE-SEPARATED STRING of "mz:intensity"
   pairs. Example: "65.0:1.38 67.0:1.09 ..."

2. Intensities are on a 0-100 scale.

3. Metadata is a list of {name, value} dicts, NOT a flat dict.

4. Compound info is under `compound[0]` — a list, not a dict.

5. Record IDs follow "HMDB<id>_c_ms_<n>" (GC-MS / chemical ionization) or
   "HMDB<id>_ms_ms_<n>" (MS/MS).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class MonaRecord:
    """A parsed MoNA record with its most useful fields flattened.

    Kept as a plain dataclass rather than a Pydantic model so that records with
    missing/malformed fields can still be inspected for debugging. Convert to
    a schemas.Spectrum only when you're confident the record is usable.
    """

    record_id: str
    # Compound info
    compound_name: str | None
    smiles: str | None
    inchi: str | None
    inchikey: str | None
    hmdb_id: str | None
    molecular_formula: str | None
    exact_mass: float | None
    # Experimental conditions
    instrument: str | None
    instrument_type: str | None
    ionization_mode: str | None  # 'positive' | 'negative' | other
    chromatography_type: str | None  # 'LC' | 'GC' | None
    precursor_mz: float | None
    precursor_type: str | None  # aka adduct, e.g. '[M+H]+'
    collision_energy: float | None
    # Spectrum
    peaks: list[tuple[float, float]]
    # Library
    library: str | None

    @property
    def is_lcms_positive(self) -> bool:
        """True iff this record is LC-MS with positive ionization, suitable for v0."""
        if not self.chromatography_type:
            return False
        if "lc" not in self.chromatography_type.lower():
            return False
        if self.ionization_mode is None:
            return False
        if "positive" not in self.ionization_mode.lower():
            return False
        if self.instrument_type and "ei" in self.instrument_type.lower():
            return False
        return True

    @property
    def has_mssms_essentials(self) -> bool:
        """True iff the record has the fields needed for library search:
        precursor m/z, peaks, and either SMILES or InChIKey."""
        return (
            self.precursor_mz is not None
            and len(self.peaks) >= 3
            and (self.smiles is not None or self.inchikey is not None)
        )


# ---------------------------------------------------------------------------
# Metadata accessors
# ---------------------------------------------------------------------------


def _md_lookup(metadata_list: list[dict], name: str) -> str | None:
    """Find a value by metaData name (case-insensitive). Returns None if absent."""
    if not metadata_list:
        return None
    name_lower = name.lower()
    for md in metadata_list:
        if md.get("name", "").lower() == name_lower:
            value = md.get("value")
            return str(value) if value is not None else None
    return None


def _parse_float(value: str | None) -> float | None:
    """Parse a MoNA numeric value. Handles '20', '20 eV', 'NCE 30', '181.0707 m/z', etc."""
    if value is None:
        return None
    value = value.strip()
    # Try direct parse first
    try:
        return float(value)
    except ValueError:
        pass
    # Extract leading numeric token
    import re

    m = re.match(r"[-+]?(\d+\.?\d*|\.\d+)", value)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Spectrum parsing
# ---------------------------------------------------------------------------


def parse_spectrum_string(spec_str: str) -> list[tuple[float, float]]:
    """Parse MoNA's space-delimited 'mz:intensity mz:intensity ...' format.

    Returns peaks as-is (no normalisation). Intensities are on MoNA's original
    0-100 scale. Use spectrum_preprocess to normalise before use.
    """
    if not spec_str:
        return []
    peaks: list[tuple[float, float]] = []
    for token in spec_str.split():
        if ":" not in token:
            continue
        mz_s, int_s = token.split(":", 1)
        try:
            mz = float(mz_s)
            intensity = float(int_s)
        except ValueError:
            continue
        if mz > 0 and intensity > 0:
            peaks.append((mz, intensity))
    peaks.sort(key=lambda p: p[0])
    return peaks


# ---------------------------------------------------------------------------
# Record parsing
# ---------------------------------------------------------------------------


def _extract_hmdb_id(record_id: str) -> str | None:
    """Pull the HMDB prefix out of a MoNA record ID like 'HMDB0240266_c_ms_102595'."""
    if not record_id or not record_id.startswith("HMDB"):
        return None
    head = record_id.split("_", 1)[0]
    # Sanity: HMDB IDs are HMDB + 7 digits (padded from older 5-digit format)
    if len(head) < 5:
        return None
    return head


def parse_record(raw: dict) -> MonaRecord:
    """Convert one raw MoNA JSON record into a flattened MonaRecord."""
    # Compound info (take first compound)
    compounds = raw.get("compound") or []
    compound = compounds[0] if compounds else {}

    names = compound.get("names") or []
    compound_name = names[0].get("name") if names else None

    compound_md = compound.get("metaData") or []
    smiles = _md_lookup(compound_md, "SMILES")
    formula = _md_lookup(compound_md, "molecular formula")
    exact_mass = _parse_float(_md_lookup(compound_md, "total exact mass"))

    # Spectrum-level metadata
    spec_md = raw.get("metaData") or []
    ion_mode = _md_lookup(spec_md, "ionization mode")
    instr = _md_lookup(spec_md, "instrument")
    instr_type = _md_lookup(spec_md, "instrument type")
    chrom = _md_lookup(spec_md, "chromatography type")
    precursor_mz = _parse_float(_md_lookup(spec_md, "precursor m/z"))
    precursor_type = _md_lookup(spec_md, "precursor type")
    collision_energy = _parse_float(_md_lookup(spec_md, "collision energy"))

    # Peaks
    spec_str = raw.get("spectrum", "")
    peaks = parse_spectrum_string(spec_str)

    # Library
    library = (raw.get("library") or {}).get("library")

    record_id = raw.get("id", "")
    hmdb_id = _extract_hmdb_id(record_id)

    return MonaRecord(
        record_id=record_id,
        compound_name=compound_name,
        smiles=smiles,
        inchi=compound.get("inchi"),
        inchikey=compound.get("inchiKey"),
        hmdb_id=hmdb_id,
        molecular_formula=formula,
        exact_mass=exact_mass,
        instrument=instr,
        instrument_type=instr_type,
        ionization_mode=ion_mode,
        chromatography_type=chrom,
        precursor_mz=precursor_mz,
        precursor_type=precursor_type,
        collision_energy=collision_energy,
        peaks=peaks,
        library=library,
    )


# ---------------------------------------------------------------------------
# Top-level loaders
# ---------------------------------------------------------------------------


def iter_records(path: str | Path) -> Iterator[MonaRecord]:
    """Yield parsed MonaRecords from a MoNA JSON export, one at a time.

    Reads the full file into memory — the MoNA-export-HMDB.json dump is ~54MB
    and well within comfortable range. For larger dumps, rewrite with ijson.
    """
    with open(path) as f:
        raw_list = json.load(f)
    for raw in raw_list:
        try:
            yield parse_record(raw)
        except Exception as e:
            rid = raw.get("id", "<unknown>")
            logger.warning("Failed to parse MoNA record %s: %s", rid, e)
            continue


def load_lcms_positive(path: str | Path) -> list[MonaRecord]:
    """Convenience: load all LC-MS positive records with usable MS/MS essentials.

    This is the default slice for v0. Returns records filtered by:
    - chromatography type contains 'LC'
    - ionization mode is positive
    - instrument type is not EI
    - has precursor m/z, at least 3 peaks, and SMILES or InChIKey
    """
    kept: list[MonaRecord] = []
    seen = 0
    for rec in iter_records(path):
        seen += 1
        if rec.is_lcms_positive and rec.has_mssms_essentials:
            kept.append(rec)
    logger.info("MoNA: loaded %d LC-MS positive records out of %d total", len(kept), seen)
    return kept


def normalise_peaks(peaks: list[tuple[float, float]]) -> tuple[list[float], list[float]]:
    """Normalise peaks so base peak intensity is 1.0. Returns (mz_list, intensity_list).

    Raises ValueError if peaks is empty or all intensities are non-positive.
    """
    if not peaks:
        raise ValueError("Cannot normalise empty peak list.")
    max_int = max(p[1] for p in peaks)
    if max_int <= 0:
        raise ValueError("All peak intensities are non-positive.")
    mz_list = [p[0] for p in peaks]
    int_list = [p[1] / max_int for p in peaks]
    return mz_list, int_list
