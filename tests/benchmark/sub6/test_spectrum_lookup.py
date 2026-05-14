"""Unit tests for ``tools.benchmark.sub6.spectrum_lookup``.

Network-free: builds a fake GNPS mgf + a fake MassBank record on tmp_path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.benchmark.sub6.spectrum_lookup import (
    SpectrumPayload,
    build_spectrum_index,
    index_coverage,
)


# ---------------------------------------------------------------------------
# Fixtures: synthetic GNPS mgf + synthetic MassBank txt
# ---------------------------------------------------------------------------


def _write_gnps_mgf(path: Path, records: list[dict]) -> Path:
    """Write a tiny GNPS mgf (peaks + spectrum_id only — metadata via csv)."""
    lines: list[str] = []
    for r in records:
        lines.append("BEGIN IONS")
        lines.append(f"PEPMASS={r['precursor_mz']}")
        lines.append(f"TITLE={r['spectrum_id']}")
        lines.append(f"SPECTRUMID={r['spectrum_id']}")
        for mz, inten in r["peaks"]:
            lines.append(f"{mz} {inten}")
        lines.append("END IONS")
        lines.append("")
    path.write_text("\n".join(lines))
    return path


def _write_gnps_csv(path: Path, records: list[dict]) -> Path:
    """Write a tiny GNPS csv with metadata + InChIKey."""
    import csv as _csv
    with path.open("w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=[
            "spectrum_id", "Adduct", "Ion_Mode", "Precursor_MZ",
            "InChIKey_smiles", "Compound_Name", "GNPS_library_membership",
            "msMassAnalyzer", "msIonisation", "collision_energy",
        ])
        w.writeheader()
        for r in records:
            w.writerow({
                "spectrum_id": r["spectrum_id"],
                "Adduct": r["adduct"],
                "Ion_Mode": r["ion_mode"],
                "Precursor_MZ": r["precursor_mz"],
                "InChIKey_smiles": r["inchikey"],
                "Compound_Name": r.get("name", ""),
                "GNPS_library_membership": "GNPS-LIBRARY",
                "msMassAnalyzer": "qtof",
                "msIonisation": "ESI",
                "collision_energy": "",
            })
    return path


def _massbank_record_text(*, accession: str, contributor: str, inchikey: str,
                            n_peaks: int = 50, ion_mode: str = "POSITIVE",
                            ce: str = "20 eV") -> str:
    peaks_lines = "\n".join(f"  {100+i}.0 {1000-i*10}" for i in range(n_peaks))
    return (
        f"ACCESSION: {accession}\n"
        f"RECORD_TITLE: Test compound; LC-ESI-QTOF; MS2; CE:{ce}; [M+H]+\n"
        "AUTHORS: Test\n"
        "PUBLICATION: Test\n"
        "COPYRIGHT: Test\n"
        "DATE: 2026-04-30\n"
        f"CH$NAME: Test compound\n"
        f"CH$FORMULA: C2H6O\n"
        f"CH$EXACT_MASS: 46.0\n"
        f"CH$SMILES: CCO\n"
        f"CH$IUPAC: InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3\n"
        f"CH$LINK: INCHIKEY {inchikey}\n"
        f"AC$INSTRUMENT: Test QTOF\n"
        f"AC$INSTRUMENT_TYPE: LC-ESI-QTOF\n"
        f"AC$MASS_SPECTROMETRY: MS_TYPE MS2\n"
        f"AC$MASS_SPECTROMETRY: ION_MODE {ion_mode}\n"
        f"AC$MASS_SPECTROMETRY: COLLISION_ENERGY {ce}\n"
        f"MS$FOCUSED_ION: PRECURSOR_M/Z 200.0\n"
        f"MS$FOCUSED_ION: PRECURSOR_TYPE [M+H]+\n"
        f"PK$NUM_PEAK: {n_peaks}\n"
        "PK$PEAK: m/z int. rel.int.\n"
        f"{peaks_lines}\n"
        "//\n"
    )


@pytest.fixture
def fake_gnps_pair(tmp_path) -> tuple[Path, Path]:
    """Return (csv_path, mgf_path) — 3 records seeded into both."""
    records = [
        {"spectrum_id": "CCMSLIB_001",
         "name": "Compound A", "adduct": "[M+H]+", "ion_mode": "positive",
         "inchikey": "AAAAAAAAAAAAAA-AAAAAAAAAA-N",
         "precursor_mz": 200.0,
         "peaks": [(float(i), 1.0) for i in range(50)]},
        {"spectrum_id": "CCMSLIB_002",
         "name": "Compound A", "adduct": "[M+H]+", "ion_mode": "positive",
         "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-N",
         "precursor_mz": 200.0,
         "peaks": [(float(i), 1.0) for i in range(10)]},  # too few peaks
        {"spectrum_id": "CCMSLIB_003",
         "name": "Other", "adduct": "[M+H]+", "ion_mode": "positive",
         "inchikey": "ZZZZZZZZZZZZZZ-AAAAAAAAAA-N",
         "precursor_mz": 200.0,
         "peaks": [(float(i), 1.0) for i in range(50)]},
    ]
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", records)
    mgf_p = _write_gnps_mgf(tmp_path / "gnps.mgf", records)
    return csv_p, mgf_p


@pytest.fixture
def fake_massbank_root(tmp_path) -> Path:
    """Two MassBank records under one contributor directory."""
    root = tmp_path / "MassBank-data"
    contrib = root / "Athens_Univ"
    contrib.mkdir(parents=True)
    # In-target, qualifying
    (contrib / "MSBNK-Athens_Univ-001.txt").write_text(_massbank_record_text(
        accession="MSBNK-Athens_Univ-001", contributor="Athens_Univ",
        inchikey="BBBBBBBBBBBBBB-AAAAAAAAAA-N",
        n_peaks=50,
    ))
    # Out-of-target
    (contrib / "MSBNK-Athens_Univ-002.txt").write_text(_massbank_record_text(
        accession="MSBNK-Athens_Univ-002", contributor="Athens_Univ",
        inchikey="ZZZZZZZZZZZZZZ-AAAAAAAAAA-N",
        n_peaks=50,
    ))
    return root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_spectrum_index_gnps_only(fake_gnps_pair):
    """Pulls only spectra whose first-block matches AND meets quality."""
    csv_p, mgf_p = fake_gnps_pair
    targets = {"AAAAAAAAAAAAAA"}
    idx = build_spectrum_index(
        targets, gnps_csv_path=csv_p, gnps_mgf_path=mgf_p,
        require_peaks_min=30,
    )
    assert "AAAAAAAAAAAAAA" in idx
    payloads = idx["AAAAAAAAAAAAAA"]
    # CCMSLIB_001 passes (50 peaks); CCMSLIB_002 fails (10 peaks)
    assert len(payloads) == 1
    assert payloads[0].source_id == "CCMSLIB_001"
    assert payloads[0].source_db == "gnps"
    assert payloads[0].n_peaks == 50


def test_build_spectrum_index_massbank_only(fake_massbank_root):
    targets = {"BBBBBBBBBBBBBB"}
    idx = build_spectrum_index(
        targets, massbank_root=fake_massbank_root,
        massbank_contributors=("Athens_Univ",),
        require_peaks_min=30,
    )
    assert "BBBBBBBBBBBBBB" in idx
    payloads = idx["BBBBBBBBBBBBBB"]
    assert len(payloads) == 1
    assert payloads[0].source_db == "massbank"
    assert payloads[0].source_id == "MSBNK-Athens_Univ-001"


def test_build_spectrum_index_combined(fake_gnps_pair, fake_massbank_root):
    """Both sources merge into one index keyed by first-block."""
    csv_p, mgf_p = fake_gnps_pair
    targets = {"AAAAAAAAAAAAAA", "BBBBBBBBBBBBBB"}
    idx = build_spectrum_index(
        targets, gnps_csv_path=csv_p, gnps_mgf_path=mgf_p,
        massbank_root=fake_massbank_root,
        massbank_contributors=("Athens_Univ",),
        require_peaks_min=30,
    )
    cov = index_coverage(idx, targets)
    assert cov["n_targets"] == 2
    assert cov["n_covered"] == 2
    assert cov["total_spectra"] >= 2


def test_build_spectrum_index_empty_targets():
    assert build_spectrum_index(
        set(), gnps_csv_path="/nope.csv", gnps_mgf_path="/nope.mgf",
    ) == {}


def test_build_spectrum_index_gnps_requires_both_paths(fake_gnps_pair, caplog):
    """Passing only csv (no mgf) or only mgf (no csv) skips GNPS with a warning."""
    csv_p, _ = fake_gnps_pair
    idx = build_spectrum_index({"AAAAAAAAAAAAAA"}, gnps_csv_path=csv_p)
    assert idx == {}


def test_spectrum_payload_serializes(fake_gnps_pair):
    csv_p, mgf_p = fake_gnps_pair
    targets = {"AAAAAAAAAAAAAA"}
    idx = build_spectrum_index(
        targets, gnps_csv_path=csv_p, gnps_mgf_path=mgf_p,
        require_peaks_min=30,
    )
    payload = idx["AAAAAAAAAAAAAA"][0]
    d = payload.to_dict()
    # Required keys for downstream Sub-6A consumption
    for k in ("spectrum_id", "source_db", "source_id", "inchikey_first_block",
              "ion_mode", "adduct", "precursor_mz", "n_peaks", "peaks"):
        assert k in d
