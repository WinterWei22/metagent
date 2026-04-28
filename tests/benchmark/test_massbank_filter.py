"""Unit tests for ``tools.benchmark.massbank_filter``.

ClassyFire is mocked / disabled in these tests — the real network path is
exercised only by the smoke-test deliverable.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from schemas.common import Spectrum
from tools.benchmark.massbank_filter import (
    CompoundPool,
    CompoundPoolIOError,
    FilterCriteria,
    build_compound_pool,
    classify_compound,
    filter_records,
)
from tools.benchmark.massbank_normalizer import NormalizedRecord


# ---------------------------------------------------------------------------
# Helpers — synthesise NormalizedRecords directly.
# ---------------------------------------------------------------------------


def _make_normalized(
    *,
    smiles: str = "N[C@@H](Cc1ccc(O)cc1)C(=O)O",
    inchikey: str | None = "OUYCCCASQSFEME-QMMMGPOBSA-N",
    formula: str = "C9H11NO3",
    ion_mode: str = "positive",
    adduct: str = "[M+H]+",
    precursor_mz: float = 182.0812,
    n_peaks: int = 20,
    instrument_type: str = "LC-ESI-Q-TOF",
    contributor: str = "RIKEN",
    ms_level: str = "MS2",
) -> NormalizedRecord:
    mz = [100.0 + i for i in range(n_peaks)]
    intensity = [1.0] + [0.5] * (n_peaks - 1)
    spectrum = Spectrum(
        mz=mz, intensity=intensity, precursor_mz=precursor_mz,
        adduct=adduct, ionization_mode=ion_mode,
        collision_energy=20.0,
    )
    return NormalizedRecord(
        spectrum=spectrum,
        ground_truth={
            "smiles": smiles,
            "inchikey": inchikey,
            "molecular_formula": formula,
            "exact_mass": 181.0739,
            "compound_names": ["Test"],
            "primary_compound_name": "Test",
            "pubchem_cid": None,
            "inchi": None,
        },
        metadata={
            "accession": "MSBNK-TEST-1",
            "record_title": "t",
            "contributor": contributor,
            "instrument": "Synthetic",
            "instrument_type": instrument_type,
            "ms_level": ms_level,
            "source_file": None,
        },
        normalization_warnings=[],
    )


# ---------------------------------------------------------------------------
# filter_records
# ---------------------------------------------------------------------------


def test_filter_by_ion_mode() -> None:
    recs = [
        _make_normalized(ion_mode="positive", adduct="[M+H]+"),
        _make_normalized(ion_mode="negative", adduct="[M-H]-"),
    ]
    out = filter_records(recs, FilterCriteria(ion_mode=["positive"]))
    assert len(out) == 1
    assert out[0].spectrum.ionization_mode == "positive"


def test_filter_by_min_peaks() -> None:
    recs = [
        _make_normalized(n_peaks=20),
        _make_normalized(n_peaks=10),  # below default 15
    ]
    out = filter_records(recs, FilterCriteria())
    assert len(out) == 1


def test_filter_by_precursor_mz_range() -> None:
    recs = [
        _make_normalized(precursor_mz=150.0),
        _make_normalized(precursor_mz=850.0),  # above default 800
        _make_normalized(precursor_mz=50.0),   # below default 100
    ]
    out = filter_records(recs, FilterCriteria())
    assert len(out) == 1
    assert out[0].spectrum.precursor_mz == 150.0


def test_filter_by_contributor() -> None:
    recs = [
        _make_normalized(contributor="RIKEN"),
        _make_normalized(contributor="EAWAG"),
    ]
    out = filter_records(recs, FilterCriteria(contributors=["RIKEN"]))
    assert len(out) == 1
    assert out[0].metadata["contributor"] == "RIKEN"

    # Case-insensitive
    out2 = filter_records(recs, FilterCriteria(contributors=["riken"]))
    assert len(out2) == 1


def test_filter_by_instrument_type_substring() -> None:
    """Instrument filter is substring-based to handle naming variation."""
    recs = [
        _make_normalized(instrument_type="LC-ESI-Q-TOF"),
        _make_normalized(instrument_type="LC-ESI-QFT"),  # Eawag variant of Orbitrap
        _make_normalized(instrument_type="GC-EI-TOF"),
    ]
    out = filter_records(recs, FilterCriteria(instrument_types=["Q-TOF", "QFT", "Orbitrap"]))
    assert len(out) == 2
    assert all("GC" not in r.metadata["instrument_type"] for r in out)


def test_filter_by_ms_level() -> None:
    recs = [
        _make_normalized(ms_level="MS2"),
        _make_normalized(ms_level="MS"),
    ]
    out = filter_records(recs, FilterCriteria(ms_level=["MS2"]))
    assert len(out) == 1


def test_filter_combined_criteria() -> None:
    """All criteria are AND-combined."""
    good = _make_normalized()  # passes everything
    bad_mode = _make_normalized(ion_mode="negative", adduct="[M-H]-")
    bad_inst = _make_normalized(instrument_type="GC-EI-TOF")
    out = filter_records(
        [good, bad_mode, bad_inst],
        FilterCriteria(
            ion_mode=["positive"],
            instrument_types=["Q-TOF"],
            ms_level=["MS2"],
        ),
    )
    assert len(out) == 1


def test_filter_streaming_with_iterator() -> None:
    """Filter must accept a generator (not just a list)."""
    def gen():
        yield _make_normalized()
        yield _make_normalized(ion_mode="negative", adduct="[M-H]-")
    out = filter_records(gen(), FilterCriteria(ion_mode=["positive"]))
    assert len(out) == 1


# ---------------------------------------------------------------------------
# classify_compound — SMARTS fallback (offline)
# ---------------------------------------------------------------------------


def test_classify_compound_amino_acid_smarts() -> None:
    """L-tyrosine via SMARTS fallback."""
    label = classify_compound(
        "N[C@@H](Cc1ccc(O)cc1)C(=O)O",
        inchikey="OUYCCCASQSFEME-QMMMGPOBSA-N",
        use_classyfire=False,
    )
    assert label == "amino_acid"


def test_classify_compound_organic_acid_smarts() -> None:
    """Citric acid via SMARTS fallback."""
    label = classify_compound("OC(=O)CC(O)(CC(=O)O)C(=O)O", use_classyfire=False)
    assert label == "organic_acid"


def test_classify_compound_flavonoid_smarts() -> None:
    """Quercetin via SMARTS fallback."""
    label = classify_compound(
        "c1cc(O)c(O)cc1-c1oc2cc(O)cc(O)c2c(=O)c1O",
        use_classyfire=False,
    )
    assert label == "flavonoid"


def test_classify_compound_lipid_smarts() -> None:
    """Palmitic acid (long chain + COOH) via SMARTS fallback."""
    label = classify_compound("CCCCCCCCCCCCCCCC(=O)O", use_classyfire=False)
    assert label == "lipid"


def test_classify_compound_invalid_smiles_returns_none() -> None:
    assert classify_compound("not a molecule", use_classyfire=False) is None
    assert classify_compound("", use_classyfire=False) is None
    assert classify_compound(None, use_classyfire=False) is None


def test_classify_compound_unknown_returns_other() -> None:
    """Random non-class molecule (benzene) returns ``"other"``."""
    label = classify_compound("c1ccccc1", use_classyfire=False)
    assert label == "other"


# ---------------------------------------------------------------------------
# classify_compound — ClassyFire path (mocked)
# ---------------------------------------------------------------------------


def test_classify_compound_uses_classyfire_when_available() -> None:
    """If ClassyFire returns 'flavonoid', we accept that even if SMARTS would disagree."""
    fake_resp = mock.Mock(all_classifications=["organic compounds", "flavonoids", "flavones"])
    with mock.patch(
        "tools.classyfire.tool.classify_structure", return_value=fake_resp
    ):
        label = classify_compound("CCCCCCCCCCCCCCCC(=O)O", inchikey="ABCDEFGHIJKLMN-OPQRSTUVWX-Y")
    assert label == "flavonoid"


def test_classify_compound_classyfire_failure_falls_back_to_smarts() -> None:
    """If ClassyFire raises, fallback path is taken."""
    with mock.patch(
        "tools.classyfire.tool.classify_structure", side_effect=RuntimeError("api down")
    ):
        label = classify_compound(
            "CCCCCCCCCCCCCCCC(=O)O", inchikey="ABCDEFGHIJKLMN-OPQRSTUVWX-Y"
        )
    assert label == "lipid"


def test_classify_compound_classyfire_returns_other_when_no_match() -> None:
    """ClassyFire taxonomy doesn't fall in our 6 buckets → ``"other"``."""
    fake_resp = mock.Mock(all_classifications=["organic compounds", "hydrocarbons", "alkanes"])
    with mock.patch(
        "tools.classyfire.tool.classify_structure", return_value=fake_resp
    ):
        label = classify_compound("CCCCC", inchikey="ABCDEFGHIJKLMN-OPQRSTUVWX-Y")
    assert label == "other"


# ---------------------------------------------------------------------------
# CompoundPool
# ---------------------------------------------------------------------------


def test_compound_pool_by_class() -> None:
    aa = _make_normalized()
    aa.ground_truth["compound_class"] = "amino_acid"
    flav = _make_normalized()
    flav.ground_truth["compound_class"] = "flavonoid"
    pool = CompoundPool([aa, flav])
    assert len(pool.by_class("amino_acid")) == 1
    assert len(pool.by_class("flavonoid")) == 1
    assert len(pool.by_class("alkaloid")) == 0


def test_compound_pool_by_mode() -> None:
    pos = _make_normalized()
    neg = _make_normalized(ion_mode="negative", adduct="[M-H]-")
    pool = CompoundPool([pos, neg])
    assert len(pool.by_mode("positive")) == 1
    assert len(pool.by_mode("negative")) == 1


def test_compound_pool_stats_format() -> None:
    aa_pos = _make_normalized()
    aa_pos.ground_truth["compound_class"] = "amino_acid"
    flav_neg = _make_normalized(ion_mode="negative", adduct="[M-H]-", contributor="EAWAG")
    flav_neg.ground_truth["compound_class"] = "flavonoid"
    pool = CompoundPool([aa_pos, flav_neg])
    stats = pool.stats()

    assert stats["total"] == 2
    assert stats["by_mode"] == {"positive": 1, "negative": 1}
    assert stats["by_class"] == {"amino_acid": 1, "flavonoid": 1}
    assert stats["by_contributor"] == {"RIKEN": 1, "EAWAG": 1}
    assert "positive|amino_acid" in stats["by_mode_class"]
    assert stats["by_mode_class"]["positive|amino_acid"] == 1


def test_compound_pool_save_load_roundtrip(tmp_path: Path) -> None:
    rec = _make_normalized()
    rec.ground_truth["compound_class"] = "amino_acid"
    rec.normalization_warnings.append("test warning")

    pool = CompoundPool([rec])
    out_path = tmp_path / "pool.jsonl"
    pool.save(out_path)
    assert out_path.exists()

    loaded = CompoundPool.load(out_path)
    assert len(loaded) == 1
    r = loaded.records[0]
    assert r.spectrum.ionization_mode == "positive"
    assert r.spectrum.adduct == "[M+H]+"
    assert r.spectrum.mz == rec.spectrum.mz
    assert r.spectrum.intensity == rec.spectrum.intensity
    assert r.ground_truth["compound_class"] == "amino_acid"
    assert r.metadata["contributor"] == "RIKEN"
    assert "test warning" in r.normalization_warnings


def test_compound_pool_load_bad_path_raises(tmp_path: Path) -> None:
    with pytest.raises(CompoundPoolIOError, match="failed to read"):
        CompoundPool.load(tmp_path / "nope.jsonl")


def test_compound_pool_load_bad_jsonl_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    p.write_text("this is not json\n")
    with pytest.raises(CompoundPoolIOError, match="failed to parse"):
        CompoundPool.load(p)


# ---------------------------------------------------------------------------
# build_compound_pool
# ---------------------------------------------------------------------------


def test_build_compound_pool_classifies_each_record() -> None:
    recs = [_make_normalized(), _make_normalized(smiles="OC(=O)CC(O)(CC(=O)O)C(=O)O")]
    pool = build_compound_pool(recs, classify=True, use_classyfire=False)
    classes = [r.ground_truth.get("compound_class") for r in pool.records]
    assert classes[0] == "amino_acid"
    assert classes[1] == "organic_acid"


def test_build_compound_pool_skip_classify() -> None:
    recs = [_make_normalized()]
    pool = build_compound_pool(recs, classify=False)
    assert "compound_class" not in pool.records[0].ground_truth


def test_build_compound_pool_consumes_iterator() -> None:
    """Iterator input — pool builder must handle generators."""
    def gen():
        yield _make_normalized()
        yield _make_normalized(smiles="OC(=O)CC(O)(CC(=O)O)C(=O)O")
    pool = build_compound_pool(gen(), classify=True, use_classyfire=False)
    assert len(pool) == 2
