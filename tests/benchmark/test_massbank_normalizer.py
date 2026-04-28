"""Unit tests for ``tools.benchmark.massbank_normalizer``."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.benchmark.massbank_normalizer import (
    NormalizedRecord,
    _NOISE_FLOOR,
    normalize_adduct,
    normalize_collision_energy,
    normalize_ion_mode,
    normalize_peaks,
    normalize_record,
)
from tools.benchmark.massbank_parser import MassBankRecord, parse_massbank_record

FIXTURES = Path(__file__).parent / "fixtures" / "massbank_records"


# ---------------------------------------------------------------------------
# Helpers — build a synthetic MassBankRecord without round-tripping a file.
# ---------------------------------------------------------------------------


def _make_record(**overrides) -> MassBankRecord:
    """Build a baseline MS2 [M+H]+ record; override fields via kwargs."""
    base = dict(
        accession="MSBNK-TEST-001",
        record_title="Test record",
        compound_names=["TestCompound"],
        formula="C9H11NO3",
        exact_mass=181.0739,
        smiles="N[C@@H](Cc1ccc(O)cc1)C(=O)O",
        inchi=None,
        inchikey="OUYCCCASQSFEME-QMMMGPOBSA-N",
        pubchem_cid=6057,
        instrument="Synthetic Q-TOF",
        instrument_type="LC-ESI-Q-TOF",
        ms_level="MS2",
        ion_mode_raw="POSITIVE",
        collision_energy_raw="20 eV",
        precursor_mz=182.0812,
        precursor_type_raw="[M+H]+",
        num_peaks=5,
        peaks=[
            (91.0540, 100.0),
            (119.0497, 200.0),
            (136.0757, 300.0),
            (165.0552, 50.0),
            (182.0812, 80.0),
        ],
    )
    base.update(overrides)
    return MassBankRecord(**base)


# ---------------------------------------------------------------------------
# normalize_ion_mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("POSITIVE", "positive"),
    ("Positive", "positive"),
    ("positive", "positive"),
    ("POS", "positive"),
    (" pos ", "positive"),
    ("P", "positive"),
    ("+", "positive"),
    ("NEGATIVE", "negative"),
    ("Negative", "negative"),
    ("NEG", "negative"),
    ("N", "negative"),
    (" neg ", "negative"),
    ("", None),
    ("N/A", None),
    ("None", None),
    (None, None),
    ("garbage", None),
    ("-", None),  # bare "-" is ambiguous
])
def test_normalize_ion_mode_variants(raw, expected) -> None:
    assert normalize_ion_mode(raw) == expected


# ---------------------------------------------------------------------------
# normalize_adduct
# ---------------------------------------------------------------------------


def test_normalize_adduct_with_explicit_brackets() -> None:
    assert normalize_adduct("[M+H]+", "positive") == "[M+H]+"
    assert normalize_adduct("[M-H]-", "negative") == "[M-H]-"
    assert normalize_adduct("[M+Na]+", "positive") == "[M+Na]+"
    assert normalize_adduct("[M+NH4]+", "positive") == "[M+NH4]+"
    assert normalize_adduct("[M-H2O+H]+", "positive") == "[M-H2O+H]+"


def test_normalize_adduct_without_brackets() -> None:
    assert normalize_adduct("M+H", "positive") == "[M+H]+"
    assert normalize_adduct("M-H", "negative") == "[M-H]-"
    assert normalize_adduct("M+Na", "positive") == "[M+Na]+"
    assert normalize_adduct("M+NH4", "positive") == "[M+NH4]+"


def test_normalize_adduct_strips_charge_number_one() -> None:
    """``[M+H]1+`` is just ``[M+H]+`` with a redundant 1."""
    assert normalize_adduct("[M+H]1+", "positive") == "[M+H]+"
    assert normalize_adduct("[M-H]1-", "negative") == "[M-H]-"


def test_normalize_adduct_preserves_multi_charge() -> None:
    """Multi-charge adducts are preserved verbatim — Spectrum.adduct: str."""
    assert normalize_adduct("[M+2H]2+", "positive") == "[M+2H]2+"
    assert normalize_adduct("[M-2H]2-", "negative") == "[M-2H]2-"


def test_normalize_adduct_infers_charge_from_ion_mode() -> None:
    """When the bracket has no trailing charge, ion_mode decides."""
    assert normalize_adduct("[M+H]", "positive") == "[M+H]+"
    assert normalize_adduct("[M-H]", "negative") == "[M-H]-"


def test_normalize_adduct_returns_none_for_garbage() -> None:
    assert normalize_adduct("", "positive") is None
    assert normalize_adduct("N/A", "positive") is None
    assert normalize_adduct(None, "positive") is None
    assert normalize_adduct("nonsense", "positive") is None


# ---------------------------------------------------------------------------
# normalize_collision_energy
# ---------------------------------------------------------------------------


def test_normalize_collision_energy_with_units() -> None:
    val, warn = normalize_collision_energy("20 eV")
    assert val == 20.0 and warn is None
    val, warn = normalize_collision_energy("20")
    assert val == 20.0 and warn is None
    val, warn = normalize_collision_energy("35.5 eV")
    assert val == 35.5 and warn is None


def test_normalize_collision_energy_nce() -> None:
    """NCE / % style is treated as eV-equivalent with a warning."""
    val, warn = normalize_collision_energy("NCE 30")
    assert val == 30.0
    assert warn and "NCE" in warn

    val, warn = normalize_collision_energy("15 % (nominal)")  # Eawag form
    assert val == 15.0
    assert warn and ("NCE" in warn or "%" in warn)

    val, warn = normalize_collision_energy("HCD 25")
    assert val == 25.0
    assert warn  # NCE warning


def test_normalize_collision_energy_range() -> None:
    val, warn = normalize_collision_energy("20-40 eV")
    assert val == 30.0
    assert warn and "midpoint" in warn

    val, warn = normalize_collision_energy("10 to 50")
    assert val == 30.0
    assert warn and "midpoint" in warn


def test_normalize_collision_energy_ramp_returns_none() -> None:
    val, warn = normalize_collision_energy("ramp 10 to 40")
    assert val is None
    assert warn and "ramp" in warn

    val, warn = normalize_collision_energy("stepwave 10/20/40")
    assert val is None
    assert warn


def test_normalize_collision_energy_empty_or_na() -> None:
    assert normalize_collision_energy(None) == (None, None)
    assert normalize_collision_energy("") == (None, None)
    assert normalize_collision_energy("N/A") == (None, None)


# ---------------------------------------------------------------------------
# normalize_peaks
# ---------------------------------------------------------------------------


def test_normalize_peaks_zero_intensity_filtered() -> None:
    out = normalize_peaks([(100.0, 0.0), (200.0, 50.0), (300.0, 100.0)])
    assert (100.0, 0.0) not in out
    assert len(out) == 2


def test_normalize_peaks_max_intensity_one() -> None:
    out = normalize_peaks([(100.0, 50.0), (200.0, 200.0), (300.0, 100.0)])
    assert max(i for _, i in out) == pytest.approx(1.0)


def test_normalize_peaks_sorted_by_mz() -> None:
    out = normalize_peaks([(300.0, 100.0), (100.0, 200.0), (200.0, 50.0)])
    mz_list = [p[0] for p in out]
    assert mz_list == sorted(mz_list)


def test_normalize_peaks_drops_below_noise_floor() -> None:
    """Peaks with rel-intensity below 0.001 get dropped."""
    out = normalize_peaks([
        (100.0, 1000.0),  # max
        (200.0, 0.5),     # rel = 5e-4 → drop
        (300.0, 1.0),     # rel = 1e-3 → keep
    ])
    mzs = [p[0] for p in out]
    assert 200.0 not in mzs
    assert 300.0 in mzs


def test_normalize_peaks_empty_input() -> None:
    assert normalize_peaks([]) == []
    assert normalize_peaks([(100.0, 0.0)]) == []


# ---------------------------------------------------------------------------
# normalize_record — drop conditions
# ---------------------------------------------------------------------------


def test_record_dropped_when_smiles_missing() -> None:
    rec = _make_record(smiles=None)
    assert normalize_record(rec) is None


def test_record_dropped_when_smiles_invalid() -> None:
    """RDKit must reject the SMILES → drop."""
    rec = _make_record(smiles="not a molecule")
    assert normalize_record(rec) is None


def test_record_dropped_when_ion_mode_missing() -> None:
    rec = _make_record(ion_mode_raw=None)
    assert normalize_record(rec) is None


def test_record_dropped_when_adduct_unparseable() -> None:
    rec = _make_record(precursor_type_raw="garbage")
    assert normalize_record(rec) is None


def test_record_dropped_when_precursor_mz_missing() -> None:
    rec = _make_record(precursor_mz=None)
    assert normalize_record(rec) is None


def test_record_dropped_when_too_few_peaks() -> None:
    rec = _make_record(peaks=[(100.0, 1.0), (200.0, 1.0)])  # 2 peaks
    assert normalize_record(rec) is None


# ---------------------------------------------------------------------------
# normalize_record — recovery paths
# ---------------------------------------------------------------------------


def test_record_kept_when_inchikey_recovered_from_smiles() -> None:
    rec = _make_record(inchikey=None)
    out = normalize_record(rec)
    assert out is not None
    assert out.ground_truth["inchikey"]
    assert any("inchikey recovered" in w.lower() for w in out.normalization_warnings)


def test_record_kept_when_exact_mass_recovered_from_smiles() -> None:
    rec = _make_record(exact_mass=None)
    out = normalize_record(rec)
    assert out is not None
    assert out.ground_truth["exact_mass"] is not None
    # Tyrosine exact mass is ~181.07, recovered from SMILES.
    assert out.ground_truth["exact_mass"] == pytest.approx(181.0739, abs=0.01)
    assert any("exact_mass recovered" in w.lower() for w in out.normalization_warnings)


def test_adduct_ion_mode_mismatch_warns_but_keeps_record() -> None:
    """[M+H]+ with ion_mode=negative — log a warning, trust ion_mode."""
    rec = _make_record(ion_mode_raw="NEGATIVE", precursor_type_raw="[M+H]+")
    out = normalize_record(rec)
    assert out is not None
    assert out.spectrum.ionization_mode == "negative"
    assert any("mismatch" in w for w in out.normalization_warnings)


def test_collision_energy_warning_propagated() -> None:
    rec = _make_record(collision_energy_raw="NCE 30")
    out = normalize_record(rec)
    assert out is not None
    assert out.spectrum.collision_energy == 30.0
    assert any("NCE" in w for w in out.normalization_warnings)


# ---------------------------------------------------------------------------
# normalize_record — happy path / shape checks
# ---------------------------------------------------------------------------


def test_record_happy_path_yields_valid_spectrum() -> None:
    rec = _make_record()
    out = normalize_record(rec)
    assert isinstance(out, NormalizedRecord)
    s = out.spectrum
    assert s.ionization_mode == "positive"
    assert s.adduct == "[M+H]+"
    assert s.collision_energy == 20.0
    assert s.precursor_mz == pytest.approx(182.0812)
    assert len(s.mz) == len(s.intensity) >= 5
    assert max(s.intensity) == pytest.approx(1.0)
    assert min(s.intensity) >= _NOISE_FLOOR
    # Ground truth contents
    assert out.ground_truth["smiles"] == rec.smiles
    assert out.ground_truth["inchikey"] == rec.inchikey
    assert out.ground_truth["primary_compound_name"] == "TestCompound"
    # Metadata
    assert out.metadata["accession"] == "MSBNK-TEST-001"
    assert out.metadata["instrument_type"] == "LC-ESI-Q-TOF"


def test_record_real_eawag_positive_normalises() -> None:
    """End-to-end: real Eawag EC001501 file → valid Spectrum."""
    rec = parse_massbank_record(FIXTURES / "MSBNK-EAWAG-EC001501.txt")
    out = normalize_record(rec)
    assert out is not None
    assert out.spectrum.ionization_mode == "positive"
    assert out.spectrum.adduct == "[M+H]+"
    # CE was "15 % (nominal)" → should yield 15.0 with NCE warning
    assert out.spectrum.collision_energy == 15.0
    assert any("NCE" in w for w in out.normalization_warnings)


def test_record_real_eawag_negative_normalises() -> None:
    rec = parse_massbank_record(FIXTURES / "MSBNK-EAWAG-EC001551.txt")
    out = normalize_record(rec)
    assert out is not None
    assert out.spectrum.ionization_mode == "negative"
    assert out.spectrum.adduct == "[M-H]-"


def test_record_real_riken_gc_dropped() -> None:
    """RIKEN GC-EI MS1 records have no precursor_mz → must be dropped."""
    rec = parse_massbank_record(FIXTURES / "MSBNK-RIKEN-PR010001.txt")
    assert normalize_record(rec) is None
