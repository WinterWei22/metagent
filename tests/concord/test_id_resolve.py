"""Unit tests for concord.reconcile.id_resolve (W4 D2)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup
from concord.reconcile.id_resolve import resolve_ids_to_compound_refs
from concord.schema.enrichment import COMPOUND_NAMESPACES, UnresolvedId

DB_PATH = WORKTREE / "data" / "concord" / "chebi.sqlite"
pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason=f"ChEBI sqlite not found at {DB_PATH} — run ETL first",
)


@pytest.fixture(scope="module")
def chebi() -> ChebiLookup:
    return ChebiLookup(db_path=DB_PATH)


def test_kegg_to_chebi_happy(chebi):
    resolved, unresolved = resolve_ids_to_compound_refs(
        ["C00031", "C00062"],  # D-glucose, L-arginine
        source_namespace="KEGG", chebi_lookup=chebi,
    )
    assert len(resolved) == 2
    assert all(r.primary_id.startswith("CHEBI:") for r in resolved)
    assert len(unresolved) == 0
    # KEGG: secondary ID populated for traceability
    assert all(r.kegg_compound_id and r.kegg_compound_id.startswith("KEGG:")
               for r in resolved)


def test_hmdb_to_chebi_happy(chebi):
    resolved, unresolved = resolve_ids_to_compound_refs(
        ["HMDB0000234", "HMDB0000122"],  # testosterone, D-glucose
        source_namespace="HMDB", chebi_lookup=chebi,
    )
    assert len(resolved) == 2
    for r in resolved:
        assert r.primary_id.startswith("CHEBI:")
        assert r.hmdb_id and r.hmdb_id.startswith("HMDB:")


def test_lipidmaps_to_chebi_happy(chebi):
    """LIPID MAPS xref → ChEBI; LMST02020002 = testosterone."""
    resolved, _ = resolve_ids_to_compound_refs(
        ["LMST02020002"],
        source_namespace="LIPIDMAPS", chebi_lookup=chebi,
    )
    assert len(resolved) == 1
    assert resolved[0].primary_id.startswith("CHEBI:")
    assert resolved[0].lipidmaps_id == "LIPIDMAPS:LMST02020002"


def test_chebi_passthrough(chebi):
    """source_namespace="CHEBI" → direct get_compound."""
    resolved, _ = resolve_ids_to_compound_refs(
        ["17347", "16467"],  # testosterone, L-arginine — ChEBI numeric
        source_namespace="CHEBI", chebi_lookup=chebi,
    )
    assert len(resolved) == 2
    assert all(r.primary_id.startswith("CHEBI:") for r in resolved)


def test_inchikey_passthrough(chebi):
    """INCHIKEY ns:raw_id is the InChIKey itself."""
    resolved, _ = resolve_ids_to_compound_refs(
        ["MUMGGOZAMZWBJJ-DYKIIFRCSA-N"],  # testosterone InChIKey
        source_namespace="INCHIKEY", chebi_lookup=chebi,
    )
    assert len(resolved) == 1
    # Should hit ChEBI via lookup_by_inchikey → primary_id starts with CHEBI:
    assert resolved[0].primary_id.startswith("CHEBI:")


def test_xref_miss_no_inchikey_returns_unresolved(chebi):
    """Bogus KEGG cpd → no ChEBI xref + no inchikey → unresolved."""
    resolved, unresolved = resolve_ids_to_compound_refs(
        ["C99999999"], source_namespace="KEGG", chebi_lookup=chebi,
    )
    assert len(resolved) == 0
    assert len(unresolved) == 1
    assert unresolved[0].raw_id == "C99999999"
    assert unresolved[0].source_namespace == "KEGG"
    assert unresolved[0].reason == "xref_miss"


def test_xref_miss_with_fallback_inchikey_resolves(chebi):
    """Bogus KEGG cpd BUT caller supplies known InChIKey → fallback CompoundRef."""
    fallback = {"C99999999": "FOOBARBAZQUUX-XYZABCDEFG-N"}
    resolved, unresolved = resolve_ids_to_compound_refs(
        ["C99999999"], source_namespace="KEGG", chebi_lookup=chebi,
        inchikey_by_raw=fallback,
    )
    assert len(resolved) == 1
    # primary_id falls back to KEGG namespace since ChEBI missed
    assert resolved[0].primary_id == "KEGG:C99999999"
    assert resolved[0].inchikey == "FOOBARBAZQUUX-XYZABCDEFG-N"
    assert resolved[0].chebi_id is None
    assert len(unresolved) == 0


def test_empty_input_returns_empty_pair():
    resolved, unresolved = resolve_ids_to_compound_refs(
        [], source_namespace="KEGG", chebi_lookup=None,  # type: ignore
    )
    assert resolved == [] and unresolved == []


def test_dedupe_preserves_first(chebi):
    """Duplicate raw_ids collapse to first."""
    resolved, _ = resolve_ids_to_compound_refs(
        ["C00031", "C00031", "C00062"],
        source_namespace="KEGG", chebi_lookup=chebi,
    )
    assert len(resolved) == 2


def test_invalid_format_blank_string(chebi):
    resolved, unresolved = resolve_ids_to_compound_refs(
        ["", "  "], source_namespace="KEGG", chebi_lookup=chebi,
    )
    assert resolved == []
    assert len(unresolved) == 2
    assert all(u.reason == "invalid_format" for u in unresolved)


def test_kegg_drug_alias_routed_as_kegg(chebi):
    """KEGG_DRUG / KEGG_GLYCAN tolerated as KEGG."""
    resolved, _ = resolve_ids_to_compound_refs(
        ["C00031"], source_namespace="KEGG_DRUG", chebi_lookup=chebi,
    )
    # KEGG_DRUG aliased to KEGG → C00031 may or may not be in KEGG_DRUG xref,
    # but routed and tested as KEGG. We just assert no crash.
    assert isinstance(resolved, list)
