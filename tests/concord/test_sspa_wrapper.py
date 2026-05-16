"""Unit tests for sspa wrapper + normalizer (W3 D4).

Covers W3 D4 unit-test checklist:
  1-4. ssgsea / ora / kpca / zscore happy path on Session 4 toy data
  5.   R-NEW-15 regression: pathway_df with int chebi cells → wrapper str-casts
  6.   Empty compound set → ValueError(graceful, doesn't crash)
  7.   pathway_id is namespace-prefixed (REACT:... or KEGG:...) per Q05-NEW-4
  8.   metabolites_hit elements use primary_id starting with CHEBI: per Q05-NEW-5
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from concord.lookup.chebi import ChebiLookup
from concord.normalize.sspa_norm import (
    _namespace_pathway_id,
    normalize_sspa_output,
)
from concord.schema.enrichment import (
    COMPOUND_NAMESPACES,
    EnrichmentResult,
    PATHWAY_NAMESPACES,
    resolve_primary_id,
)
from concord.wrappers.sspa_wrapper import (
    _normalize_pathway_df,
    _refs_to_chebi_numeric,
    run_sspa,
)

DB_PATH = WORKTREE / "data" / "concord" / "chebi.sqlite"
pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason=f"ChEBI sqlite not found at {DB_PATH} — run ETL first",
)


@pytest.fixture(scope="module")
def chebi() -> ChebiLookup:
    return ChebiLookup(db_path=DB_PATH)


@pytest.fixture(scope="module")
def toy_refs(chebi: ChebiLookup) -> list:
    """8 well-known compounds via ChebiLookup → CompoundRecord list."""
    pairs = [
        ("HMDB", "HMDB0000234"),   # testosterone
        ("HMDB", "HMDB0000122"),   # D-glucose
        ("HMDB", "HMDB0000517"),   # L-arginine
        ("HMDB", "HMDB0000172"),   # L-isoleucine
        ("HMDB", "HMDB0000538"),   # ATP
        ("HMDB", "HMDB0000094"),   # citric acid
        ("HMDB", "HMDB0000077"),   # DHEA
        ("HMDB", "HMDB0001264"),   # dehydroascorbic acid
    ]
    refs = [chebi.lookup_by_xref(ns, ext) for ns, ext in pairs]
    return [r for r in refs if r is not None]


# ---------------------------------------------------------------------------
# Helper unit tests (no network / no sspa call)
# ---------------------------------------------------------------------------


def test_R_NEW_15_normalize_pathway_df_int_to_str():
    """R-NEW-15 regression: int cells become str."""
    df = pd.DataFrame({
        "Pathway_name": ["Glycolysis", "TCA"],
        0: [17234, 16467],   # int ChEBI IDs
        1: [16238, 15422],
    }, index=["R-HSA-1", "R-HSA-2"])
    out = _normalize_pathway_df(df)
    # All non-Pathway_name cells should be str now
    for col in [0, 1]:
        for val in out[col]:
            assert isinstance(val, str), f"col {col} contains non-str: {val!r}"
    # Pathway_name column unchanged
    assert out["Pathway_name"][0] == "Glycolysis"


def test_R_NEW_15_handles_nan_cells():
    """NaN cells (short pathways) must not crash."""
    import numpy as np
    df = pd.DataFrame({
        "Pathway_name": ["Short"],
        0: [17234],
        1: [np.nan],   # short pathway
        2: [np.nan],
    }, index=["R-HSA-1"])
    out = _normalize_pathway_df(df)
    assert out[0][0] == "17234"
    assert pd.isna(out[1][0])


def test_namespace_pathway_id_reactome():
    assert _namespace_pathway_id("R-HSA-71387") == "REACT:R-HSA-71387"


def test_namespace_pathway_id_kegg():
    assert _namespace_pathway_id("hsa00010") == "KEGG:hsa00010"


def test_refs_to_chebi_numeric_handles_mixed():
    from concord.lookup.chebi import CompoundRecord
    refs = [
        CompoundRecord(chebi_id="17234", primary_id="CHEBI:17234", name="x",
                       inchikey=None, inchikey_block14=None, smiles=None,
                       monoisotopic_mass=None, charge=None, formula=None),
        "CHEBI:16467",
        "15422",
        None,
    ]
    out = _refs_to_chebi_numeric(refs)
    assert out == ["17234", "16467", "15422"]


# ---------------------------------------------------------------------------
# Integration: run sspa end-to-end (uses real ChEBI + sspa Reactome DB)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["ora", "ssgsea"])
def test_run_sspa_happy_path(toy_refs, method):
    """Reactome path, 2 methods. Verify wrapper returns expected dict structure."""
    result = run_sspa(
        compound_refs=toy_refs,
        method=method,
        pathway_db="reactome",
    )
    assert "raw" in result
    assert result["method"] == method
    assert result["pathway_db"] == "reactome"
    assert result["n_input"] == len(toy_refs)
    assert result["n_input_resolved"] >= 1, (
        f"none of {len(toy_refs)} ChEBI refs resolved to sspa Reactome "
        f"universe (expected ≥1 since toy is mainstream metabolites)"
    )
    assert result["wall_time_sec"] > 0
    assert isinstance(result["raw"], pd.DataFrame)
    assert not result["raw"].empty


def test_run_sspa_empty_input_raises(chebi):
    with pytest.raises(ValueError, match="empty"):
        run_sspa(compound_refs=[], method="ora", pathway_db="reactome")


def test_normalize_to_v03_namespace_format(toy_refs):
    """End-to-end: run_sspa → normalize → EnrichmentResult v0.3.

    Q05-NEW-4 verify: pathway_id starts with valid namespace prefix.
    """
    raw_result = run_sspa(
        compound_refs=toy_refs, method="ora", pathway_db="reactome",
    )
    er = normalize_sspa_output(raw_result, top_n=10)
    assert isinstance(er, EnrichmentResult)
    assert er.schema_version == "concordmet_v0.3.1"
    assert er.chebi_canonicalized is True
    # At least 1 pathway hit (ORA on 8 mainstream metabolites should yield ≥1)
    assert len(er.pathways) >= 1
    # All pathway_ids must be namespace-prefixed
    for hit in er.pathways:
        ns = hit.pathway_id.split(":", 1)[0]
        assert ns in PATHWAY_NAMESPACES, (
            f"pathway_id {hit.pathway_id!r} namespace {ns!r} "
            f"not in {PATHWAY_NAMESPACES}"
        )
        assert hit.pathway_id_native, "native pathway_id missing"


def test_normalize_ssgsea_method(toy_refs):
    """ssGSEA method also normalizes correctly to v0.3."""
    raw_result = run_sspa(
        compound_refs=toy_refs, method="ssgsea", pathway_db="reactome",
    )
    er = normalize_sspa_output(raw_result, top_n=10)
    assert isinstance(er, EnrichmentResult)
    assert len(er.pathways) >= 1
    for hit in er.pathways:
        assert ":" in hit.pathway_id
        assert hit.pathway_id.split(":", 1)[0] in PATHWAY_NAMESPACES


def test_normalize_handles_empty_raw():
    """Empty raw DataFrame should produce EnrichmentResult with 0 pathways, not crash."""
    empty_result = {
        "raw": pd.DataFrame(),
        "method": "ora",
        "pathway_db": "reactome",
        "organism": "Homo sapiens",
        "n_input": 0,
        "n_input_resolved": 0,
        "wall_time_sec": 0.01,
        "tool_version": "sspa-1.0.4",
        "db_release": "test",
        "parameters": {},
    }
    er = normalize_sspa_output(empty_result, top_n=10)
    assert isinstance(er, EnrichmentResult)
    assert len(er.pathways) == 0


# ---------------------------------------------------------------------------
# W3 hotfix regression (2026-05-16):metabolites_hit must be populated by
# real sspa.sspa_ora pipeline. Earlier unit tests passed because they did
# NOT go through producer→validator end-to-end;they constructed pathway_df
# manually and never exercised the DA_Metabolites_ID column.
# ---------------------------------------------------------------------------


def test_sspa_ora_populates_metabolites_hit_regression(toy_refs, chebi):
    """REGRESSION:running real sspa.sspa_ora() through the wrapper +
    normalizer must yield non-empty ``metabolites_hit`` on at least one
    pathway. Asserted: primary_id starts with ``CHEBI:`` per Q05-NEW-5.

    This case caught the bug where Check 2 (post-W3 sanity) reported
    ``n_compound_refs = 0`` despite ``n_pathways = 10``.
    """
    raw_result = run_sspa(
        compound_refs=toy_refs, method="ora", pathway_db="reactome",
    )
    er = normalize_sspa_output(raw_result, top_n=10, chebi_lookup=chebi)
    assert isinstance(er, EnrichmentResult)
    assert len(er.pathways) > 0, "no pathways at all — too small toy?"
    total_hits = sum(len(p.metabolites_hit) for p in er.pathways)
    assert total_hits > 0, (
        f"metabolites_hit empty across all {len(er.pathways)} pathways. "
        f"Patch 1 (sspa_norm wire DA_Metabolites_ID) is broken."
    )
    # CHEBI: namespace assertion on at least the top-hit pathway with refs
    found_chebi = False
    for p in er.pathways:
        for m in p.metabolites_hit:
            if m.primary_id.startswith("CHEBI:"):
                found_chebi = True
                # Spot-check structural integrity
                assert m.inchikey, f"CompoundRef without inchikey: {m}"
                assert m.chebi_id, f"CompoundRef without chebi_id: {m}"
                break
        if found_chebi:
            break
    assert found_chebi, (
        f"No CHEBI:-prefixed primary_id found across {total_hits} metabolites_hit"
    )


def test_enrichment_result_validator_rejects_vacuous(toy_refs, chebi):
    """REGRESSION:Patch 2 validator must reject n_pathways>0 with 0 refs.

    Pre-W3-hotfix this passed silently (vacuous all() over empty list).
    """
    from concord.schema.enrichment import (
        EnrichmentMethod,
        PathwayDB,
        PathwayHit,
        ScoreType,
    )
    bad_hit = PathwayHit(
        pathway_id="REACT:R-HSA-71387",
        pathway_name="x",
        pathway_id_native="R-HSA-71387",
        pathway_db=PathwayDB.REACTOME,
        score=0.01, score_type=ScoreType.P_VALUE, rank=0,
        metabolites_hit=(),  # <— vacuous
    )
    with pytest.raises(ValueError, match="structurally vacuous"):
        EnrichmentResult(
            method=EnrichmentMethod.ORA_SSPA,
            pathway_db=PathwayDB.REACTOME,
            pathways=(bad_hit,),
            parameters={},
            tool_version="x", db_release="x",
            n_input=1, n_input_resolved=1, wall_time_sec=0.1,
        )
