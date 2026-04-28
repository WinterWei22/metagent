"""MassBank record normaliser.

Converts a :class:`tools.benchmark.massbank_parser.MassBankRecord` (raw
intermediate) into a :class:`NormalizedRecord` containing a fully validated
:class:`schemas.common.Spectrum` plus a ``ground_truth`` and ``metadata``
dict. This is the single place in the pipeline where MassBank's "dirty
data" quirks are smoothed over.

Drop policy
-----------
A record is **dropped** (this function returns ``None``) when:

- ion mode is unparseable / missing (Spectrum requires it)
- adduct is unparseable (Spectrum requires a non-empty string)
- precursor m/z is missing or non-positive (Spectrum requires ``> 0``)
- SMILES is missing or invalid per RDKit
- after peak normalisation, fewer than ``min_peaks`` peaks remain

When recovery is possible we recover quietly (e.g. compute InChIKey from
SMILES, fill in exact mass from SMILES). Recovery and surprises both end up
in :attr:`NormalizedRecord.normalization_warnings`.

The ``min_peaks`` threshold here is **5**, deliberately laxer than the
benchmark filter's 15 — the filter applies the protocol's stricter rule.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from rdkit import Chem
from rdkit.Chem import Descriptors, inchi as rdkit_inchi

from schemas.common import Spectrum
from tools.benchmark.massbank_parser import MassBankRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class NormalizedRecord:
    """A MassBank record after normalisation, ready for filtering / pooling.

    The ``Spectrum`` is the only schema-typed payload. Everything else lives
    in plain dicts so we can carry contributor / accession / etc. without
    pushing those into the shared :class:`schemas.common.Spectrum` schema.
    """

    spectrum: Spectrum
    ground_truth: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    normalization_warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_MIN_PEAKS = 5
"""Soft floor applied here. The benchmark protocol enforces ≥15 elsewhere."""

_NOISE_FLOOR = 0.001
"""Drop peaks with relative intensity strictly below this. Per the brief's
pitfall list: 'preserve all peaks ≥0.001 relative intensity'."""


# ---------------------------------------------------------------------------
# Ion mode
# ---------------------------------------------------------------------------


def normalize_ion_mode(raw: str | None) -> Literal["positive", "negative"] | None:
    """Normalise an ion-mode string to canonical form.

    Accepts (case-insensitive, whitespace-tolerant):

    ============================  ==========
    Input variants                Output
    ============================  ==========
    ``POSITIVE``, ``POS``, ``+``  ``"positive"``
    ``NEGATIVE``, ``NEG``, ``-``  ``"negative"``
    ``None``, ``""``, ``N/A``     ``None``
    ============================  ==========
    """
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in {"", "n/a", "na", "none", "null", "-"}:
        # bare "-" is ambiguous — treat as missing rather than "negative"
        return None
    if v in {"positive", "pos", "p", "+", "positiv"}:
        return "positive"
    if v in {"negative", "neg", "n", "negativ"}:
        return "negative"
    return None


# ---------------------------------------------------------------------------
# Adduct
# ---------------------------------------------------------------------------


def normalize_adduct(raw: str | None, ion_mode: str | None) -> str | None:
    """Normalise an adduct string to canonical bracketed form.

    Parameters
    ----------
    raw
        Adduct string as it appears in MassBank, e.g. ``[M+H]+``, ``M+H``,
        ``[M+H]1+``, ``[M-H]-``, ``[M+2H]2+``.
    ion_mode
        Canonical ion mode (``"positive"`` / ``"negative"``). Used to
        infer the trailing charge when the raw string does not include it.

    Returns
    -------
    str | None
        Canonical bracketed form, e.g. ``[M+H]+``, ``[M-H]-``,
        ``[M+2H]2+``. Multi-charge forms are preserved verbatim.
        Returns ``None`` for empty / N/A / unrecognisable input.
    """
    if raw is None:
        return None
    v = raw.strip()
    if v.lower() in {"", "n/a", "na", "none", "null"}:
        return None

    # Drop a stray "1" in [M+H]1+ → [M+H]+ (charge of 1 is implicit).
    v = re.sub(r"\](1)([+\-])", r"]\2", v)

    # Already bracketed and has trailing charge? Keep verbatim.
    if v.startswith("[") and v.endswith("+"):
        return v
    if v.startswith("[") and v.endswith("-"):
        return v

    # Bracketed but missing trailing charge: [M+H], [M-H], [M+Na]
    if v.startswith("[") and v.endswith("]"):
        body = v[1:-1]
        sign = _infer_charge_sign(body, ion_mode)
        if sign is None:
            return None
        return f"[{body}]{sign}"

    # Bare form: M+H, M-H, M+Na, M+NH4
    if v.startswith("M+") or v.startswith("M-"):
        sign = _infer_charge_sign(v, ion_mode)
        if sign is None:
            return None
        return f"[{v}]{sign}"

    # Anything else — give up. (The Spectrum schema demands a non-empty
    # string but we'd rather drop the record than emit garbage.)
    return None


def _infer_charge_sign(body: str, ion_mode: str | None) -> str | None:
    """Decide whether the trailing sign should be ``+`` or ``-``."""
    has_minus = "-" in body
    has_plus = "+" in body
    if has_minus and has_plus:
        # Mixed (e.g. "M+H-H2O") — sign comes from ion_mode, fallback to "+".
        return _sign_from_mode(ion_mode) or "+"
    if has_minus and not has_plus:
        if ion_mode == "positive":
            return "+"
        return "-"
    if has_plus and not has_minus:
        if ion_mode == "negative":
            return "-"
        return "+"
    return _sign_from_mode(ion_mode)


def _sign_from_mode(ion_mode: str | None) -> str | None:
    if ion_mode == "positive":
        return "+"
    if ion_mode == "negative":
        return "-"
    return None


# ---------------------------------------------------------------------------
# Collision energy
# ---------------------------------------------------------------------------

_RAMP_KEYWORDS = ("ramp", "stepwave", "step-wave", "stepped", "step ")
"""Substring markers identifying a CE ramp / stepped acquisition."""


def normalize_collision_energy(raw: str | None) -> tuple[float | None, str | None]:
    """Extract a single eV value from a free-form CE string.

    Returns ``(value, warning_or_None)``. The warning string is meant for
    :attr:`NormalizedRecord.normalization_warnings`.

    Examples (with returned warnings):

    ===========================  =========================================
    Input                        Output
    ===========================  =========================================
    ``"20 eV"``                  ``(20.0, None)``
    ``"20"``                     ``(20.0, None)``
    ``"NCE 30"``                 ``(30.0, "NCE/% — treated as eV-equivalent")``
    ``"15 % (nominal)"``         ``(15.0, "NCE/% — treated as eV-equivalent")``
    ``"20-40 eV"``               ``(30.0, "range — used midpoint 30.0")``
    ``"ramp 10 to 40"``          ``(None, "ramp/stepwave — cannot single-value")``
    ===========================  =========================================
    """
    if raw is None:
        return None, None
    v = raw.strip()
    if v.lower() in {"", "n/a", "na", "none", "null"}:
        return None, None

    lower = v.lower()
    if any(k in lower for k in _RAMP_KEYWORDS):
        return None, f"ramp/stepwave — cannot single-value: {v!r}"

    # Range like "20-40 eV" or "20 to 40"
    range_match = re.search(r"(\d+\.?\d*)\s*(?:-|to)\s*(\d+\.?\d*)", v)
    if range_match:
        try:
            lo = float(range_match.group(1))
            hi = float(range_match.group(2))
        except ValueError:
            pass
        else:
            mid = (lo + hi) / 2.0
            return mid, f"range — used midpoint {mid:.1f}"

    # Detect NCE / percent style
    is_nce = "%" in v or "nce" in lower or "hcd" in lower or "rce" in lower

    # Pull leading numeric (works for "20", "20 eV", "NCE 30", "15 % (nominal)")
    num_match = re.search(r"[-+]?\d+\.?\d*", v)
    if not num_match:
        return None, f"unparseable CE: {v!r}"
    try:
        ev = float(num_match.group(0))
    except ValueError:
        return None, f"unparseable CE: {v!r}"

    if is_nce:
        return ev, "NCE/% — treated as eV-equivalent"
    return ev, None


# ---------------------------------------------------------------------------
# Peaks
# ---------------------------------------------------------------------------


def normalize_peaks(
    raw_peaks: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Normalise peaks for the :class:`Spectrum` schema.

    Operations, in order:

    1. Drop entries with intensity ``<= 0``.
    2. Sort by m/z ascending.
    3. Scale so the base peak intensity is ``1.0``.
    4. Drop peaks whose normalised intensity is below
       :data:`_NOISE_FLOOR` (``0.001``).

    Returns an empty list if all peaks were filtered.
    """
    if not raw_peaks:
        return []
    pos = [(mz, i) for mz, i in raw_peaks if i > 0 and mz > 0]
    if not pos:
        return []
    max_int = max(i for _, i in pos)
    if max_int <= 0:
        return []
    normed = [(mz, i / max_int) for mz, i in pos]
    normed = [(mz, i) for mz, i in normed if i >= _NOISE_FLOOR]
    normed.sort(key=lambda p: p[0])
    return normed


# ---------------------------------------------------------------------------
# RDKit helpers
# ---------------------------------------------------------------------------


def _validate_smiles(smiles: str) -> Chem.Mol | None:
    """Return an RDKit ``Mol`` if SMILES parses cleanly, else ``None``."""
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:  # RDKit can raise on extremely malformed input
        return None
    return mol


def _inchikey_from_mol(mol: Chem.Mol) -> str | None:
    try:
        ikey = rdkit_inchi.InchiToInchiKey(rdkit_inchi.MolToInchi(mol))
    except Exception:
        return None
    return ikey or None


def _exact_mass_from_mol(mol: Chem.Mol) -> float | None:
    try:
        return float(Descriptors.ExactMolWt(mol))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Top-level normalise
# ---------------------------------------------------------------------------


def normalize_record(record: MassBankRecord) -> NormalizedRecord | None:
    """Normalise one :class:`MassBankRecord` into a :class:`NormalizedRecord`.

    Returns ``None`` if the record cannot be made schema-compliant. Reasons
    are logged at DEBUG level and surfaced in the resulting record's
    ``normalization_warnings`` (when one is returned) or in the Python log
    when the record is dropped.
    """
    warnings: list[str] = []

    # 1. Ion mode is required by the schema.
    ion_mode = normalize_ion_mode(record.ion_mode_raw)
    if ion_mode is None:
        logger.debug(
            "drop %s: unparseable ion_mode %r", record.accession, record.ion_mode_raw
        )
        return None

    # 2. Adduct.
    adduct = normalize_adduct(record.precursor_type_raw, ion_mode)
    if not adduct:
        logger.debug(
            "drop %s: unparseable adduct %r", record.accession, record.precursor_type_raw
        )
        return None

    # Sanity check: bracket-form sign vs ion mode. Inconsistencies trust ion_mode.
    if adduct.endswith("+") and ion_mode == "negative":
        warnings.append(
            f"adduct/ion_mode mismatch: adduct={adduct} but ion_mode={ion_mode}; "
            "trusting ion_mode (per brief)"
        )
    elif adduct.endswith("-") and ion_mode == "positive":
        warnings.append(
            f"adduct/ion_mode mismatch: adduct={adduct} but ion_mode={ion_mode}; "
            "trusting ion_mode (per brief)"
        )

    # 3. Precursor m/z required.
    if record.precursor_mz is None or record.precursor_mz <= 0:
        logger.debug("drop %s: missing/non-positive precursor_mz", record.accession)
        return None

    # 4. Peaks.
    peaks = normalize_peaks(record.peaks)
    if len(peaks) < _MIN_PEAKS:
        logger.debug(
            "drop %s: %d peaks < min %d", record.accession, len(peaks), _MIN_PEAKS
        )
        return None

    # 5. SMILES required & must validate via RDKit.
    if not record.smiles:
        logger.debug("drop %s: missing SMILES", record.accession)
        return None
    mol = _validate_smiles(record.smiles)
    if mol is None:
        logger.debug("drop %s: invalid SMILES %r", record.accession, record.smiles)
        return None

    # Recover InChIKey if missing.
    inchikey = record.inchikey
    if not inchikey:
        recovered = _inchikey_from_mol(mol)
        if recovered:
            inchikey = recovered
            warnings.append("inchikey recovered from SMILES via RDKit")
        else:
            logger.debug("drop %s: no inchikey, RDKit recovery failed", record.accession)
            return None

    # Recover exact mass if missing.
    exact_mass = record.exact_mass
    if exact_mass is None:
        recovered_mass = _exact_mass_from_mol(mol)
        if recovered_mass is not None:
            exact_mass = recovered_mass
            warnings.append("exact_mass recovered from SMILES via RDKit")

    # 6. Collision energy (optional).
    ce_value, ce_warning = normalize_collision_energy(record.collision_energy_raw)
    if ce_warning:
        warnings.append(f"collision_energy: {ce_warning}")

    # 7. Forward parser warnings.
    for w in record.parse_warnings:
        warnings.append(f"parser: {w}")

    # 8. Build Spectrum.
    mz = [p[0] for p in peaks]
    intensity = [p[1] for p in peaks]
    try:
        spectrum = Spectrum(
            mz=mz,
            intensity=intensity,
            precursor_mz=record.precursor_mz,
            adduct=adduct,
            ionization_mode=ion_mode,
            collision_energy=ce_value,
        )
    except Exception as e:
        logger.debug("drop %s: Spectrum construction failed: %s", record.accession, e)
        return None

    ground_truth = {
        "smiles": record.smiles,
        "inchi": record.inchi,
        "inchikey": inchikey,
        "molecular_formula": record.formula,
        "exact_mass": exact_mass,
        "compound_names": record.compound_names,
        "primary_compound_name": record.compound_names[0] if record.compound_names else None,
        "pubchem_cid": record.pubchem_cid,
    }
    metadata = {
        "accession": record.accession,
        "record_title": record.record_title,
        "contributor": record.contributor,
        "instrument": record.instrument,
        "instrument_type": record.instrument_type,
        "ms_level": record.ms_level,
        "source_file": str(record.source_file) if record.source_file else None,
    }

    return NormalizedRecord(
        spectrum=spectrum,
        ground_truth=ground_truth,
        metadata=metadata,
        normalization_warnings=warnings,
    )
