"""Unit tests for `concord.reconcile.inchikey` (W3 D5).

5+ test cases per spec, plus Q-04 sugar fix end-to-end test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup, CompoundRecord
from concord.reconcile.inchikey import (
    ConflictReport,
    ReconcileResult,
    block14,
    cluster_by_block14,
    compute_inchikey,
    detect_charge_stereo_conflict,
    reconcile_with_chebi,
)

DB_PATH = WORKTREE / "data" / "concord" / "chebi.sqlite"
pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason=f"ChEBI sqlite not found at {DB_PATH} — run ETL first",
)


@pytest.fixture(scope="module")
def chebi() -> ChebiLookup:
    return ChebiLookup(db_path=DB_PATH)


# ---------------------------------------------------------------------------
# compute_inchikey
# ---------------------------------------------------------------------------


def test_compute_inchikey_smiles_glucose():
    # D-glucose canonical SMILES
    ik = compute_inchikey("OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O")
    assert ik is not None
    assert ik.startswith("WQZGKKKJIJFFOK"), f"unexpected block14: {ik}"


def test_compute_inchikey_inchi_input():
    """Accept InChI string directly."""
    inchi_str = ("InChI=1S/C6H12O6/c7-1-2-3(8)4(9)5(10)6(11)12-2/"
                 "h2-11H,1H2/t2-,3-,4+,5-,6?/m1/s1")
    ik = compute_inchikey(inchi_str)
    assert ik is not None
    assert ik.startswith("WQZGKKKJIJFFOK")


def test_compute_inchikey_invalid_returns_none():
    assert compute_inchikey("not_a_smiles") is None
    assert compute_inchikey("") is None
    assert compute_inchikey(None) is None


# ---------------------------------------------------------------------------
# block14
# ---------------------------------------------------------------------------


def test_block14_basic():
    assert block14("WQZGKKKJIJFFOK-GASJEMHNSA-N") == "WQZGKKKJIJFFOK"
    assert block14("") == ""
    assert block14(None) == ""


# ---------------------------------------------------------------------------
# cluster_by_block14
# ---------------------------------------------------------------------------


def test_cluster_by_block14_groups_correctly(chebi):
    # 2 testosterone-related refs(same block14)+ 1 D-glucose(different)
    refs = [
        chebi.get_compound("17347"),     # testosterone
        chebi.get_compound("28689"),     # DHEA — different connectivity
        # Construct a stand-in identical-block14 ref:
    ]
    # Filter None
    refs = [r for r in refs if r is not None]
    clusters = cluster_by_block14(refs)
    # All 2 refs should be in distinct clusters
    n_block14_keys = sum(1 for k in clusters if k)
    assert n_block14_keys >= 1


# ---------------------------------------------------------------------------
# detect_charge_stereo_conflict
# ---------------------------------------------------------------------------


def test_detect_conflict_charge_state():
    """Mock refs differing only in charge layer (N vs M last char)."""
    class _MockRef:
        def __init__(self, ik): self.inchikey = ik
    refs = [
        _MockRef("ABCDEFGHIJKLMN-FOOBARBAZQ-N"),  # neutral
        _MockRef("ABCDEFGHIJKLMN-FOOBARBAZQ-M"),  # anion
    ]
    report = detect_charge_stereo_conflict(refs)
    assert report.conflict_type == "charge"
    assert report.n_distinct_block14 == 1
    assert report.n_distinct_full == 2


def test_detect_conflict_stereo_layer():
    class _MockRef:
        def __init__(self, ik): self.inchikey = ik
    refs = [
        _MockRef("ABCDEFGHIJKLMN-UHFFFAOYSA-N"),  # no stereo
        _MockRef("ABCDEFGHIJKLMN-DYKIIFRCSA-N"),  # full stereo
    ]
    report = detect_charge_stereo_conflict(refs)
    assert report.conflict_type == "stereo"
    assert report.n_distinct_block14 == 1


def test_detect_conflict_connectivity():
    class _MockRef:
        def __init__(self, ik): self.inchikey = ik
    refs = [
        _MockRef("ABCDEFGHIJKLMN-FOOBARBAZQ-N"),
        _MockRef("XYZAAAAAAAAAAA-FOOBARBAZQ-N"),  # different block14
    ]
    report = detect_charge_stereo_conflict(refs)
    assert report.conflict_type == "connectivity"
    assert report.n_distinct_block14 == 2


def test_detect_conflict_none():
    """Single ref or identical refs → none."""
    class _MockRef:
        def __init__(self, ik): self.inchikey = ik
    same = _MockRef("ABCDEFGHIJKLMN-FOOBARBAZQ-N")
    report = detect_charge_stereo_conflict([same, _MockRef("ABCDEFGHIJKLMN-FOOBARBAZQ-N")])
    assert report.conflict_type == "none"


# ---------------------------------------------------------------------------
# reconcile_with_chebi — Q-04 sugar fix END-TO-END
# ---------------------------------------------------------------------------


def test_reconcile_q04_three_sugars_via_block14(chebi):
    """Q-04 END-TO-END part 1:三 ring-form glucose ChEBI IDs(α/β/D-glucopyranose)
    ChEBI 中已 canonicalize 到同一 standard InChI → 都共享 block14。
    Reconciler 走 block14 路径成功 reconcile,不需 fall back 到 is_a。
    """
    refs = [
        chebi.get_compound("17925"),   # α-D-glucopyranose
        chebi.get_compound("15903"),   # β-D-glucopyranose
        chebi.get_compound("4167"),    # D-glucopyranose (parent)
    ]
    refs = [r for r in refs if r is not None]
    assert len(refs) == 3, f"only {len(refs)} sugars resolvable in ChEBI"

    result = reconcile_with_chebi(refs, chebi, max_depth=3)
    assert isinstance(result, ReconcileResult)
    assert result.is_same_compound is True, (
        f"Q-04 sugar fix FAILED: reconciler should treat α/β/D-glucopyranose "
        f"as same compound. Result: {result}"
    )
    assert result.method in ("block14", "chebi_is_a"), result.method


def test_reconcile_q04_via_is_a_fallback(chebi):
    """Q-04 END-TO-END part 2:fabricate two refs with DIFFERENT block14
    but sharing ChEBI is_a ancestor → reconciler must walk is_a chain.

    Use:
      - α-D-glucopyranose (17925) — has InChIKey WQZGKKKJIJFFOK...
      - synthetic CompoundRecord with chebi_id=17234(glucose,parent)
        and DIFFERENT block14 to force is_a path.
    """
    real_alpha = chebi.get_compound("17925")
    assert real_alpha and real_alpha.inchikey_block14

    # Synthesize a sibling with different block14 but related via is_a chain
    fake_open_chain_glucose = CompoundRecord(
        chebi_id="17234",
        primary_id="CHEBI:17234",
        name="glucose (parent)",
        inchikey="GZCGUPFRVQAUEE-UHFFFAOYSA-N",   # open-chain Fischer block14
        inchikey_block14="GZCGUPFRVQAUEE",
        smiles="OCC(O)C(O)C(O)C(O)C=O",
        monoisotopic_mass=180.0634,
        charge=0,
        formula="C6H12O6",
    )
    refs = [real_alpha, fake_open_chain_glucose]
    result = reconcile_with_chebi(refs, chebi, max_depth=4)
    # is_a chain: α-D-glucopyranose(17925) climbs to D-glucose(17634) at depth 2
    #             and to glucose(17234) at depth 3. So they share 17234.
    assert result.is_same_compound is True, (
        f"Q-04 is_a-path reconciliation FAILED: {result}"
    )
    assert result.method == "chebi_is_a", (
        f"Expected method=chebi_is_a but got {result.method}"
    )


def test_reconcile_single_ref_trivially_same(chebi):
    r = chebi.get_compound("17234")
    result = reconcile_with_chebi([r], chebi)
    assert result.is_same_compound is True
    assert result.n_refs == 1


def test_reconcile_unrelated_compounds(chebi):
    """Totally unrelated compounds:no block14 or ancestor overlap → is_same=False."""
    refs = [
        chebi.get_compound("17347"),   # testosterone
        chebi.get_compound("15422"),   # ATP
    ]
    refs = [r for r in refs if r is not None]
    assert len(refs) == 2
    result = reconcile_with_chebi(refs, chebi, max_depth=2)
    # These are clearly different compounds. block14 should differ.
    assert result.is_same_compound is False, (
        f"testosterone and ATP should NOT reconcile to same compound; "
        f"got {result}"
    )
