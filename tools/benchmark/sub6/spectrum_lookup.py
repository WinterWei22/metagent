"""GNPS + MassBank-(non-RIKEN) spectrum lookup for Sub-6A end-to-end tasks.

Sub-6 was originally scoped to plant secondary metabolism (RIKEN-only
spectra). After moving Sub-6A to mammalian end-to-end (see session
``track_sub6_pathway_fix``), spectra need to come from public libraries
that cover mammalian metabolites. This module builds a per-compound
spectrum index from:

* **GNPS** ``ALL_GNPS_cleaned.mgf`` (parsed via :mod:`common.gnps_loader`).
* **MassBank** non-RIKEN contributors (parsed via
  :mod:`tools.benchmark.massbank_parser`). RIKEN itself is excluded —
  it carries plant secondary metabolites with the ``CE=6V`` ramp
  signature we already use for Sub-6B-Plant elsewhere.

Quality gate per spectrum:
  * ``len(peaks) >= require_peaks_min``
  * ``ion_mode in {"positive", "negative"}``
  * ``adduct`` parseable (loosely — bracketed or bare ``[M+H]+`` form)
  * ``precursor_mz > 0``
  * ``ms_level == 2`` (best-effort)

Leakage handling:
  Each ``SpectrumPayload.source_id`` is a stable library identifier
  (``CCMSLIB...`` for GNPS, ``MSBNK-<contributor>-...`` for MassBank).
  Downstream Sub-6A orchestrator should pass these into
  ``library_search`` as an exclusion list to prevent self-matching —
  exactly the role :mod:`tools.benchmark.leakage_filter` plays for the
  RIKEN-vs-GNPS NM-002 audit.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

import csv

from common.gnps_loader import (
    _normalise_adduct as _gnps_normalise_adduct,
    _parse_ion_mode as _gnps_parse_ion_mode,
    _parse_precursor_mz as _gnps_parse_precursor_mz,
    iter_records as iter_gnps_records,
)
from tools.benchmark.massbank_normalizer import (
    normalize_collision_energy,
    normalize_ion_mode,
)
from tools.benchmark.massbank_parser import (
    MassBankParseError,
    parse_massbank_record,
)

logger = logging.getLogger(__name__)


# Default MassBank contributors to include for Sub-6A-Mammalian. We exclude
# RIKEN (plant scope, used elsewhere) and contributors heavy in non-mammalian
# / specialty data.
DEFAULT_MASSBANK_CONTRIBUTORS: tuple[str, ...] = (
    "Athens_Univ", "Eawag", "Eawag_Additional_Specs", "Washington_State_Univ",
    "Fac_Eng_Univ_Tokyo", "IPB_Halle", "Kazusa", "Keio_Univ",
    "BS", "BGC_Munich", "MPI_for_Chemical_Ecology", "MSSJ",
)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


@dataclass
class SpectrumPayload:
    """One library spectrum suitable for Sub-6A's differential_spectra field."""

    spectrum_id: str        # unique within Sub-6A: f"sub6a-{source_db}-{source_id}"
    source_db: str          # "gnps" | "massbank"
    source_id: str          # CCMSLIB... | MSBNK-...
    inchikey: str
    inchikey_first_block: str
    instrument: str | None
    instrument_type: str | None
    ion_mode: str | None    # "positive" | "negative"
    adduct: str | None
    precursor_mz: float | None
    collision_energy: float | None
    n_peaks: int
    peaks: list[tuple[float, float]]
    library_membership: str | None  # for GNPS: e.g. "GNPS-LIBRARY"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Quality / parsing helpers
# ---------------------------------------------------------------------------


_ADDUCT_RX = re.compile(r"^\[?M[+\-][^]]*\]?[+\-0-9]*$")


def _adduct_acceptable(s: str | None) -> bool:
    if not s:
        return False
    return bool(_ADDUCT_RX.match(s.strip()))


def _meets_quality(
    *, n_peaks: int, require_peaks_min: int,
    ion_mode: str | None, adduct: str | None,
    precursor_mz: float | None, ms_level: int | None,
) -> bool:
    if n_peaks < require_peaks_min:
        return False
    if ion_mode not in ("positive", "negative"):
        return False
    if not _adduct_acceptable(adduct):
        return False
    if precursor_mz is None or precursor_mz <= 0:
        return False
    if ms_level is not None and ms_level != 2:
        return False
    return True


# ---------------------------------------------------------------------------
# GNPS source
# ---------------------------------------------------------------------------


def _build_gnps_target_meta(
    csv_path: Path, target_first_blocks: set[str],
) -> dict[str, dict]:
    """First pass: scan GNPS csv to build spectrum_id → metadata for in-target records.

    The mgf file does not carry InChIKey or many of the metadata fields we
    need (instrument, library_membership, etc.), so we resolve everything
    from the csv first and pull only peaks from the mgf in pass 2.
    """
    out: dict[str, dict] = {}
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ikey = (row.get("InChIKey_smiles") or "").strip()
            if len(ikey) < 14 or ikey[:14] not in target_first_blocks:
                continue
            sid = (row.get("spectrum_id") or "").strip()
            if not sid:
                continue
            try:
                ce = float(row.get("collision_energy") or "") if row.get("collision_energy") else None
            except (TypeError, ValueError):
                ce = None
            out[sid] = {
                "inchikey": ikey,
                "first_block": ikey[:14],
                "adduct": _gnps_normalise_adduct(row.get("Adduct")),
                "ion_mode": _gnps_parse_ion_mode(row.get("Ion_Mode")),
                "precursor_mz": _gnps_parse_precursor_mz(row.get("Precursor_MZ")),
                "collision_energy": ce,
                "instrument": row.get("msMassAnalyzer") or None,
                "ion_source": row.get("msIonisation") or None,
                "library_membership": row.get("GNPS_library_membership") or None,
                "compound_name": row.get("Compound_Name") or None,
            }
    return out


def _iter_mgf_blocks(path: Path) -> Iterator[tuple[str, list[tuple[float, float]]]]:
    """Yield (spectrum_id, peaks) for each BEGIN IONS / END IONS block."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        in_block = False
        sid = ""
        peaks: list[tuple[float, float]] = []
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s == "BEGIN IONS":
                in_block, sid, peaks = True, "", []
                continue
            if s == "END IONS":
                if in_block and sid:
                    yield sid, peaks
                in_block = False
                continue
            if not in_block:
                continue
            if "=" in s and not s[0].isdigit() and s[0] not in "+-.":
                k, _, v = s.partition("=")
                key = k.strip().upper()
                if key in ("SPECTRUMID", "SPECTRUM_ID", "TITLE") and not sid:
                    sid = v.strip()
            else:
                parts = s.split()
                if len(parts) >= 2:
                    try:
                        peaks.append((float(parts[0]), float(parts[1])))
                    except ValueError:
                        continue


def _iter_gnps_payloads(
    csv_path: Path,
    mgf_path: Path,
    target_first_blocks: set[str],
    *,
    require_peaks_min: int,
) -> Iterator[SpectrumPayload]:
    target_meta = _build_gnps_target_meta(csv_path, target_first_blocks)
    if not target_meta:
        logger.info("gnps: csv resolved 0 in-target rows — nothing to look up")
        return
    n_seen = n_kept = 0
    for sid, peaks in _iter_mgf_blocks(mgf_path):
        n_seen += 1
        meta = target_meta.get(sid)
        if meta is None:
            continue
        if not _meets_quality(
            n_peaks=len(peaks), require_peaks_min=require_peaks_min,
            ion_mode=meta["ion_mode"], adduct=meta["adduct"],
            precursor_mz=meta["precursor_mz"], ms_level=2,  # GNPS library is MS2
        ):
            continue
        n_kept += 1
        yield SpectrumPayload(
            spectrum_id=f"sub6a-gnps-{sid}",
            source_db="gnps",
            source_id=sid,
            inchikey=meta["inchikey"],
            inchikey_first_block=meta["first_block"],
            instrument=meta["instrument"],
            instrument_type=meta["ion_source"],
            ion_mode=meta["ion_mode"],
            adduct=meta["adduct"],
            precursor_mz=meta["precursor_mz"],
            collision_energy=meta["collision_energy"],
            n_peaks=len(peaks),
            peaks=peaks,
            library_membership=meta["library_membership"],
        )
    logger.info(
        "gnps: csv resolved %d target spectrum_ids, mgf scanned %d blocks, kept %d",
        len(target_meta), n_seen, n_kept,
    )


# ---------------------------------------------------------------------------
# MassBank source
# ---------------------------------------------------------------------------


def _iter_massbank_payloads(
    massbank_root: Path,
    target_first_blocks: set[str],
    *,
    contributors: Iterable[str],
    require_peaks_min: int,
) -> Iterator[SpectrumPayload]:
    n_seen = n_kept = 0
    for contrib in contributors:
        contrib_dir = massbank_root / contrib
        if not contrib_dir.is_dir():
            continue
        for fp in contrib_dir.glob("MSBNK-*.txt"):
            n_seen += 1
            try:
                rec = parse_massbank_record(fp)
            except MassBankParseError:
                continue
            ikey = (rec.inchikey or "").strip()
            if len(ikey) < 14:
                continue
            first = ikey[:14]
            if first not in target_first_blocks:
                continue
            ion_mode = normalize_ion_mode(rec.ion_mode_raw)
            ce, _warn = normalize_collision_energy(rec.collision_energy_raw)
            ms_level: int | None = None
            if rec.ms_level:
                m = re.search(r"(\d)", rec.ms_level)
                if m:
                    ms_level = int(m.group(1))
            if not _meets_quality(
                n_peaks=len(rec.peaks),
                require_peaks_min=require_peaks_min,
                ion_mode=ion_mode, adduct=rec.precursor_type_raw,
                precursor_mz=rec.precursor_mz, ms_level=ms_level,
            ):
                continue
            n_kept += 1
            yield SpectrumPayload(
                spectrum_id=f"sub6a-massbank-{rec.accession}",
                source_db="massbank",
                source_id=rec.accession,
                inchikey=ikey,
                inchikey_first_block=first,
                instrument=rec.instrument,
                instrument_type=rec.instrument_type,
                ion_mode=ion_mode,
                adduct=rec.precursor_type_raw,
                precursor_mz=rec.precursor_mz,
                collision_energy=ce,
                n_peaks=len(rec.peaks),
                peaks=rec.peaks,
                library_membership=rec.contributor,
            )
    logger.info("massbank: scanned %d files, kept %d for Sub-6A", n_seen, n_kept)


# ---------------------------------------------------------------------------
# Public index builder
# ---------------------------------------------------------------------------


def build_spectrum_index(
    target_first_blocks: Iterable[str],
    *,
    gnps_csv_path: Path | str | None = None,
    gnps_mgf_path: Path | str | None = None,
    massbank_root: Path | str | None = None,
    massbank_contributors: Iterable[str] = DEFAULT_MASSBANK_CONTRIBUTORS,
    require_peaks_min: int = 30,
) -> dict[str, list[SpectrumPayload]]:
    """Return ``inchikey_first_block → list[SpectrumPayload]`` index.

    GNPS path requires BOTH ``gnps_csv_path`` (metadata + InChIKey) AND
    ``gnps_mgf_path`` (peaks). MassBank path requires ``massbank_root``.
    Sources are independent; pass any combination.
    """
    targets = {b for b in target_first_blocks if b}
    if not targets:
        return {}

    out: dict[str, list[SpectrumPayload]] = defaultdict(list)
    seen_ids: set[str] = set()

    if gnps_csv_path and gnps_mgf_path:
        for payload in _iter_gnps_payloads(
            Path(gnps_csv_path), Path(gnps_mgf_path), targets,
            require_peaks_min=require_peaks_min,
        ):
            if payload.source_id in seen_ids:
                continue
            seen_ids.add(payload.source_id)
            out[payload.inchikey_first_block].append(payload)
    elif gnps_csv_path or gnps_mgf_path:
        logger.warning(
            "spectrum_lookup: GNPS skipped — both csv and mgf paths are required"
        )

    if massbank_root:
        for payload in _iter_massbank_payloads(
            Path(massbank_root), targets, contributors=massbank_contributors,
            require_peaks_min=require_peaks_min,
        ):
            if payload.source_id in seen_ids:
                continue
            seen_ids.add(payload.source_id)
            out[payload.inchikey_first_block].append(payload)

    return dict(out)


def index_coverage(
    index: dict[str, list[SpectrumPayload]],
    target_first_blocks: Iterable[str],
) -> dict[str, int]:
    targets = list(target_first_blocks)
    return {
        "n_targets": len(targets),
        "n_covered": sum(1 for b in targets if index.get(b)),
        "n_uncovered": sum(1 for b in targets if not index.get(b)),
        "total_spectra": sum(len(v) for v in index.values()),
    }
