"""Unit tests for RaMP wrapper + normalizer (W4 D4)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

# Default RaMP db (Session 3 verified)
RAMP_DB = Path("/data/weiwentao/llm_agent_metabolomics/ramp.sqlite")
CHEBI_DB = WORKTREE / "data" / "concord" / "chebi.sqlite"

pytestmark = pytest.mark.skipif(
    not (RAMP_DB.exists() and CHEBI_DB.exists()),
    reason="RaMP or ChEBI sqlite missing",
)


@pytest.fixture(scope="module")
def chebi():
    from concord.lookup.chebi import ChebiLookup
    return ChebiLookup(db_path=CHEBI_DB)


@pytest.fixture(scope="module")
def toy_refs(chebi):
    """8 mainstream metabolites via ChebiLookup."""
    pairs = [
        ("HMDB", "HMDB0000234"),  # testosterone
        ("HMDB", "HMDB0000122"),  # D-glucose
        ("HMDB", "HMDB0000517"),  # L-arginine
        ("HMDB", "HMDB0000538"),  # ATP
        ("HMDB", "HMDB0000094"),  # citric acid
        ("HMDB", "HMDB0000077"),  # DHEA
        ("HMDB", "HMDB0001264"),  # dehydroascorbic
        ("HMDB", "HMDB0000172"),  # L-isoleucine
    ]
    from concord.schema.enrichment import CompoundRef, resolve_primary_id
    refs = []
    for ns, ext_id in pairs:
        rec = chebi.lookup_by_xref(ns, ext_id)
        if rec is None or not rec.inchikey:
            continue
        refs.append(CompoundRef(
            primary_id=resolve_primary_id(chebi_id=rec.primary_id, inchikey=rec.inchikey),
            inchikey=rec.inchikey, display_name=rec.name,
            chebi_id=rec.primary_id,
            hmdb_id=f"HMDB:{ext_id}",
        ))
    return refs


def test_ramp_happy_path(toy_refs, chebi):
    """End-to-end:CompoundRef list → run_ramp_enrichment → normalize → v0.3."""
    from concord.normalize.ramp_norm import normalize_ramp_output
    from concord.schema.enrichment import (
        EnrichmentResult, PATHWAY_NAMESPACES, COMPOUND_NAMESPACES,
    )
    from concord.wrappers.ramp_wrapper import run_ramp_enrichment

    raw = run_ramp_enrichment(toy_refs, top_n=10)
    assert raw["n_input"] >= 1
    assert raw["report"] is not None
    er = normalize_ramp_output(raw, top_n=10, chebi_lookup=chebi)
    assert isinstance(er, EnrichmentResult)
    assert er.schema_version == "concordmet_v0.3"
    assert len(er.pathways) >= 1
    for hit in er.pathways:
        ns = hit.pathway_id.split(":", 1)[0]
        assert ns in PATHWAY_NAMESPACES, hit.pathway_id
    # At least 1 metabolites_hit overall
    total = sum(len(p.metabolites_hit) for p in er.pathways)
    assert total > 0


def test_ramp_metabolites_hit_chebi_namespace(toy_refs, chebi):
    """At least 1 metabolites_hit primary_id is CHEBI: prefixed."""
    from concord.normalize.ramp_norm import normalize_ramp_output
    from concord.wrappers.ramp_wrapper import run_ramp_enrichment

    raw = run_ramp_enrichment(toy_refs, top_n=10)
    er = normalize_ramp_output(raw, top_n=10, chebi_lookup=chebi)
    chebi_n = sum(1 for p in er.pathways for m in p.metabolites_hit
                  if m.primary_id.startswith("CHEBI:"))
    assert chebi_n > 0, "no CHEBI:-prefixed metabolites_hit"


def test_ramp_empty_compound_set():
    """Empty input → empty EnrichmentResult (does NOT raise)."""
    from concord.normalize.ramp_norm import normalize_ramp_output
    from concord.wrappers.ramp_wrapper import run_ramp_enrichment

    raw = run_ramp_enrichment([], top_n=10)
    assert raw["n_input"] == 0
    er = normalize_ramp_output(raw, top_n=10)
    assert len(er.pathways) == 0


def test_ramp_pathway_namespace_distribution(toy_refs, chebi):
    """Top-N pathways should span ≥2 distinct namespaces (RaMP merges sources)."""
    from concord.normalize.ramp_norm import normalize_ramp_output
    from concord.wrappers.ramp_wrapper import run_ramp_enrichment

    raw = run_ramp_enrichment(toy_refs, top_n=20)
    er = normalize_ramp_output(raw, top_n=20, chebi_lookup=chebi)
    namespaces = {p.pathway_id.split(":", 1)[0] for p in er.pathways}
    # With mainstream metabolites, RaMP usually returns SMPDB + WP + REACT mix
    assert len(namespaces) >= 2, (
        f"only 1 namespace in top-20 ({namespaces}); RaMP usually mixes sources"
    )


def test_ramp_inchikey_fallback_when_no_hmdb(chebi):
    """If only InChIKey available (no hmdb_id), wrapper falls back to inchikey path."""
    from concord.schema.enrichment import CompoundRef
    from concord.wrappers.ramp_wrapper import run_ramp_enrichment

    rec = chebi.lookup_by_xref("HMDB", "HMDB0000234")
    only_ik = CompoundRef(
        primary_id=f"INCHIKEY:{rec.inchikey}", inchikey=rec.inchikey,
        display_name=rec.name,
        chebi_id=None, hmdb_id=None, kegg_compound_id=None,
    )
    raw = run_ramp_enrichment([only_ik], top_n=5)
    assert raw["id_type_used"] == "inchikey"
    # Result may or may not resolve depending on RaMP coverage
    assert "report" in raw


def test_ramp_pathway_validator_rejects_unknown_ns(monkeypatch, toy_refs, chebi):
    """If RaMP returned an exotic source (e.g. 'metanetx'), it falls back to SMPDB
    namespace (whitelisted) — no validator rejection."""
    from concord.normalize.ramp_norm import _namespace_pathway_id
    ns_id, native = _namespace_pathway_id(
        pathway_source="weird_source", ext_id="WEIRD123", ramp_pid="RAMP_P_99",
    )
    # Conservative fallback to SMPDB
    assert ns_id.startswith("SMPDB:")
