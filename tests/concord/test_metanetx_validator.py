"""Unit tests for MetaNetX cross-namespace validator (W4 D3).

Spec: ≥6 case.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.schema.enrichment import CompoundRef
from concord.validate.metanetx_validator import (
    ConflictRecord,
    ValidationReport,
    validate_cross_namespace_consistency,
)


def _make_test_db(tmp_path: Path) -> Path:
    """Build a tiny MetaNetX-shaped sqlite with hand-crafted conflict cases."""
    db = tmp_path / "metanetx_test.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE mnx_compound (
            mnx_id TEXT PRIMARY KEY, name TEXT, formula TEXT, charge INTEGER,
            inchikey TEXT, inchikey_block14 TEXT
        );
        CREATE TABLE mnx_xref (
            mnx_id TEXT NOT NULL, external_ns TEXT NOT NULL, external_id TEXT NOT NULL
        );
        CREATE INDEX idx ON mnx_xref(external_ns, external_id);
    """)
    # Two MNX compounds with different block14 (critical conflict scenario)
    conn.executemany(
        "INSERT INTO mnx_compound VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("MNXM0001", "compound A", "C6H12O6",  0, "AAAAAAAAAAAAAA-XYZ-N", "AAAAAAAAAAAAAA"),
            ("MNXM0002", "compound A neutral", "C6H12O6",  0, "BBBBBBBBBBBBBB-XYZ-N", "BBBBBBBBBBBBBB"),
            ("MNXM0003", "compound B salt-shift", "C6H11O6", -1, "CCCCCCCCCCCCCC-XYZ-M", "CCCCCCCCCCCCCC"),
            ("MNXM0004", "compound B neutral",   "C6H12O6",  0, "CCCCCCCCCCCCCC-XYZ-N", "CCCCCCCCCCCCCC"),
        ],
    )
    # Xref scenarios:
    # Compound A: ChEBI:111 → MNXM0001, HMDB:HMDB001 → MNXM0001 (consistent)
    # Compound B: ChEBI:222 → MNXM0001, HMDB:HMDB002 → MNXM0002 (critical: differ block14)
    # Compound C: ChEBI:333 → MNXM0003, HMDB:HMDB003 → MNXM0004 (warning: same block14, different charge)
    # Compound D: ChEBI:444 → MNXM0001 (single-ns)
    # Compound E: ChEBI:999 (not in MNX) → uncoverable
    conn.executemany(
        "INSERT INTO mnx_xref VALUES (?, ?, ?)",
        [
            ("MNXM0001", "CHEBI", "111"),
            ("MNXM0001", "HMDB",  "HMDB001"),
            ("MNXM0001", "CHEBI", "222"),
            ("MNXM0002", "HMDB",  "HMDB002"),
            ("MNXM0003", "CHEBI", "333"),
            ("MNXM0004", "HMDB",  "HMDB003"),
            ("MNXM0001", "CHEBI", "444"),
        ],
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture(scope="module")
def fake_db(tmp_path_factory) -> Path:
    return _make_test_db(tmp_path_factory.mktemp("mnx_test"))


def _ref(chebi=None, hmdb=None, kegg=None, lipidmaps=None):
    ik = "ZZZZZZZZZZZZZZ-AAAAAAAAA-N"  # dummy required field
    return CompoundRef(
        primary_id=f"CHEBI:{chebi}" if chebi else "INCHIKEY:" + ik,
        inchikey=ik,
        display_name="test",
        chebi_id=f"CHEBI:{chebi}" if chebi else None,
        hmdb_id=f"HMDB:{hmdb}" if hmdb else None,
        kegg_compound_id=f"KEGG:{kegg}" if kegg else None,
        lipidmaps_id=f"LIPIDMAPS:{lipidmaps}" if lipidmaps else None,
    )


def test_consistent_cross_namespace(fake_db):
    """Compound A: ChEBI:111 + HMDB:HMDB001 both → MNXM0001."""
    ref = _ref(chebi="111", hmdb="HMDB001")
    rep = validate_cross_namespace_consistency([ref], db_path=fake_db)
    assert rep.n_total == 1
    assert rep.n_consistent == 1
    assert rep.n_inconsistent == 0
    assert len(rep.conflicts) == 0


def test_critical_conflict_different_block14(fake_db):
    """Compound B: ChEBI:222 → MNXM0001 (AAA…), HMDB:HMDB002 → MNXM0002 (BBB…)."""
    ref = _ref(chebi="222", hmdb="HMDB002")
    rep = validate_cross_namespace_consistency([ref], db_path=fake_db)
    assert rep.n_inconsistent == 1
    assert len(rep.conflicts) == 1
    assert rep.conflicts[0].severity == "critical"
    assert len(rep.conflicts[0].inchikey_block14s) == 2


def test_warning_conflict_same_block14(fake_db):
    """Compound C: ChEBI:333 → MNXM0003, HMDB:HMDB003 → MNXM0004 (same CCC… block14)."""
    ref = _ref(chebi="333", hmdb="HMDB003")
    rep = validate_cross_namespace_consistency([ref], db_path=fake_db)
    assert rep.n_inconsistent == 1
    assert len(rep.conflicts) == 1
    assert rep.conflicts[0].severity == "warning"


def test_single_namespace_no_conflict(fake_db):
    """Compound D: ChEBI:444 alone — counts as consistent (trivially)."""
    ref = _ref(chebi="444")
    rep = validate_cross_namespace_consistency([ref], db_path=fake_db)
    assert rep.n_consistent == 1
    assert rep.n_inconsistent == 0


def test_uncoverable_metabolite(fake_db):
    """Compound E: ChEBI:999 not in MNX → uncoverable, not conflict."""
    ref = _ref(chebi="999")
    rep = validate_cross_namespace_consistency([ref], db_path=fake_db)
    assert rep.n_uncoverable == 1
    assert rep.n_inconsistent == 0


def test_empty_list(fake_db):
    rep = validate_cross_namespace_consistency([], db_path=fake_db)
    assert rep.n_total == 0
    assert rep.summary()["n_total"] == 0


def test_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="MetaNetX"):
        validate_cross_namespace_consistency([], db_path=tmp_path / "no.sqlite")


def test_aggregate_mixed_batch(fake_db):
    """All 5 scenarios in one batch."""
    refs = [
        _ref(chebi="111", hmdb="HMDB001"),    # consistent
        _ref(chebi="222", hmdb="HMDB002"),    # critical
        _ref(chebi="333", hmdb="HMDB003"),    # warning
        _ref(chebi="444"),                     # single ns / consistent
        _ref(chebi="999"),                     # uncoverable
    ]
    rep = validate_cross_namespace_consistency(refs, db_path=fake_db)
    s = rep.summary()
    assert s["n_total"] == 5
    assert s["n_consistent"] == 2
    assert s["n_inconsistent"] == 2
    assert s["n_uncoverable"] == 1
    assert s["n_critical_conflicts"] == 1
    assert s["n_warning_conflicts"] == 1
