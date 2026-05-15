"""Unit tests for `concord.lookup.chebi.ChebiLookup` (W3 D3).

Requires:`data/concord/chebi.sqlite` already ETL'd
        (`python -m concord.etl.chebi_etl --with-isa`).

Covers W3 D3 unit-test checklist:
  - 4 lookup functions × happy path
  - get_compound on non-existent ID returns None
  - lookup_by_inchikey block14=True vs False behavior diff
  - lookup_by_xref 4 namespaces(KEGG / HMDB / LIPIDMAPS / METACYC)
  - climb_to_canonical Q-04 three-sugar sanity
  - Thread safety:K=4 concurrent × 1000 query no crash
  - normalize_chebi_id accepts "17234" / "CHEBI:17234" / "chebi:17234"
"""
from __future__ import annotations

import concurrent.futures
import sqlite3
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup, CompoundRecord, normalize_chebi_id

DB_PATH = WORKTREE / "data" / "concord" / "chebi.sqlite"
pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason=f"ChEBI sqlite not found at {DB_PATH} — run ETL first",
)


@pytest.fixture(scope="module")
def chebi() -> ChebiLookup:
    return ChebiLookup(db_path=DB_PATH)


# ---------------------------------------------------------------------------
# normalize_chebi_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("17234", "17234"),
        ("CHEBI:17234", "17234"),
        ("chebi:17234", "17234"),
        ("  CHEBI:17234  ", "17234"),
    ],
)
def test_normalize_chebi_id_accepted(raw, expected):
    assert normalize_chebi_id(raw) == expected


@pytest.mark.parametrize("bad", ["", "abc", "CHEBI:", "CHEBI:abc", "x17234"])
def test_normalize_chebi_id_rejected(bad):
    with pytest.raises(ValueError):
        normalize_chebi_id(bad)


# ---------------------------------------------------------------------------
# get_compound — happy path + miss
# ---------------------------------------------------------------------------


def test_get_compound_known(chebi):
    r = chebi.get_compound("17347")  # testosterone
    assert isinstance(r, CompoundRecord)
    assert r.chebi_id == "17347"
    assert r.primary_id == "CHEBI:17347"
    assert "testosterone" in r.name.lower()
    assert r.inchikey is not None and r.inchikey.startswith("MUMGGOZAMZWBJJ")


def test_get_compound_accepts_prefixed(chebi):
    r = chebi.get_compound("CHEBI:17347")
    assert r is not None
    assert r.chebi_id == "17347"


def test_get_compound_not_found_returns_none(chebi):
    assert chebi.get_compound("99999999") is None


# ---------------------------------------------------------------------------
# lookup_by_inchikey — full vs block14 difference
# ---------------------------------------------------------------------------


def test_lookup_by_inchikey_full(chebi):
    rows = chebi.lookup_by_inchikey("MUMGGOZAMZWBJJ-DYKIIFRCSA-N")  # testosterone full
    assert any(r.chebi_id == "17347" for r in rows)


def test_lookup_by_inchikey_block14_returns_more(chebi):
    """Block14 lookup should return ≥ as many hits as full(superset)."""
    full = chebi.lookup_by_inchikey("MUMGGOZAMZWBJJ-DYKIIFRCSA-N")
    block14 = chebi.lookup_by_inchikey("MUMGGOZAMZWBJJ", use_block14=True)
    assert len(block14) >= len(full)
    full_ids = {r.chebi_id for r in full}
    block_ids = {r.chebi_id for r in block14}
    assert full_ids.issubset(block_ids), "block14 must be superset of full match"


# ---------------------------------------------------------------------------
# lookup_by_xref — 4 namespaces
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ns, ext_id, expected_chebi",
    [
        ("KEGG",     "C00031", None),   # glucose-related (don't pin exact ChEBI; just non-None)
        ("HMDB",     "HMDB0000234", "17347"),  # testosterone
        ("LIPIDMAPS","LMST02020002", "17347"),  # testosterone
        ("METACYC",  "ARG", "16467"),   # L-arginine (D1 sanity confirmed)
    ],
)
def test_lookup_by_xref_4_namespaces(chebi, ns, ext_id, expected_chebi):
    r = chebi.lookup_by_xref(ns, ext_id)
    assert r is not None, f"{ns}:{ext_id} should resolve"
    if expected_chebi is not None:
        assert r.chebi_id == expected_chebi


def test_lookup_by_xref_unknown_ns_or_id_returns_none(chebi):
    assert chebi.lookup_by_xref("KEGG", "C99999999") is None
    assert chebi.lookup_by_xref("UNKNOWN_NS", "anything") is None


# ---------------------------------------------------------------------------
# lookup_by_name — exact vs fuzzy
# ---------------------------------------------------------------------------


def test_lookup_by_name_exact(chebi):
    rows = chebi.lookup_by_name("testosterone", fuzzy=False)
    chebi_ids = {r.chebi_id for r in rows}
    assert "17347" in chebi_ids


def test_lookup_by_name_fuzzy_broader(chebi):
    """Fuzzy substring search should return ≥ exact."""
    exact = chebi.lookup_by_name("testosterone", fuzzy=False)
    fuzzy = chebi.lookup_by_name("testosterone", fuzzy=True, limit=200)
    exact_ids = {r.chebi_id for r in exact}
    fuzzy_ids = {r.chebi_id for r in fuzzy}
    assert exact_ids.issubset(fuzzy_ids)
    assert len(fuzzy) >= len(exact)


# ---------------------------------------------------------------------------
# climb_to_canonical — Q-04 sanity (3 sugars share ancestors)
# ---------------------------------------------------------------------------


def test_climb_alpha_D_glucopyranose_ancestors(chebi):
    """CHEBI:17925 = α-D-glucopyranose. depth ≤ 2 should include D-glucopyranose
    (4167) and D-glucose (17634)."""
    ancestors = chebi.climb_to_canonical("17925", max_depth=2)
    assert "4167" in ancestors, "depth-1 parent D-glucopyranose (4167) missing"
    assert "17634" in ancestors, "depth-2 D-glucose (17634) missing"


def test_climb_three_sugars_share_canonical_ancestor(chebi):
    """Q-04 SANITY: α / β / D-glucopyranose 应在 depth ≤ 2 共享 ancestor
    (`4167` = D-glucopyranose OR `17634` = D-glucose)."""
    # α-D-glucopyranose (17925), β-D-glucopyranose (15903), D-glucopyranose (4167)
    sugars = ["17925", "15903", "4167"]
    chains: dict[str, set[str]] = {}
    for cid in sugars:
        chains[cid] = set(chebi.climb_to_canonical(cid, max_depth=2)) | {cid}
    intersection = chains[sugars[0]] & chains[sugars[1]] & chains[sugars[2]]
    assert intersection, (
        f"Q-04 sanity FAILED: no common ancestor at depth ≤ 2 among "
        f"α-D-glucopyranose / β-D-glucopyranose / D-glucopyranose. "
        f"Chains: {chains}"
    )
    # D-glucopyranose (4167) or D-glucose (17634) expected
    assert any(a in intersection for a in ["4167", "17634"])


def test_climb_terminal_compound_returns_empty(chebi):
    """A non-existent ChEBI ID climb should return empty list."""
    assert chebi.climb_to_canonical("99999999", max_depth=2) == []


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_thread_safety_k4_x_1000(chebi):
    """K=4 threads × 1000 lookups each should not crash."""
    chebi_ids = ["17347", "17234", "16467", "15422", "16238", "30769"]

    def worker(n: int) -> int:
        ok = 0
        for i in range(n):
            cid = chebi_ids[i % len(chebi_ids)]
            r = chebi.get_compound(cid)
            if r is not None:
                ok += 1
        return ok

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(worker, 1000) for _ in range(4)]
        results = [f.result(timeout=60) for f in futures]
    assert all(r == 1000 for r in results), f"some thread misses: {results}"


# ---------------------------------------------------------------------------
# Bulk helper
# ---------------------------------------------------------------------------


def test_lookup_many_by_xref(chebi):
    pairs = [("HMDB", "HMDB0000234"), ("KEGG", "C00031"), ("KEGG", "C99999999")]
    result = chebi.lookup_many_by_xref(pairs)
    assert result[("HMDB", "HMDB0000234")] is not None
    assert result[("KEGG", "C00031")] is not None
    assert result[("KEGG", "C99999999")] is None


# ---------------------------------------------------------------------------
# DB integrity sanity (light smoke, not full data validation)
# ---------------------------------------------------------------------------


def test_db_has_minimum_records(chebi):
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as c:
        n_compound = c.execute("SELECT COUNT(*) FROM compound").fetchone()[0]
        n_xref = c.execute("SELECT COUNT(*) FROM compound_xref").fetchone()[0]
        n_kegg = c.execute(
            "SELECT COUNT(*) FROM compound_xref WHERE external_ns='KEGG'"
        ).fetchone()[0]
        n_isa = c.execute("SELECT COUNT(*) FROM compound_isa").fetchone()[0]
    assert n_compound > 150_000, f"only {n_compound} compounds (spec: > 150K)"
    assert n_kegg > 15_000, f"only {n_kegg} KEGG xrefs (spec: > 15K)"
    assert n_xref > 50_000
    assert n_isa > 1_000_000, f"is_a flattened only {n_isa} (expected ~2.9M)"
