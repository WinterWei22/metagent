"""Unit tests for ``tools.benchmark.leakage_filter``.

Network-free: every test builds an in-memory ``.csv`` fixture with
``tmp_path`` and feeds it to :func:`build_leakage_filter`.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tools.benchmark.leakage_filter import (
    LeakageFilterError,
    LeakageFilterResult,
    _extract_riken_ids,
    build_leakage_filter,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_GNPS_COLUMNS = [
    "spectrum_id", "InChIKey_smiles", "Compound_Name",
    "Compound_Source", "GNPS_library_membership",
]


def _write_gnps_csv(path: Path, rows: list[dict]) -> Path:
    """Write a minimal GNPS-shaped CSV at ``path`` and return it."""
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_GNPS_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in _GNPS_COLUMNS})
    return path


def _query(*, source_id: str, inchikey: str) -> dict:
    """Build a benchmark query record in the legacy ``source_id`` shape."""
    return {"source_id": source_id, "ground_truth": {"inchikey": inchikey}}


def _query_metadata_shape(*, accession: str, inchikey: str) -> dict:
    """Build a query in the ``compound_pool_riken.jsonl`` (metadata.accession) shape."""
    return {
        "metadata": {"accession": accession},
        "ground_truth": {"inchikey": inchikey},
    }


# ---------------------------------------------------------------------------
# Trigger 1 — InChIKey first-block
# ---------------------------------------------------------------------------


def test_inchikey_first_block_match(tmp_path: Path) -> None:
    """Same first 14 chars, different stereo block → excluded."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        {
            "spectrum_id": "CCMSLIB_AAA",
            "InChIKey_smiles": "VVLXCWVSSLFQDS-BBBB-N",
            "Compound_Name": "Glutamyltyrosine (other stereo)",
            "GNPS_library_membership": "GNPS-LIBRARY",
        },
    ])
    queries = [_query(source_id="MSBNK-RIKEN-PR309407",
                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    res = build_leakage_filter(queries, csv_p)
    assert "CCMSLIB_AAA" in res.excluded_gnps_ids
    assert any("inchikey_first_block" in r for r in res.exclusion_reasons["CCMSLIB_AAA"])


def test_inchikey_full_match(tmp_path: Path) -> None:
    """Identical full InChIKey → still triggers first-block match."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        {"spectrum_id": "CCMSLIB_BBB",
         "InChIKey_smiles": "VVLXCWVSSLFQDS-AAAA-N"},
    ])
    queries = [_query(source_id="MSBNK-RIKEN-PR309407",
                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    res = build_leakage_filter(queries, csv_p)
    assert "CCMSLIB_BBB" in res.excluded_gnps_ids


def test_inchikey_different_first_block_not_excluded(tmp_path: Path) -> None:
    """Different compound (different first block) → not excluded."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        {"spectrum_id": "CCMSLIB_CCC",
         "InChIKey_smiles": "ZZZZZZZZZZZZZZ-AAAA-N",
         "Compound_Name": "Unrelated"},
    ])
    queries = [_query(source_id="MSBNK-RIKEN-PR309407",
                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    res = build_leakage_filter(queries, csv_p)
    assert "CCMSLIB_CCC" not in res.excluded_gnps_ids


# ---------------------------------------------------------------------------
# Trigger 2 — Cross-references
# ---------------------------------------------------------------------------


def test_cross_reference_msbnk_riken_format(tmp_path: Path) -> None:
    """spectrum_id literally is the MSBNK-RIKEN form (the dominant case)."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        {"spectrum_id": "MSBNK-RIKEN-PR309407",
         "InChIKey_smiles": ""},  # malformed inchikey on purpose — xref still catches
    ])
    queries = [_query(source_id="MSBNK-RIKEN-PR309407",
                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    res = build_leakage_filter(queries, csv_p)
    assert "MSBNK-RIKEN-PR309407" in res.excluded_gnps_ids
    rs = res.exclusion_reasons["MSBNK-RIKEN-PR309407"]
    assert any("exact_source_match" in r for r in rs)
    assert any("cross_reference_to_riken" in r for r in rs)


def test_cross_reference_alternative_format(tmp_path: Path) -> None:
    """Cross-ref with ``MassBank:PR309407`` / ``RIKEN PR309407`` text variants."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        # MassBank: form embedded in Compound_Name (hypothetical but the brief
        # asks for tolerance to this format)
        {"spectrum_id": "CCMSLIB_DDD",
         "InChIKey_smiles": "QQQQQQQQQQQQQQ-PPPP-N",
         "Compound_Name": "Curated from MassBank:PR309407 — Glutamyltyrosine"},
        # 'RIKEN PR309407' form embedded in Compound_Source
        {"spectrum_id": "CCMSLIB_EEE",
         "InChIKey_smiles": "RRRRRRRRRRRRRR-OOOO-N",
         "Compound_Source": "Re-imported from RIKEN PR309407"},
    ])
    queries = [_query(source_id="MSBNK-RIKEN-PR309407",
                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    res = build_leakage_filter(queries, csv_p)
    assert "CCMSLIB_DDD" in res.excluded_gnps_ids
    assert "CCMSLIB_EEE" in res.excluded_gnps_ids


def test_cross_reference_no_match_not_excluded(tmp_path: Path) -> None:
    """Different MSBNK ID (PR000001 vs PR309407) → not excluded."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        {"spectrum_id": "MSBNK-RIKEN-PR000001",
         "InChIKey_smiles": "QQQQQQQQQQQQQQ-AAAA-N",
         "Compound_Name": "Different compound"},
    ])
    queries = [_query(source_id="MSBNK-RIKEN-PR309407",
                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    res = build_leakage_filter(queries, csv_p)
    assert "MSBNK-RIKEN-PR000001" not in res.excluded_gnps_ids


# ---------------------------------------------------------------------------
# Trigger 3 — Exact source-id match
# ---------------------------------------------------------------------------


def test_exact_source_id_match(tmp_path: Path) -> None:
    """spec_id literally equals query source_id, even with cross_ref off."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        {"spectrum_id": "MSBNK-RIKEN-PR309407",
         "InChIKey_smiles": "ZZZZZZZZZZZZZZ-AAAA-N"},  # different first block
    ])
    queries = [_query(source_id="MSBNK-RIKEN-PR309407",
                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    res = build_leakage_filter(queries, csv_p, match_cross_references=False,
                                match_inchikey_first_block=False)
    assert "MSBNK-RIKEN-PR309407" in res.excluded_gnps_ids
    rs = res.exclusion_reasons["MSBNK-RIKEN-PR309407"]
    assert any("exact_source_match" in r for r in rs)


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_malformed_inchikey_handled_gracefully(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """``None`` / empty / too-short InChIKey on either side does not crash."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        # GNPS record with empty InChIKey
        {"spectrum_id": "CCMSLIB_BAD1", "InChIKey_smiles": ""},
        # GNPS record with too-short InChIKey
        {"spectrum_id": "CCMSLIB_BAD2", "InChIKey_smiles": "TOOSHORT"},
    ])
    queries = [
        _query(source_id="MSBNK-RIKEN-PR1", inchikey=""),       # empty query inchikey
        _query(source_id="MSBNK-RIKEN-PR2", inchikey="ABCDEFGHIJKLMN-AAAA-N"),
    ]
    # Should not raise.
    res = build_leakage_filter(queries, csv_p)
    assert isinstance(res, LeakageFilterResult)
    # Bad GNPS InChIKey records are tracked in stats.
    assert res.stats["gnps_with_malformed_inchikey"] == 2
    # Malformed query inchikey was logged.
    assert res.stats["queries_with_malformed_inchikey"] == 1


def test_audit_log_records_all_reasons(tmp_path: Path) -> None:
    """A record matched by both InChIKey AND cross-ref should log both."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        {"spectrum_id": "MSBNK-RIKEN-PR309407",
         "InChIKey_smiles": "VVLXCWVSSLFQDS-AAAA-N"},
    ])
    queries = [_query(source_id="MSBNK-RIKEN-PR309407",
                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    res = build_leakage_filter(queries, csv_p)
    rs = res.exclusion_reasons["MSBNK-RIKEN-PR309407"]
    assert any("inchikey_first_block" in r for r in rs)
    assert any("cross_reference_to_riken" in r for r in rs)
    assert any("exact_source_match" in r for r in rs)


def test_stats_correctness(tmp_path: Path) -> None:
    """All stat counters reflect the actual exclusions."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        # 1) only inchikey trigger
        {"spectrum_id": "CCMSLIB_X1", "InChIKey_smiles": "VVLXCWVSSLFQDS-XXXX-N"},
        # 2) only source-id + xref trigger (no inchikey)
        {"spectrum_id": "MSBNK-RIKEN-PR309407", "InChIKey_smiles": ""},
        # 3) all three triggers
        {"spectrum_id": "MSBNK-RIKEN-PR111", "InChIKey_smiles": "VVLXCWVSSLFQDS-YYYY-N"},
        # 4) nothing
        {"spectrum_id": "CCMSLIB_X2", "InChIKey_smiles": "ZZZZZZZZZZZZZZ-AAAA-N"},
    ])
    queries = [
        _query(source_id="MSBNK-RIKEN-PR309407", inchikey="VVLXCWVSSLFQDS-AAAA-N"),
        _query(source_id="MSBNK-RIKEN-PR111",    inchikey="VVLXCWVSSLFQDS-AAAA-N"),
    ]
    res = build_leakage_filter(queries, csv_p)
    s = res.stats
    assert s["total_gnps_records_scanned"] == 4
    assert s["total_query_records"] == 2
    assert s["excluded_by_inchikey_match"] == 2  # X1 + PR111
    assert s["excluded_by_cross_reference"] == 2  # PR309407 + PR111
    assert s["excluded_by_source_match"] == 2    # PR309407 + PR111
    assert s["total_excluded"] == 3              # X1, PR309407, PR111 — X2 stays


def test_query_metadata_accession_shape_works(tmp_path: Path) -> None:
    """Maintainer Q1: filter must accept compound_pool_riken.jsonl shape."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        {"spectrum_id": "MSBNK-RIKEN-PR309407",
         "InChIKey_smiles": "VVLXCWVSSLFQDS-AAAA-N"},
    ])
    queries = [_query_metadata_shape(accession="MSBNK-RIKEN-PR309407",
                                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    res = build_leakage_filter(queries, csv_p)
    assert "MSBNK-RIKEN-PR309407" in res.excluded_gnps_ids


# ---------------------------------------------------------------------------
# Wholesale library exclusion
# ---------------------------------------------------------------------------


def test_exclude_massbank_ml_export_optional_switch(tmp_path: Path) -> None:
    """``exclude_massbank_ml_export=True`` removes every MassBank_ML_Export."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        {"spectrum_id": "CCMSLIB_F1",
         "InChIKey_smiles": "AAAAAAAAAAAAAA-AAAA-N",
         "GNPS_library_membership": "MassBank_ML_Export"},
        {"spectrum_id": "CCMSLIB_F2",
         "InChIKey_smiles": "BBBBBBBBBBBBBB-BBBB-N",
         "GNPS_library_membership": "GNPS-LIBRARY"},
    ])
    queries = [_query(source_id="MSBNK-RIKEN-PR309407",
                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    # Off by default: neither is excluded (different inchikey, no xref).
    off = build_leakage_filter(queries, csv_p, exclude_massbank_ml_export=False)
    assert "CCMSLIB_F1" not in off.excluded_gnps_ids
    # On: F1 is wholesale-excluded.
    on = build_leakage_filter(queries, csv_p, exclude_massbank_ml_export=True)
    assert "CCMSLIB_F1" in on.excluded_gnps_ids
    assert "CCMSLIB_F2" not in on.excluded_gnps_ids
    assert any(
        "library_membership_excluded:MassBank_ML_Export" in r
        for r in on.exclusion_reasons["CCMSLIB_F1"]
    )


def test_additional_excluded_libraries(tmp_path: Path) -> None:
    """Arbitrary libraries can be wholesale-excluded too."""
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        {"spectrum_id": "CCMSLIB_M1",
         "InChIKey_smiles": "AAAAAAAAAAAAAA-AAAA-N",
         "GNPS_library_membership": "MONA_ML_Export"},
    ])
    queries = [_query(source_id="MSBNK-RIKEN-PR1",
                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    res = build_leakage_filter(queries, csv_p,
                                additional_excluded_libraries=["MONA_ML_Export"])
    assert "CCMSLIB_M1" in res.excluded_gnps_ids


# ---------------------------------------------------------------------------
# Performance smoke test
# ---------------------------------------------------------------------------


def test_large_pool_performance(tmp_path: Path) -> None:
    """1k queries × 10k GNPS records completes in < 5s."""
    import time

    rows = [
        {
            "spectrum_id": f"CCMSLIB_{i:08d}",
            # First-block hits 1 in every 10 query records (sparse leakage).
            "InChIKey_smiles": (
                f"QUERY_INCHIKEY_{i // 10:03d}-XXXX-N"
                if i % 10 == 0
                else f"NOMATCH_{i:09d}-XXXX-N"
            ),
            "Compound_Name": f"compound_{i}",
            "GNPS_library_membership": "GNPS-LIBRARY",
        }
        for i in range(10_000)
    ]
    csv_p = _write_gnps_csv(tmp_path / "big_gnps.csv", rows)

    queries = [
        _query(source_id=f"MSBNK-RIKEN-PR{i:06d}",
               inchikey=f"QUERY_INCHIKEY_{i:03d}-WWWW-N")
        for i in range(1000)
    ]
    t0 = time.monotonic()
    res = build_leakage_filter(queries, csv_p)
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0, f"perf regression: {elapsed:.2f}s for 1k×10k"
    assert res.stats["total_gnps_records_scanned"] == 10_000
    assert res.stats["total_query_records"] == 1000


# ---------------------------------------------------------------------------
# Helper-level tests
# ---------------------------------------------------------------------------


def test_extract_riken_ids_canonical_form() -> None:
    out = _extract_riken_ids("hello MSBNK-RIKEN-PR309407 world")
    assert out == ["MSBNK-RIKEN-PR309407"]


def test_extract_riken_ids_alternative_formats() -> None:
    a = _extract_riken_ids("Curated from MassBank:PR309407")
    b = _extract_riken_ids("re-imported from RIKEN PR309407")
    c = _extract_riken_ids("RIKEN-PR000001")
    assert "MSBNK-RIKEN-PR309407" in a
    assert "MSBNK-RIKEN-PR309407" in b
    assert "MSBNK-RIKEN-PR000001" in c


def test_extract_riken_ids_no_match() -> None:
    assert _extract_riken_ids("just random text", "ABC-123", "") == []


def test_empty_pool_raises(tmp_path: Path) -> None:
    csv_p = _write_gnps_csv(tmp_path / "gnps.csv", [
        {"spectrum_id": "CCMSLIB_X", "InChIKey_smiles": "AAAAAAAAAAAAAA-AAAA-N"},
    ])
    with pytest.raises(LeakageFilterError, match="empty"):
        build_leakage_filter([], csv_p)


def test_missing_library_path_raises(tmp_path: Path) -> None:
    queries = [_query(source_id="MSBNK-RIKEN-PR1",
                      inchikey="VVLXCWVSSLFQDS-AAAA-N")]
    with pytest.raises(LeakageFilterError, match="not found"):
        build_leakage_filter(queries, tmp_path / "nope.csv")
