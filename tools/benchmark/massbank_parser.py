"""MassBank record parser.

Reads MassBank ``.txt`` records into a :class:`MassBankRecord` intermediate
representation. The output is **deliberately not** a :class:`schemas.Spectrum`
yet — record fields here are kept close to the source format so downstream
:mod:`tools.benchmark.massbank_normalizer` can do the dirty-data work in one
place.

MassBank record format
----------------------
- Pretty-printed text, ``KEY: VALUE`` lines.
- ``$`` is allowed in keys (e.g. ``CH$NAME``, ``AC$MASS_SPECTROMETRY``).
- A line starting with whitespace is a **continuation** of the previous
  ``KEY: VALUE`` line.
- A few keys appear multiple times on purpose (e.g. ``CH$NAME``,
  ``CH$LINK``, ``AC$MASS_SPECTROMETRY`` sub-tags) and must all be kept.
- Some keys carry a sub-tag inside the value, e.g.
  ``AC$MASS_SPECTROMETRY: ION_MODE POSITIVE`` or
  ``CH$LINK: INCHIKEY ABCDE-XYZ``. We treat these as
  ``key=AC$MASS_SPECTROMETRY, value="ION_MODE POSITIVE"`` and unpack
  the sub-tag at extraction time.
- The peak block sits between ``PK$PEAK: m/z int. rel.int.`` (header line)
  and the record terminator ``//``. Each data row is whitespace-separated:
  ``<mz> <abs_intensity> <rel_intensity>``.
- ``PK$ANNOTATION:`` blocks may appear before ``PK$NUM_PEAK`` /
  ``PK$PEAK``. Their data rows look similar but with a different schema
  (``m/z formula count mass error_ppm``); we **skip** them.
- The record ends at the line ``//``.

Empty / N/A handling: bare empty values, ``N/A``, ``NA``, ``-`` map to ``None``.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from schemas.common import ToolError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MassBankParseError(ToolError):
    """Unrecoverable error while parsing a MassBank record."""

    code = "MASSBANK_PARSE_ERROR"
    recoverable = False


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class MassBankRecord:
    """Intermediate representation of a parsed MassBank record.

    Fields are kept in their *raw* form where the source has formatting
    variation (``ion_mode_raw``, ``collision_energy_raw``,
    ``precursor_type_raw``). Normalisation is the job of
    :mod:`tools.benchmark.massbank_normalizer`.
    """

    accession: str
    record_title: str

    # Compound info
    compound_names: list[str] = field(default_factory=list)
    formula: str | None = None
    exact_mass: float | None = None
    smiles: str | None = None
    inchi: str | None = None
    inchikey: str | None = None
    pubchem_cid: int | None = None

    # Instrument & acquisition (raw form — normaliser converts)
    instrument: str | None = None
    instrument_type: str | None = None
    ms_level: str | None = None  # e.g. "MS2", "MS"
    ion_mode_raw: str | None = None  # e.g. "POSITIVE"
    collision_energy_raw: str | None = None  # e.g. "20 eV", "15 % (nominal)"

    # Precursor
    precursor_mz: float | None = None
    precursor_type_raw: str | None = None  # e.g. "[M+H]+"

    # Peaks
    num_peaks: int = 0  # PK$NUM_PEAK as written; may not match len(peaks)
    peaks: list[tuple[float, float]] = field(default_factory=list)

    # Source tracking
    source_file: Path | None = None
    contributor: str = ""  # "RIKEN", "Eawag", etc.
    raw_text: str | None = None  # kept None unless caller asks

    # Soft warnings collected during parse — never raised
    parse_warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_NA_VALUES = {"", "N/A", "n/a", "NA", "null", "None", "-"}


def _clean_na(value: str | None) -> str | None:
    """Strip + collapse common 'unset' values to None."""
    if value is None:
        return None
    v = value.strip()
    return None if v in _NA_VALUES else v


def _parse_float(value: str | None) -> float | None:
    """Parse a leading float from ``value``. Returns ``None`` on failure.

    Tolerates trailing units / annotations: ``"181.0739"``, ``"75.03203"``,
    ``"299.2329 m/z"``, ``"20 eV"`` all work.
    """
    if value is None:
        return None
    v = value.strip()
    if v in _NA_VALUES:
        return None
    try:
        return float(v)
    except ValueError:
        pass
    m = re.match(r"[-+]?(\d+\.?\d*|\.\d+)", v)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return None
    return None


def _extract_subkey(values: list[str], subkey: str) -> str | None:
    """Find a sub-tagged value inside a multi-valued key.

    Example: ``values=["MS_TYPE MS2", "ION_MODE POSITIVE", ...]``,
    ``subkey="ION_MODE"`` → ``"POSITIVE"``.
    Returns the value of the first matching sub-tag, or ``None``.
    """
    needle = subkey.strip()
    for v in values:
        token, _, rest = v.strip().partition(" ")
        if token == needle and rest:
            return rest.strip()
    return None


_PUBCHEM_CID_RE = re.compile(r"\bCID[:\s]?(\d+)", re.IGNORECASE)
_INCHIKEY_RE = re.compile(r"\b([A-Z]{14}-[A-Z]{10}-[A-Z])\b")


def _extract_inchikey_from_links(links: list[str]) -> str | None:
    """Pick the InChIKey out of ``CH$LINK`` values.

    Format seen in MassBank:
        ``CH$LINK: INCHIKEY DHMQDGOQFOQNFH-UHFFFAOYSA-N``
    The first 14-10-1 hash that pairs with the ``INCHIKEY`` sub-tag wins.
    Falls back to a regex scan if the sub-tag is missing but the hash is
    obvious (defensive — happens with hand-edited records).
    """
    for v in links:
        v_str = v.strip()
        if v_str.upper().startswith("INCHIKEY"):
            tail = v_str[len("INCHIKEY"):].strip()
            m = _INCHIKEY_RE.search(tail)
            if m:
                return m.group(1)
    # Fallback: scan all link lines for an InChIKey-shaped token.
    for v in links:
        m = _INCHIKEY_RE.search(v)
        if m:
            return m.group(1)
    return None


def _extract_pubchem_cid(links: list[str]) -> int | None:
    """Extract PubChem CID from ``CH$LINK`` lines.

    Common forms:
        ``PUBCHEM CID:750``
        ``PUBCHEM CID 750``
        ``PUBCHEM 750``  (rare; we accept it)
    """
    for v in links:
        v_str = v.strip()
        if not v_str.upper().startswith("PUBCHEM"):
            continue
        tail = v_str[len("PUBCHEM"):].strip()
        m = _PUBCHEM_CID_RE.search(tail)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
        # Bare "PUBCHEM 750" form
        token = tail.split()[0] if tail else ""
        if token.isdigit():
            return int(token)
    return None


def _contributor_from_path(path: Path | None) -> str:
    """Best-effort contributor name from the source file path / accession.

    MassBank-data filenames are uniformly ``MSBNK-<CONTRIBUTOR>-<ID>.txt``,
    so the filename is the most reliable source. We use it first; fall back
    to the parent directory name only when the filename doesn't follow the
    ``MSBNK-`` convention.
    """
    if path is None:
        return ""
    stem = path.stem
    if stem.startswith("MSBNK-"):
        parts = stem.split("-", 2)
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    # Fallback: walk up to a likely contributor dir.
    skip = {
        "massbank_records", "fixtures", "main", "MassBank-data",
        "data", "raw", "benchmark", "tests",
    }
    for parent in path.parents:
        name = parent.name
        if name and name not in skip and not name.startswith("."):
            return name
    return ""


# ---------------------------------------------------------------------------
# Core line parser
# ---------------------------------------------------------------------------


def _split_records(text: str) -> Iterator[str]:
    """Split a multi-record blob on the ``//`` terminator."""
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip() == "//":
            if buf:
                yield "\n".join(buf)
                buf = []
            continue
        buf.append(line)
    if buf:  # trailing record without // — caller decides whether to keep
        yield "\n".join(buf)


def _parse_lines(text: str) -> tuple[dict[str, list[str]], list[tuple[float, float]], list[str], bool]:
    """Tokenise one record into (key_values, peaks, warnings, saw_terminator).

    ``key_values`` maps each top-level key to the list of values it produced
    (ordered as seen in the file). Continuation lines have already been
    folded into the last value.
    """
    rec_data: dict[str, list[str]] = {}
    peaks: list[tuple[float, float]] = []
    warnings: list[str] = []

    current_key: str | None = None
    in_peak_block = False
    in_annotation_block = False
    saw_terminator = False

    for raw_line in text.splitlines():
        if raw_line.strip() == "//":
            saw_terminator = True
            break

        # Indented / continuation line
        if raw_line and (raw_line[0] == " " or raw_line[0] == "\t"):
            stripped = raw_line.strip()
            if not stripped:
                continue
            if in_peak_block:
                parts = stripped.split()
                if len(parts) >= 2:
                    try:
                        mz = float(parts[0])
                        intensity = float(parts[1])
                        if mz > 0 and intensity >= 0:
                            peaks.append((mz, intensity))
                        else:
                            warnings.append(f"non-positive peak: {stripped!r}")
                    except ValueError:
                        warnings.append(f"unparseable peak row: {stripped!r}")
                else:
                    warnings.append(f"short peak row: {stripped!r}")
                continue
            if in_annotation_block:
                # Skip PK$ANNOTATION rows entirely.
                continue
            # Continuation of last KV value.
            if current_key is not None and rec_data.get(current_key):
                rec_data[current_key][-1] = (
                    rec_data[current_key][-1] + " " + stripped
                ).strip()
            else:
                # Stray indented line at the start — just ignore.
                continue
            continue

        # Non-indented line. Either a KEY: value or noise.
        if ":" not in raw_line:
            # Some MassBank records have stray empty lines; ignore.
            continue

        key, _, value = raw_line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        # Reset block flags whenever we hit a new top-level key.
        in_peak_block = False
        in_annotation_block = False

        if key == "PK$PEAK":
            in_peak_block = True
            current_key = key
            # The value here is the column header; do not store it.
            continue
        if key == "PK$ANNOTATION":
            in_annotation_block = True
            current_key = key
            continue

        rec_data.setdefault(key, []).append(value)
        current_key = key

    return rec_data, peaks, warnings, saw_terminator


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_massbank_record(
    file_path: Path | str,
    *,
    keep_raw_text: bool = False,
) -> MassBankRecord:
    """Parse one MassBank ``.txt`` file into a :class:`MassBankRecord`.

    Parameters
    ----------
    file_path
        Path to a MassBank record file.
    keep_raw_text
        If ``True``, populate :attr:`MassBankRecord.raw_text` for debugging.
        Default ``False`` to keep memory bounded for large iterations.

    Raises
    ------
    :class:`MassBankParseError`
        If the file cannot be read or has no ``ACCESSION`` line. Recoverable
        format quirks are reported in :attr:`MassBankRecord.parse_warnings`.
    """
    path = Path(file_path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise MassBankParseError(f"cannot read {path}: {e}") from e

    rec_data, peaks, warnings, saw_terminator = _parse_lines(text)

    accession_list = rec_data.get("ACCESSION") or []
    if not accession_list:
        raise MassBankParseError(
            f"{path}: no ACCESSION line — file does not look like a MassBank record."
        )
    accession = accession_list[0].strip()
    if not accession:
        raise MassBankParseError(f"{path}: empty ACCESSION value.")

    if not saw_terminator:
        warnings.append("missing '//' terminator")

    record_title = (rec_data.get("RECORD_TITLE") or [""])[0]

    # Compound names — keep ALL CH$NAME values
    compound_names = [v.strip() for v in rec_data.get("CH$NAME", []) if _clean_na(v)]

    formula = _clean_na((rec_data.get("CH$FORMULA") or [None])[0])
    exact_mass = _parse_float((rec_data.get("CH$EXACT_MASS") or [None])[0])
    smiles = _clean_na((rec_data.get("CH$SMILES") or [None])[0])
    inchi = _clean_na((rec_data.get("CH$IUPAC") or [None])[0])

    links = rec_data.get("CH$LINK", [])
    inchikey = _extract_inchikey_from_links(links)
    pubchem_cid = _extract_pubchem_cid(links)

    instrument = _clean_na((rec_data.get("AC$INSTRUMENT") or [None])[0])
    instrument_type = _clean_na((rec_data.get("AC$INSTRUMENT_TYPE") or [None])[0])

    ms_section = rec_data.get("AC$MASS_SPECTROMETRY", [])
    ms_level = _clean_na(_extract_subkey(ms_section, "MS_TYPE"))
    ion_mode_raw = _clean_na(_extract_subkey(ms_section, "ION_MODE"))
    collision_energy_raw = _clean_na(_extract_subkey(ms_section, "COLLISION_ENERGY"))

    focused = rec_data.get("MS$FOCUSED_ION", [])
    precursor_mz_raw = _extract_subkey(focused, "PRECURSOR_M/Z")
    precursor_mz = _parse_float(precursor_mz_raw)
    precursor_type_raw = _clean_na(_extract_subkey(focused, "PRECURSOR_TYPE"))

    # Peak count: prefer the declared PK$NUM_PEAK, fall back to len(peaks).
    declared_num = (rec_data.get("PK$NUM_PEAK") or [None])[0]
    try:
        num_peaks = int(declared_num) if declared_num else len(peaks)
    except ValueError:
        num_peaks = len(peaks)
        warnings.append(f"unparseable PK$NUM_PEAK: {declared_num!r}")
    if peaks and num_peaks and len(peaks) != num_peaks:
        warnings.append(
            f"PK$NUM_PEAK={num_peaks} but parsed {len(peaks)} peak rows"
        )

    return MassBankRecord(
        accession=accession,
        record_title=record_title,
        compound_names=compound_names,
        formula=formula,
        exact_mass=exact_mass,
        smiles=smiles,
        inchi=inchi,
        inchikey=inchikey,
        pubchem_cid=pubchem_cid,
        instrument=instrument,
        instrument_type=instrument_type,
        ms_level=ms_level,
        ion_mode_raw=ion_mode_raw,
        collision_energy_raw=collision_energy_raw,
        precursor_mz=precursor_mz,
        precursor_type_raw=precursor_type_raw,
        num_peaks=num_peaks,
        peaks=peaks,
        source_file=path,
        contributor=_contributor_from_path(path),
        raw_text=text if keep_raw_text else None,
        parse_warnings=warnings,
    )


def parse_massbank_directory(
    directory: Path | str,
    contributor_filter: list[str] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Iterator[MassBankRecord]:
    """Walk a directory tree yielding parsed records.

    Parameters
    ----------
    directory
        Either a contributor directory (e.g. ``.../RIKEN/``) or the root of
        the MassBank-data clone. We recurse into subdirectories so both
        layouts work.
    contributor_filter
        Optional whitelist of contributor names. Filtering is by the parent
        directory name AND by the substring after ``MSBNK-`` in the
        filename, so it works on both flat fixtures and nested clones.
        Comparison is case-insensitive.
    progress_callback
        Called as ``cb(processed, total)`` after each file. ``total`` is the
        upfront file count; ``processed`` includes failed files.

    Yields
    ------
    :class:`MassBankRecord`
        One record per successfully-parsed ``.txt`` file. Files that raise
        :class:`MassBankParseError` are skipped with a logged warning.
    """
    root = Path(directory)
    if not root.is_dir():
        raise MassBankParseError(f"{root} is not a directory.")
    files = sorted(root.rglob("*.txt"))
    total = len(files)
    processed = 0

    contrib_set = {c.lower() for c in contributor_filter} if contributor_filter else None

    for fp in files:
        processed += 1
        if contrib_set is not None:
            # Match against parent dir or accession-derived contributor.
            parent_name = fp.parent.name.lower()
            stem = fp.stem
            stem_contrib = ""
            if stem.startswith("MSBNK-"):
                parts = stem.split("-", 2)
                if len(parts) >= 2:
                    stem_contrib = parts[1].lower()
            if parent_name not in contrib_set and stem_contrib not in contrib_set:
                if progress_callback:
                    progress_callback(processed, total)
                continue
        try:
            yield parse_massbank_record(fp)
        except MassBankParseError as e:
            logger.warning("MassBank: skipping %s: %s", fp, e)
        except Exception as e:  # defensive — should never escape parse_massbank_record
            logger.warning("MassBank: unexpected error parsing %s: %s", fp, e)
        finally:
            if progress_callback:
                progress_callback(processed, total)
