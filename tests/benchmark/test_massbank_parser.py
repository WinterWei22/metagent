"""Unit tests for ``tools.benchmark.massbank_parser``."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.benchmark.massbank_parser import (
    MassBankParseError,
    MassBankRecord,
    _extract_inchikey_from_links,
    _extract_pubchem_cid,
    _extract_subkey,
    parse_massbank_directory,
    parse_massbank_record,
)


FIXTURES = Path(__file__).parent / "fixtures" / "massbank_records"


# ---------------------------------------------------------------------------
# Fixtures sanity
# ---------------------------------------------------------------------------


def test_fixtures_present() -> None:
    """If real-data fixtures vanish the rest of the suite is meaningless."""
    expected = {
        "MSBNK-RIKEN-PR010001.txt",
        "MSBNK-RIKEN-PR010014.txt",
        "MSBNK-EAWAG-EC001501.txt",
        "MSBNK-EAWAG-EC001551.txt",
        "synthetic_continuation.txt",
        "broken_no_terminator.txt",
        "broken_malformed_peaks.txt",
    }
    have = {p.name for p in FIXTURES.glob("*.txt")}
    assert expected <= have, f"missing fixtures: {expected - have}"


# ---------------------------------------------------------------------------
# Single-record parsing — real files
# ---------------------------------------------------------------------------


def test_parse_eawag_positive_mode() -> None:
    """EAWAG-EC001501: LC-ESI-QFT MS2 [M+H]+ — the canonical positive case."""
    rec = parse_massbank_record(FIXTURES / "MSBNK-EAWAG-EC001501.txt")
    assert isinstance(rec, MassBankRecord)
    assert rec.accession == "MSBNK-EAWAG-EC001501"
    assert "Nocuolin A" in rec.compound_names
    # Three CH$NAME entries should all be retained.
    assert len(rec.compound_names) == 3
    assert rec.formula == "C16H30N2O3"
    assert rec.exact_mass == pytest.approx(298.2256428)
    assert rec.smiles == "CCCCCC1CC(CCCCC)=NN(C(CCO)=O)O1"
    assert rec.inchikey == "MPGIDXBHXRMMSY-UHFFFAOYSA-N"
    assert rec.pubchem_cid == 129017397
    assert rec.instrument == "Exploris 240 Thermo Scientific"
    assert rec.instrument_type == "LC-ESI-QFT"
    assert rec.ms_level == "MS2"
    assert rec.ion_mode_raw == "POSITIVE"
    # CE form is "15 % (nominal)" — left raw for normaliser
    assert rec.collision_energy_raw is not None
    assert "15" in rec.collision_energy_raw
    assert rec.precursor_mz == pytest.approx(299.2329)
    assert rec.precursor_type_raw == "[M+H]+"
    assert rec.num_peaks > 0
    assert len(rec.peaks) == rec.num_peaks
    # Peaks should NOT include PK$ANNOTATION rows (which had different schema)
    for mz, intensity in rec.peaks:
        assert mz > 0 and intensity >= 0
    # Contributor parsed from the MSBNK-EAWAG-* filename
    assert rec.contributor == "EAWAG"
    assert rec.parse_warnings == []  # clean record


def test_parse_eawag_negative_mode() -> None:
    """EAWAG-EC001551: same compound but [M-H]- in negative mode."""
    rec = parse_massbank_record(FIXTURES / "MSBNK-EAWAG-EC001551.txt")
    assert rec.ion_mode_raw == "NEGATIVE"
    assert rec.precursor_type_raw == "[M-H]-"
    assert rec.precursor_mz == pytest.approx(297.2184)


def test_parse_riken_record_with_multiple_names() -> None:
    """RIKEN-PR010014 (Glycine) has three CH$NAME entries."""
    rec = parse_massbank_record(FIXTURES / "MSBNK-RIKEN-PR010014.txt")
    assert rec.accession == "MSBNK-RIKEN-PR010014"
    assert rec.compound_names == ["Glycine", "Aminoacetic acid", "Gly"]
    assert rec.smiles == "NCC(O)=O"
    assert rec.inchikey == "DHMQDGOQFOQNFH-UHFFFAOYSA-N"
    # GC-EI MS1 — important: ms_level is "MS", not "MS2"
    assert rec.ms_level == "MS"
    # No PRECURSOR_M/Z in GC-EI records
    assert rec.precursor_mz is None
    assert rec.precursor_type_raw is None


def test_parse_riken_gc_ei_record() -> None:
    """RIKEN-PR010001: 1,3-Diaminopropane GC-EI-TOF — exercises GC quirks.

    GC records have no PRECURSOR_M/Z and no COLLISION_ENERGY but DO have
    peaks. The normaliser will reject these later; here we just confirm we
    parsed without crashing.
    """
    rec = parse_massbank_record(FIXTURES / "MSBNK-RIKEN-PR010001.txt")
    assert rec.accession == "MSBNK-RIKEN-PR010001"
    assert rec.smiles == "NCCCN"
    assert rec.precursor_mz is None
    assert rec.collision_energy_raw is None
    assert len(rec.peaks) > 0
    assert rec.num_peaks == len(rec.peaks)


# ---------------------------------------------------------------------------
# Single-record parsing — synthetic edge cases
# ---------------------------------------------------------------------------


def test_parse_record_with_continuation_lines() -> None:
    """Multi-line values (COMMENT, CH$NAME, CH$IUPAC) must be folded."""
    rec = parse_massbank_record(FIXTURES / "synthetic_continuation.txt")
    assert rec.accession == "SYNTH-CONT-0001"
    # COMMENT spans 3 lines — joined into one
    # We don't expose COMMENT directly; instead check the multi-line CH$NAME.
    assert rec.compound_names[0] == (
        "Synthetic test compound with a deliberately "
        "long name that wraps onto a second line"
    )
    assert rec.compound_names[1] == "AltName-2"
    # CH$IUPAC continuation
    assert rec.inchi is not None
    assert "10H2,(H,12,13)" in rec.inchi
    # PK$ANNOTATION rows must NOT appear in peaks
    assert (91.0540, 1.0) not in rec.peaks  # annotation row had different intensity
    # PK$PEAK rows are present
    assert any(abs(mz - 91.0540) < 1e-4 for mz, _ in rec.peaks)
    assert rec.num_peaks == 5
    assert len(rec.peaks) == 5


def test_parse_record_negative_mode_and_negative_adduct() -> None:
    """[M-H]- adduct preserved verbatim."""
    rec = parse_massbank_record(FIXTURES / "MSBNK-EAWAG-EC001551.txt")
    assert rec.precursor_type_raw == "[M-H]-"
    assert rec.ion_mode_raw == "NEGATIVE"


def test_parse_record_missing_smiles(tmp_path: Path) -> None:
    """Records with no CH$SMILES still parse; smiles is None."""
    p = tmp_path / "no_smiles.txt"
    p.write_text(
        "ACCESSION: MSBNK-TEST-NOSMI\n"
        "RECORD_TITLE: No SMILES test\n"
        "CH$NAME: SmilesGap\n"
        "CH$FORMULA: C1H2\n"
        "AC$MASS_SPECTROMETRY: MS_TYPE MS2\n"
        "AC$MASS_SPECTROMETRY: ION_MODE POSITIVE\n"
        "MS$FOCUSED_ION: PRECURSOR_M/Z 17.026\n"
        "MS$FOCUSED_ION: PRECURSOR_TYPE [M+H]+\n"
        "PK$NUM_PEAK: 1\n"
        "PK$PEAK: m/z int. rel.int.\n"
        "  17 1 1\n"
        "//\n"
    )
    rec = parse_massbank_record(p)
    assert rec.smiles is None
    assert rec.inchikey is None
    assert rec.pubchem_cid is None
    assert rec.peaks == [(17.0, 1.0)]


def test_parse_record_no_terminator_logs_warning() -> None:
    """Missing ``//`` is not fatal but is reported as a warning."""
    rec = parse_massbank_record(FIXTURES / "broken_no_terminator.txt")
    assert rec.accession == "SYNTH-BAD-NO-TERMINATOR"
    assert any("terminator" in w for w in rec.parse_warnings)


def test_parse_record_malformed_peaks_collected_as_warnings() -> None:
    """Non-numeric peak rows produce warnings but parser does not abort."""
    rec = parse_massbank_record(FIXTURES / "broken_malformed_peaks.txt")
    # Only the last well-formed row should be in peaks.
    assert (100.0, 5.0) in rec.peaks
    assert len(rec.peaks) == 1
    assert any("unparseable" in w for w in rec.parse_warnings)


def test_parse_record_no_accession_raises(tmp_path: Path) -> None:
    """No ``ACCESSION`` line → :class:`MassBankParseError`."""
    p = tmp_path / "no_accession.txt"
    p.write_text("RECORD_TITLE: garbage\n//\n")
    with pytest.raises(MassBankParseError, match="no ACCESSION"):
        parse_massbank_record(p)


def test_parse_nonexistent_file_raises(tmp_path: Path) -> None:
    with pytest.raises(MassBankParseError, match="cannot read"):
        parse_massbank_record(tmp_path / "nope.txt")


# ---------------------------------------------------------------------------
# Helper-level tests
# ---------------------------------------------------------------------------


def test_extract_subkey() -> None:
    vs = ["MS_TYPE MS2", "ION_MODE POSITIVE", "COLLISION_ENERGY 35 eV"]
    assert _extract_subkey(vs, "MS_TYPE") == "MS2"
    assert _extract_subkey(vs, "ION_MODE") == "POSITIVE"
    assert _extract_subkey(vs, "COLLISION_ENERGY") == "35 eV"
    assert _extract_subkey(vs, "MISSING") is None


def test_extract_subkey_picks_first_match() -> None:
    """If a sub-tag appears twice, the first is returned."""
    vs = ["ION_MODE POSITIVE", "ION_MODE NEGATIVE"]
    assert _extract_subkey(vs, "ION_MODE") == "POSITIVE"


def test_extract_inchikey_explicit() -> None:
    links = ["CAS 12345", "INCHIKEY DHMQDGOQFOQNFH-UHFFFAOYSA-N", "PUBCHEM CID:750"]
    assert _extract_inchikey_from_links(links) == "DHMQDGOQFOQNFH-UHFFFAOYSA-N"


def test_extract_inchikey_fallback_regex_on_unrecognised_format() -> None:
    """If the sub-tag is missing but a hash is present, regex still finds it."""
    links = ["PUBCHEM 750", "Notes: see ABCDEFGHIJKLMN-OPQRSTUVWX-Y for details"]
    assert _extract_inchikey_from_links(links) == "ABCDEFGHIJKLMN-OPQRSTUVWX-Y"


def test_extract_pubchem_cid_variants() -> None:
    assert _extract_pubchem_cid(["PUBCHEM CID:750"]) == 750
    assert _extract_pubchem_cid(["PUBCHEM CID 750"]) == 750
    assert _extract_pubchem_cid(["PUBCHEM 750"]) == 750
    assert _extract_pubchem_cid(["CAS 12345"]) is None
    assert _extract_pubchem_cid([]) is None


# ---------------------------------------------------------------------------
# Directory iteration
# ---------------------------------------------------------------------------


def test_parse_directory_yields_all_valid_records() -> None:
    """Iterator yields one record per .txt and skips fatal errors silently."""
    records = list(parse_massbank_directory(FIXTURES))
    accs = {r.accession for r in records}
    assert "MSBNK-EAWAG-EC001501" in accs
    assert "MSBNK-EAWAG-EC001551" in accs
    assert "MSBNK-RIKEN-PR010014" in accs
    assert "SYNTH-CONT-0001" in accs
    # broken_no_terminator and broken_malformed_peaks parse OK (with warnings)
    # only files without ACCESSION would be skipped.


def test_parse_directory_skips_malformed(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """File with no ACCESSION is skipped; rest still produced."""
    (tmp_path / "good.txt").write_text(
        "ACCESSION: GOOD\nRECORD_TITLE: t\nCH$NAME: x\nPK$NUM_PEAK: 0\n//\n"
    )
    (tmp_path / "bad.txt").write_text("RECORD_TITLE: garbage\n//\n")
    accs = [r.accession for r in parse_massbank_directory(tmp_path)]
    assert accs == ["GOOD"]
    assert "bad.txt" in caplog.text


def test_parse_directory_contributor_filter(tmp_path: Path) -> None:
    """``contributor_filter`` limits which files we parse."""
    (tmp_path / "MSBNK-RIKEN-FOO.txt").write_text(
        "ACCESSION: MSBNK-RIKEN-FOO\nCH$NAME: A\n//\n"
    )
    (tmp_path / "MSBNK-EAWAG-BAR.txt").write_text(
        "ACCESSION: MSBNK-EAWAG-BAR\nCH$NAME: B\n//\n"
    )
    accs = [r.accession for r in parse_massbank_directory(tmp_path, ["RIKEN"])]
    assert accs == ["MSBNK-RIKEN-FOO"]


def test_parse_directory_progress_callback(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("ACCESSION: A\n//\n")
    (tmp_path / "b.txt").write_text("ACCESSION: B\n//\n")
    seen: list[tuple[int, int]] = []
    list(parse_massbank_directory(
        tmp_path, progress_callback=lambda p, t: seen.append((p, t))
    ))
    assert seen == [(1, 2), (2, 2)]


def test_parse_nonexistent_directory_raises() -> None:
    with pytest.raises(MassBankParseError, match="not a directory"):
        list(parse_massbank_directory("/nope/does-not-exist"))
