"""Unit tests for tools.kegg.graph_builder."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import textwrap
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from tools.kegg.graph_builder import (
    _normalise_alias,
    build_reaction_graph,
    load_curated_pool_aliases,
    parse_kgml,
)


# ---- minimal KGML fixture --------------------------------------------------


def _write_minimal_kgml(p: Path) -> None:
    """A 2-reaction KGML covering substrate→product directionality and
    the reversible/irreversible distinction."""
    p.write_text(textwrap.dedent("""\
        <?xml version="1.0"?>
        <pathway name="path:hsa99999" org="hsa" number="99999"
                 title="Test pathway">
            <entry id="1" name="cpd:C00001" type="compound"/>
            <entry id="2" name="cpd:C00002" type="compound"/>
            <entry id="3" name="cpd:C00003" type="compound"/>
            <entry id="4" name="ko:K00001" type="ortholog"/>
            <reaction id="100" name="rn:R00001" type="irreversible">
                <substrate id="1" name="cpd:C00001"/>
                <product id="2" name="cpd:C00002"/>
            </reaction>
            <reaction id="101" name="rn:R00002" type="reversible">
                <substrate id="2" name="cpd:C00002"/>
                <product id="3" name="cpd:C00003"/>
            </reaction>
        </pathway>
    """))


# ---- parse_kgml -----------------------------------------------------------


def test_parse_kgml_minimal_extracts_compounds_and_reactions(tmp_path):
    p = tmp_path / "hsa99999.xml"
    _write_minimal_kgml(p)
    cpds, rxns, pid = parse_kgml(p)
    assert pid == "hsa99999"
    assert {c.compound_id for c in cpds} == {"cpd:C00001", "cpd:C00002", "cpd:C00003"}
    rxn_ids = {r.reaction_id for r in rxns}
    assert rxn_ids == {"rn:R00001", "rn:R00002"}
    rev_map = {r.reaction_id: r.reversible for r in rxns}
    assert rev_map["rn:R00001"] is False  # irreversible
    assert rev_map["rn:R00002"] is True   # reversible
    sub_map = {r.reaction_id: r.substrate_compounds for r in rxns}
    prod_map = {r.reaction_id: r.product_compounds for r in rxns}
    assert sub_map["rn:R00001"] == ("cpd:C00001",)
    assert prod_map["rn:R00001"] == ("cpd:C00002",)


def test_parse_kgml_methionine_metabolism_real():
    """Real-data smoke: parse hsa00270 if present and verify expected
    KEGG compounds (S-adenosyl-L-methionine cpd:C00019, homocysteine
    cpd:C00155, methionine cpd:C00073)."""
    p = Path(_REPO_ROOT) / "data" / "kegg" / "kgml" / "hsa00270.xml"
    if not p.is_file():
        pytest.skip("hsa00270.xml not cached locally")
    cpds, rxns, pid = parse_kgml(p)
    cids = {c.compound_id for c in cpds}
    assert pid == "hsa00270"
    # All three are well-known methionine-cycle compounds
    assert "cpd:C00019" in cids  # SAM
    assert "cpd:C00073" in cids  # L-methionine
    assert "cpd:C00155" in cids  # L-homocysteine
    assert len(rxns) >= 30, f"expected ≥30 reactions, got {len(rxns)}"


def test_parse_kgml_skips_non_compound_entries(tmp_path):
    """Glycan / drug / map-link entries must NOT show up in compounds."""
    p = tmp_path / "hsa99998.xml"
    p.write_text(textwrap.dedent("""\
        <?xml version="1.0"?>
        <pathway name="path:hsa99998" org="hsa" number="99998">
            <entry id="1" name="cpd:C00001" type="compound"/>
            <entry id="2" name="gl:G00001" type="glycan"/>
            <entry id="3" name="dr:D00001" type="drug"/>
            <entry id="4" name="path:hsa00270" type="map"/>
        </pathway>
    """))
    cpds, rxns, _ = parse_kgml(p)
    assert {c.compound_id for c in cpds} == {"cpd:C00001"}


def test_parse_kgml_handles_multi_reaction_id(tmp_path):
    """KGML uses ``name="rn:R00001 rn:R00002"`` for fused reactions."""
    p = tmp_path / "hsa99997.xml"
    p.write_text(textwrap.dedent("""\
        <?xml version="1.0"?>
        <pathway name="path:hsa99997" org="hsa" number="99997">
            <entry id="1" name="cpd:C00001" type="compound"/>
            <entry id="2" name="cpd:C00002" type="compound"/>
            <reaction id="100" name="rn:R00001 rn:R00002" type="irreversible">
                <substrate id="1" name="cpd:C00001"/>
                <product id="2" name="cpd:C00002"/>
            </reaction>
        </pathway>
    """))
    _, rxns, _ = parse_kgml(p)
    rxn_ids = {r.reaction_id for r in rxns}
    assert rxn_ids == {"rn:R00001", "rn:R00002"}


def test_parse_kgml_drops_reactions_without_substrate_or_product(tmp_path):
    """Defensive: malformed reaction entries shouldn't crash the build."""
    p = tmp_path / "hsa99996.xml"
    p.write_text(textwrap.dedent("""\
        <?xml version="1.0"?>
        <pathway name="path:hsa99996" org="hsa" number="99996">
            <entry id="1" name="cpd:C00001" type="compound"/>
            <reaction id="100" name="rn:R00001" type="irreversible">
                <product id="1" name="cpd:C00001"/>
            </reaction>
        </pathway>
    """))
    _, rxns, _ = parse_kgml(p)
    assert rxns == []


# ---- alias loader ---------------------------------------------------------


def test_load_curated_pool_aliases_emits_all_4_sources(tmp_path):
    """Exactly 4 source kinds should be present (kegg, name, inchikey14,
    hmdb); name kind also produces L-/D- and ic-acid/ate variants but
    they all share source='name'."""
    p = tmp_path / "curated.jsonl"
    p.write_text(json.dumps({
        "name": "L-Methionine",
        "kegg_id": "C00073",
        "hmdb_id": "HMDB0000696",
        "inchikey_first_block": "FFEARJCKVFRZRR",
    }) + "\n")
    rows = load_curated_pool_aliases(p)
    sources = {src for _, _, src in rows}
    assert sources == {"name", "inchikey14", "hmdb", "kegg"}
    # Name variants must include both 'l-methionine' and 'methionine'
    name_aliases = {alias for alias, _, src in rows if src == "name"}
    assert "l-methionine" in name_aliases
    assert "methionine" in name_aliases
    # Curated pool stores 'C00073' (no cpd: prefix); loader must canonicalise.
    cpd_ids = {kegg for _, kegg, _ in rows}
    assert cpd_ids == {"cpd:C00073"}


def test_normalise_alias_handles_whitespace_and_case():
    assert _normalise_alias("  L-Methionine  ") == "l-methionine"
    assert _normalise_alias("S-adenosyl  methionine") == "s-adenosyl methionine"


# ---- build_reaction_graph -------------------------------------------------


def test_build_reaction_graph_creates_indexes(tmp_path):
    """DB must have the indexes the layer relies on."""
    kgml_dir = tmp_path / "kgml"
    kgml_dir.mkdir()
    _write_minimal_kgml(kgml_dir / "hsa99999.xml")
    out_db = tmp_path / "graph.sqlite"
    summary = build_reaction_graph(kgml_dir, out_db)
    assert summary["n_pathways"] == 1
    assert summary["n_compounds"] == 3
    assert summary["n_unique_reactions"] == 2

    # Confirm indexes exist
    conn = sqlite3.connect(out_db)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        names = {r[0] for r in rows}
        assert "idx_reaction_substrates_compound" in names
        assert "idx_reaction_products_compound" in names
        assert "idx_pathway_compounds_compound" in names
        assert "idx_compound_aliases_alias" in names
    finally:
        conn.close()


def test_build_reaction_graph_writes_alias_table(tmp_path):
    kgml_dir = tmp_path / "kgml"
    kgml_dir.mkdir()
    _write_minimal_kgml(kgml_dir / "hsa99999.xml")
    curated = tmp_path / "curated.jsonl"
    curated.write_text(json.dumps({
        "name": "Test compound",
        "kegg_id": "C00001",
        "hmdb_id": "HMDB0099001",
        "inchikey_first_block": "ZZZZZZZZZZZZZZ",
    }) + "\n")
    out_db = tmp_path / "graph.sqlite"
    summary = build_reaction_graph(kgml_dir, out_db, curated_path=curated)
    # name (incl. L-/D- variants) + inchikey14 + hmdb + kegg
    assert summary["n_compound_aliases"] >= 4

    conn = sqlite3.connect(out_db)
    try:
        # Lookup by name
        row = conn.execute(
            "SELECT compound_id FROM compound_aliases WHERE alias = ? AND source = 'name'",
            ("test compound",),
        ).fetchone()
        assert row[0] == "cpd:C00001"
        # Lookup by InChIKey first-block
        row2 = conn.execute(
            "SELECT compound_id FROM compound_aliases WHERE alias = ? AND source = 'inchikey14'",
            ("zzzzzzzzzzzzzz",),
        ).fetchone()
        assert row2[0] == "cpd:C00001"
        # Compounds.name was populated from the alias
        n = conn.execute(
            "SELECT name FROM compounds WHERE compound_id = ?",
            ("cpd:C00001",),
        ).fetchone()
        assert n[0] == "test compound"
    finally:
        conn.close()


def test_compound_alias_resolution_inchikey_to_kegg(tmp_path):
    """Real curated-pool round-trip: lookup InChIKey first-block →
    cpd:C-id, then back to the human-readable name."""
    kgml_dir = tmp_path / "kgml"
    kgml_dir.mkdir()
    _write_minimal_kgml(kgml_dir / "hsa99999.xml")
    curated = Path(_REPO_ROOT) / "data" / "benchmark" / "sub6" / "curated_hmdb_mammalian.jsonl"
    if not curated.is_file():
        pytest.skip("curated pool not available")
    out_db = tmp_path / "graph.sqlite"
    build_reaction_graph(kgml_dir, out_db, curated_path=curated)

    conn = sqlite3.connect(out_db)
    try:
        # Pyruvic acid: inchikey first-block LCTONWCANYUPML → KEGG C00022
        # (curated_hmdb_mammalian.jsonl line 1; pyruvate is a stable
        # canonical pick for a smoke test).
        row = conn.execute(
            "SELECT compound_id FROM compound_aliases WHERE alias = ? AND source = 'inchikey14'",
            ("lctonwcanyupml",),
        ).fetchone()
        assert row is not None and row[0] == "cpd:C00022"
        # Round-trip via name lookup — multiple aliases per compound
        # (canonical + L-/D- + ate/acid variants).
        rows2 = conn.execute(
            "SELECT alias FROM compound_aliases WHERE compound_id = ? AND source = 'name'",
            ("cpd:C00022",),
        ).fetchall()
        aliases = {r[0] for r in rows2}
        assert any("pyruvic" in a for a in aliases), aliases
        assert any("pyruvate" in a for a in aliases), aliases
    finally:
        conn.close()


def test_build_reaction_graph_idempotent(tmp_path):
    """Re-running over the same KGML dir must produce the same
    counts (no duplicates from PRIMARY KEY conflict). Output file is
    overwritten on each build."""
    kgml_dir = tmp_path / "kgml"
    kgml_dir.mkdir()
    _write_minimal_kgml(kgml_dir / "hsa99999.xml")
    out_db = tmp_path / "graph.sqlite"
    s1 = build_reaction_graph(kgml_dir, out_db)
    s2 = build_reaction_graph(kgml_dir, out_db)
    assert s1 == s2


def test_reversibility_flag_persisted(tmp_path):
    kgml_dir = tmp_path / "kgml"
    kgml_dir.mkdir()
    _write_minimal_kgml(kgml_dir / "hsa99999.xml")
    out_db = tmp_path / "graph.sqlite"
    build_reaction_graph(kgml_dir, out_db)

    conn = sqlite3.connect(out_db)
    try:
        rows = dict(conn.execute(
            "SELECT reaction_id, reversible FROM reactions"
        ).fetchall())
        assert rows["rn:R00001"] == 0
        assert rows["rn:R00002"] == 1
    finally:
        conn.close()
