"""GNPS JSON library loader.

Primary spectrum library source for library_search. Consumes the GNPS2
ALL_GNPS_NO_PROPOGATED matchms-cleaned JSON dump from:

    https://external.gnps2.org/gnpslibrary

Set METAGENT_GNPS_PATH=/path/to/ALL_GNPS_NO_PROPOGATED.json to locate the file.

GNPS JSON records are flatter and cleaner than MoNA, but there are still a few
quirks worth knowing:

1. `peaks_json` is a STRING containing a JSON-encoded list of [mz, intensity]
   pairs (double-encoded). Must be parsed with json.loads() on the string.

2. `Ion_Mode` values include leading whitespace and capitalised spellings:
   " Positive", "Positive", " Negative", "Negative", "". Strip and lowercase.

3. `Adduct` values vary in bracket notation: "M+H", "[M+H]+", "M-H", "[M-H]-".
   We normalise to the bracketed form in `_normalise_adduct()`.

4. `Precursor_MZ` is a string that may be empty, "0.0", or "N/A". Parse defensively.

5. Not every record has SMILES — some contributor entries have only the compound
   name. Records without SMILES AND without InChIKey are filtered out of the
   v0 pipeline (they cannot be cross-referenced against HMDB / PubChem later).

6. `Ion_Source` is what distinguishes LC-ESI from DI-ESI, MALDI, etc. For v0
   we accept anything containing "LC" or "ESI" (so DI-ESI is kept), and reject
   MALDI, GC, EI.

7. `library_membership` tells you which sub-collection a record belongs to
   ("GNPS-LIBRARY", "MASSBANK", "CASMI", "MIADB", etc.). Useful for
   stratified analysis later.

This loader is the ONLY place in the codebase that knows about GNPS's quirks.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class GnpsRecord:
    """A parsed GNPS record with fields flattened and types coerced.

    Kept as a plain dataclass so malformed records can be inspected. Convert to
    schemas.Spectrum only once you've confirmed is_usable_for_v0.
    """

    spectrum_id: str
    compound_name: str | None
    smiles: str | None
    inchi: str | None
    inchikey: str | None
    # Experimental conditions
    instrument: str | None
    ion_source: str | None  # e.g. "LC-ESI", "DI-ESI", "MALDI"
    ion_mode: str | None  # normalised to "positive" | "negative" | None
    adduct: str | None  # normalised to bracketed form where possible
    precursor_mz: float | None
    ms_level: int | None
    # Spectrum
    peaks: list[tuple[float, float]]
    # Library bookkeeping
    library_membership: str | None
    library_quality: int | None  # GNPS quality score, 1-4, where 1 is highest

    @property
    def is_usable_for_v0(self) -> bool:
        """True iff this record meets v0 acceptance: LC/DI-ESI positive mode
        MS/MS with precursor_mz, adduct, at least 3 peaks, and SMILES or InChIKey.
        """
        if self.ion_mode != "positive":
            return False
        if self.precursor_mz is None or self.precursor_mz <= 0:
            return False
        if self.adduct is None:
            return False
        if len(self.peaks) < 3:
            return False
        if not self.smiles and not self.inchikey:
            return False
        if self.ion_source:
            src = self.ion_source.upper()
            # Reject non-soft-ionization sources
            if "MALDI" in src or src.startswith("EI") or src == "GC":
                return False
        if self.ms_level is not None and self.ms_level != 2:
            return False
        return True


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_ion_mode(raw: str | None) -> str | None:
    """Normalise GNPS Ion_Mode to 'positive' | 'negative' | None.

    GNPS values seen in the wild: ' Positive', 'Positive', 'POSITIVE',
    ' Negative', 'Negative', '', 'N/A'.
    """
    if not raw:
        return None
    v = raw.strip().lower()
    if v == "positive":
        return "positive"
    if v == "negative":
        return "negative"
    return None


def _parse_precursor_mz(raw: str | None) -> float | None:
    """Parse Precursor_MZ, handling empty, 'N/A', '0.0' (which means unset)."""
    if not raw:
        return None
    v = raw.strip()
    if v in ("", "N/A", "n/a", "NA"):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    # GNPS records with Precursor_MZ=0.0 are effectively unset. Real MS/MS
    # precursors are always > 0.
    if f <= 0:
        return None
    return f


def _parse_ms_level(raw: str | None) -> int | None:
    """Parse ms_level as int. GNPS uses '1', '2', sometimes missing."""
    if not raw:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


_ADDUCT_PATTERN = re.compile(r"^\[?(M[+\-][^]]*?)\]?([+\-]?)$")


def _normalise_adduct(raw: str | None) -> str | None:
    """Normalise adduct to bracketed form where possible.

    Examples:
      'M+H'        -> '[M+H]+'
      'M-H'        -> '[M-H]-'
      '[M+H]+'     -> '[M+H]+'  (already normal)
      '[M+Na]+'    -> '[M+Na]+'
      'M+NH4'      -> '[M+NH4]+'
      ''           -> None

    If the raw string does not look like an adduct at all, returns it as-is
    (conservative: better to pass through a weird value than silently drop it).
    """
    if not raw:
        return None
    v = raw.strip()
    if v in ("", "N/A", "n/a"):
        return None

    # Already bracketed — trust it
    if v.startswith("["):
        return v

    # Bare 'M+H' / 'M-H' form — infer charge from +/- in the body
    if "M+" in v:
        return f"[{v}]+"
    if "M-" in v:
        return f"[{v}]-"

    return v  # give up, pass through


def _parse_peaks_json(raw: str | None) -> list[tuple[float, float]]:
    """Parse GNPS peaks_json (double-encoded JSON string of [mz, intensity] pairs).

    Returns peaks as-is (no normalisation of intensities). Use
    common.mona_loader.normalise_peaks() or spectrum_preprocess to normalise.
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    peaks: list[tuple[float, float]] = []
    for item in parsed:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            mz = float(item[0])
            intensity = float(item[1])
        except (ValueError, TypeError):
            continue
        if mz > 0 and intensity > 0:
            peaks.append((mz, intensity))
    peaks.sort(key=lambda p: p[0])
    return peaks


def _parse_quality(raw: str | int | None) -> int | None:
    """GNPS LibraryQuality is 1 (best) to 4 (worst). Parse defensively."""
    if raw is None:
        return None
    try:
        q = int(raw)
        if 1 <= q <= 4:
            return q
    except (ValueError, TypeError):
        pass
    return None


def _clean_na(raw: str | None) -> str | None:
    """Convert 'N/A', empty string, etc. to None. Strip whitespace otherwise."""
    if raw is None:
        return None
    v = raw.strip() if isinstance(raw, str) else str(raw).strip()
    if v in ("", "N/A", "n/a", "NA", "null", "None"):
        return None
    return v


# ---------------------------------------------------------------------------
# Record parser
# ---------------------------------------------------------------------------


def parse_record(raw: dict) -> GnpsRecord:
    """Convert one raw GNPS JSON record into a flattened GnpsRecord."""
    return GnpsRecord(
        spectrum_id=str(raw.get("spectrum_id", raw.get("SpectrumID", ""))),
        compound_name=_clean_na(raw.get("Compound_Name")),
        smiles=_clean_na(raw.get("Smiles")),
        inchi=_clean_na(raw.get("INCHI")),
        inchikey=_clean_na(raw.get("InChIKey_smiles") or raw.get("InChIKey")),
        instrument=_clean_na(raw.get("Instrument")),
        ion_source=_clean_na(raw.get("Ion_Source")),
        ion_mode=_parse_ion_mode(raw.get("Ion_Mode")),
        adduct=_normalise_adduct(raw.get("Adduct")),
        precursor_mz=_parse_precursor_mz(raw.get("Precursor_MZ")),
        ms_level=_parse_ms_level(raw.get("ms_level")),
        peaks=_parse_peaks_json(raw.get("peaks_json")),
        library_membership=_clean_na(raw.get("library_membership")),
        library_quality=_parse_quality(raw.get("Library_Class") or raw.get("LibraryQuality")),
    )


# ---------------------------------------------------------------------------
# Top-level loaders
# ---------------------------------------------------------------------------


def iter_records(path: str | Path) -> Iterator[GnpsRecord]:
    """Yield parsed GnpsRecords from the GNPS JSON export, one at a time.

    Reads the full file into memory. For ALL_GNPS_NO_PROPOGATED (~500k records,
    a few hundred MB), this requires several GB of RAM peak during parse. If
    that's a concern, switch to ijson streaming.
    """
    with open(path) as f:
        raw_list = json.load(f)
    for raw in raw_list:
        try:
            yield parse_record(raw)
        except Exception as e:
            sid = raw.get("spectrum_id", "<unknown>")
            logger.warning("Failed to parse GNPS record %s: %s", sid, e)
            continue


def load_v0_usable(path: str | Path) -> list[GnpsRecord]:
    """Convenience: return only records that pass the v0 acceptance filter.

    v0 filter: positive ion mode MS/MS with precursor_mz, adduct, ≥3 peaks,
    SMILES or InChIKey, and a soft-ionization source (LC/DI-ESI accepted;
    MALDI, GC, EI rejected).
    """
    kept: list[GnpsRecord] = []
    total = 0
    for rec in iter_records(path):
        total += 1
        if rec.is_usable_for_v0:
            kept.append(rec)
    logger.info("GNPS: loaded %d v0-usable records out of %d total", len(kept), total)
    return kept


def normalise_peaks(peaks: list[tuple[float, float]]) -> tuple[list[float], list[float]]:
    """Normalise peaks so base peak intensity is 1.0. Returns (mz_list, intensity_list).

    Raises ValueError if peaks is empty or all intensities are non-positive.
    Shared helper — behaviour identical to common.mona_loader.normalise_peaks.
    """
    if not peaks:
        raise ValueError("Cannot normalise empty peak list.")
    max_int = max(p[1] for p in peaks)
    if max_int <= 0:
        raise ValueError("All peak intensities are non-positive.")
    mz_list = [p[0] for p in peaks]
    int_list = [p[1] / max_int for p in peaks]
    return mz_list, int_list
