"""W7 D1.1 — pathway_members.sqlite ETL smoke."""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.etl.pathway_members_etl import load_pathway_members, DEFAULT_OUT


pytestmark = pytest.mark.skipif(
    not DEFAULT_OUT.exists(),
    reason=f"{DEFAULT_OUT} not built — run ETL first",
)


def test_pathway_members_human1_alanine_nonempty():
    """Human1 'alanine_aspartate_and_glutamate_metabolism' should resolve
    to a meaningful member set (≥10 CHEBI IDs, all CHEBI:-prefixed)."""
    members = load_pathway_members("HUMAN1", "alanine_aspartate_and_glutamate_metabolism")
    assert len(members) >= 10, f"expected ≥10 members, got {len(members)}"
    assert all(m.startswith("CHEBI:") for m in members), \
        f"non-CHEBI ids leaked: {[m for m in list(members)[:5] if not m.startswith('CHEBI:')]}"


def test_pathway_members_recon2_lookup_works():
    """Recon2.2 pathways should also be queryable (BIGG→MNX→ChEBI bridge)."""
    members = load_pathway_members("RECON2", "starch_and_sucrose_metabolism")
    assert len(members) >= 1, "Recon2.2 starch/sucrose should resolve at least one CHEBI"
