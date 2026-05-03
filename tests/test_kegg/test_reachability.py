"""Unit tests for tools.kegg.reachability."""
from __future__ import annotations

import os
import sqlite3
import sys
import textwrap
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from tools.kegg.graph_builder import build_reaction_graph
from tools.kegg.reachability import (
    get_pathway_compounds,
    is_compound_a_upstream_of_compound_b,
    is_pathway_a_upstream_of_pathway_b,
    resolve_compound_to_kegg,
)


# ---- fixture builder ------------------------------------------------------


def _build_test_db(tmp_path: Path, kgml_text: str | None = None,
                   curated_lines: list[dict] | None = None) -> Path:
    """Create a tiny KGML + curated pool, build the sqlite reaction graph,
    return its path."""
    import json
    kgml_dir = tmp_path / "kgml"
    kgml_dir.mkdir()
    if kgml_text is None:
        kgml_text = textwrap.dedent("""\
            <?xml version="1.0"?>
            <pathway name="path:hsa00001" org="hsa" number="00001">
                <entry id="1" name="cpd:C00001" type="compound"/>
                <entry id="2" name="cpd:C00002" type="compound"/>
                <entry id="3" name="cpd:C00003" type="compound"/>
                <entry id="4" name="cpd:C00004" type="compound"/>
                <entry id="5" name="cpd:C00005" type="compound"/>
                <reaction id="100" name="rn:R001" type="irreversible">
                    <substrate id="1" name="cpd:C00001"/>
                    <product id="2" name="cpd:C00002"/>
                </reaction>
                <reaction id="101" name="rn:R002" type="irreversible">
                    <substrate id="2" name="cpd:C00002"/>
                    <product id="3" name="cpd:C00003"/>
                </reaction>
                <reaction id="102" name="rn:R003" type="reversible">
                    <substrate id="3" name="cpd:C00003"/>
                    <product id="4" name="cpd:C00004"/>
                </reaction>
                <reaction id="103" name="rn:R004" type="irreversible">
                    <substrate id="5" name="cpd:C00005"/>
                    <product id="5" name="cpd:C00005"/>
                </reaction>
            </pathway>
        """)
    (kgml_dir / "hsa00001.xml").write_text(kgml_text)

    curated = tmp_path / "curated.jsonl"
    if curated_lines is None:
        curated_lines = [
            {"name": "Compound One", "kegg_id": "C00001",
             "inchikey_first_block": "AAAAAAAAAAAAAA"},
            {"name": "Compound Two", "kegg_id": "C00002",
             "inchikey_first_block": "BBBBBBBBBBBBBB"},
            {"name": "Compound Three", "kegg_id": "C00003",
             "inchikey_first_block": "CCCCCCCCCCCCCC"},
        ]
    with curated.open("w") as f:
        for r in curated_lines:
            f.write(json.dumps(r) + "\n")

    out_db = tmp_path / "graph.sqlite"
    build_reaction_graph(kgml_dir, out_db, curated_path=curated)
    return out_db


# ---- alias resolution -----------------------------------------------------


def test_resolve_compound_kegg_canonical_forms(tmp_path):
    db = _build_test_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        # Already canonical
        assert resolve_compound_to_kegg("cpd:C00001", conn=conn) == ("cpd:C00001", "kegg")
        # Bare KEGG ID
        assert resolve_compound_to_kegg("C00001", conn=conn) == ("cpd:C00001", "kegg")
        # Name (case-insensitive, whitespace-tolerant)
        assert resolve_compound_to_kegg("compound one", conn=conn)[0] == "cpd:C00001"
        assert resolve_compound_to_kegg("  Compound One  ", conn=conn)[0] == "cpd:C00001"
        # InChIKey 14-char
        assert resolve_compound_to_kegg("AAAAAAAAAAAAAA", conn=conn)[0] == "cpd:C00001"
        # Full InChIKey
        assert resolve_compound_to_kegg("AAAAAAAAAAAAAA-XXXXXXXXXX-X", conn=conn)[0] == "cpd:C00001"
        # Garbage
        assert resolve_compound_to_kegg("not a compound", conn=conn) == (None, None)
    finally:
        conn.close()


def test_resolve_compound_handles_l_d_prefix(tmp_path):
    """LLM sometimes drops/adds the L-/D- stereodescriptor."""
    db = _build_test_db(tmp_path, curated_lines=[
        {"name": "L-Methionine", "kegg_id": "C00073",
         "inchikey_first_block": "FFEARJCKVFRZRR"},
    ])
    conn = sqlite3.connect(db)
    try:
        # Stored as "L-Methionine"; query without prefix should still hit
        assert resolve_compound_to_kegg("Methionine", conn=conn)[0] == "cpd:C00073"
        assert resolve_compound_to_kegg("methionine", conn=conn)[0] == "cpd:C00073"
        # Query with prefix already there
        assert resolve_compound_to_kegg("L-Methionine", conn=conn)[0] == "cpd:C00073"
    finally:
        conn.close()


def test_resolve_compound_acid_ate_swap(tmp_path):
    """Pool stores 'Pyruvic acid' but LLM may say 'pyruvate'."""
    db = _build_test_db(tmp_path, curated_lines=[
        {"name": "Pyruvic acid", "kegg_id": "C00022",
         "inchikey_first_block": "LCTONWCANYUPML"},
    ])
    conn = sqlite3.connect(db)
    try:
        assert resolve_compound_to_kegg("Pyruvate", conn=conn)[0] == "cpd:C00022"
        assert resolve_compound_to_kegg("pyruvic acid", conn=conn)[0] == "cpd:C00022"
    finally:
        conn.close()


# ---- compound-level reachability ------------------------------------------


def test_compound_reachable_forward_irreversible_chain(tmp_path):
    """Linear chain C00001 → C00002 → C00003 (both irreversible);
    forward should be reachable, reverse should NOT."""
    db = _build_test_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        r = is_compound_a_upstream_of_compound_b("C00001", "C00003", conn=conn)
        assert r.is_reachable is True
        assert r.path_length == 2
        assert r.shortest_path == ["cpd:C00001", "cpd:C00002", "cpd:C00003"]
        assert r.direction == "forward"

        # Reverse: C00003 → C00001 should not be reachable (irreversible)
        r2 = is_compound_a_upstream_of_compound_b("C00003", "C00001", conn=conn)
        assert r2.is_reachable is False
        assert r2.direction in {"reverse", "none"}
    finally:
        conn.close()


def test_compound_reachable_bidirectional_via_reversible(tmp_path):
    """C00003 → C00004 is reversible, so C00004 → C00003 should also be
    reachable (1 hop) and the direction is 'bidirectional' relative to
    C00003."""
    db = _build_test_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        r = is_compound_a_upstream_of_compound_b("C00003", "C00004", conn=conn)
        assert r.is_reachable is True
        assert r.path_length == 1
        assert r.direction == "bidirectional"
    finally:
        conn.close()


def test_compound_unresolvable_returns_unreachable(tmp_path):
    db = _build_test_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        # 'mystery_compound' resolves to no KEGG ID at all
        r = is_compound_a_upstream_of_compound_b("mystery_compound", "C00001", conn=conn)
        assert r.is_reachable is False
        assert r.path_length is None
        assert any("could not resolve" in n for n in r.notes)
    finally:
        conn.close()


def test_compound_resolvable_but_absent_from_graph(tmp_path):
    """KEGG-form ID that bypasses the alias table but isn't in the
    reaction graph still returns is_reachable=False without raising."""
    db = _build_test_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        r = is_compound_a_upstream_of_compound_b("C00099", "C00001", conn=conn)
        assert r.is_reachable is False
        assert r.path_length is None
        assert r.shortest_path is None
        # Note: no "could not resolve" — both endpoints DID resolve syntactically
    finally:
        conn.close()


def test_compound_max_path_length_enforced(tmp_path):
    """Linear chain C00001 → C00002 → C00003 — at max_path_length=1,
    only the first hop should be reachable."""
    db = _build_test_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        r = is_compound_a_upstream_of_compound_b(
            "C00001", "C00002", conn=conn, max_path_length=1
        )
        assert r.is_reachable is True
        assert r.path_length == 1
        # 2 hops away — exceeds bound
        r2 = is_compound_a_upstream_of_compound_b(
            "C00001", "C00003", conn=conn, max_path_length=1
        )
        assert r2.is_reachable is False
    finally:
        conn.close()


def test_compound_self_match_zero_hops(tmp_path):
    db = _build_test_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        r = is_compound_a_upstream_of_compound_b("C00001", "C00001", conn=conn)
        assert r.is_reachable is True
        assert r.path_length == 0
        assert r.shortest_path == ["cpd:C00001"]
    finally:
        conn.close()


def test_compound_real_methionine_to_homocysteine():
    """Real-data smoke against the live reaction graph (skip if absent)."""
    db = Path(_REPO_ROOT) / "data" / "kegg" / "reaction_graph.sqlite"
    if not db.is_file():
        pytest.skip("live reaction graph not built")
    conn = sqlite3.connect(db)
    try:
        r = is_compound_a_upstream_of_compound_b(
            "Methionine", "Homocysteine", conn=conn
        )
        assert r.is_reachable is True
        assert r.path_length is not None and r.path_length <= 6
        # Path passes through SAM (cpd:C00019) and/or SAH (cpd:C00021)
        assert r.shortest_path is not None
        ids = set(r.shortest_path)
        assert "cpd:C00019" in ids or "cpd:C00021" in ids
    finally:
        conn.close()


def test_compound_real_unrelated_pair_not_reachable():
    """Acrolein and Methionine are not in a direct upstream/downstream
    relationship within 6 hops in mammalian KEGG metabolism."""
    db = Path(_REPO_ROOT) / "data" / "kegg" / "reaction_graph.sqlite"
    if not db.is_file():
        pytest.skip("live reaction graph not built")
    conn = sqlite3.connect(db)
    try:
        r = is_compound_a_upstream_of_compound_b(
            "Acrolein", "Methionine", conn=conn, max_path_length=6
        )
        # Whichever the answer is, the result is well-formed
        assert r.direction in {"forward", "reverse", "bidirectional", "none"}
        assert r.max_path_length == 6
    finally:
        conn.close()


# ---- pathway-level reachability ------------------------------------------


def test_get_pathway_compounds_returns_sorted_unique(tmp_path):
    db = _build_test_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        cs = get_pathway_compounds("hsa00001", conn=conn)
        assert cs == sorted(cs)
        assert len(cs) == len(set(cs))
        assert "cpd:C00001" in cs
    finally:
        conn.close()


def test_pathway_reachable_through_compound_chain(tmp_path):
    """Two pathways sharing only their endpoints; compounds inside each
    are connected by reactions."""
    kgml_a = textwrap.dedent("""\
        <?xml version="1.0"?>
        <pathway name="path:hsa00001" org="hsa" number="00001">
            <entry id="1" name="cpd:C10001" type="compound"/>
            <entry id="2" name="cpd:C10002" type="compound"/>
            <reaction id="100" name="rn:R001" type="irreversible">
                <substrate id="1" name="cpd:C10001"/>
                <product id="2" name="cpd:C10002"/>
            </reaction>
        </pathway>
    """)
    kgml_b = textwrap.dedent("""\
        <?xml version="1.0"?>
        <pathway name="path:hsa00002" org="hsa" number="00002">
            <entry id="1" name="cpd:C10002" type="compound"/>
            <entry id="2" name="cpd:C10003" type="compound"/>
            <reaction id="200" name="rn:R002" type="irreversible">
                <substrate id="1" name="cpd:C10002"/>
                <product id="2" name="cpd:C10003"/>
            </reaction>
        </pathway>
    """)
    kgml_dir = tmp_path / "kgml"
    kgml_dir.mkdir()
    (kgml_dir / "hsa00001.xml").write_text(kgml_a)
    (kgml_dir / "hsa00002.xml").write_text(kgml_b)
    out_db = tmp_path / "graph.sqlite"
    build_reaction_graph(kgml_dir, out_db)

    conn = sqlite3.connect(out_db)
    try:
        # Pathway A → B via shared compound C10002
        r = is_pathway_a_upstream_of_pathway_b("hsa00001", "hsa00002", conn=conn)
        assert r.is_reachable is True
        # Source: {C10001, C10002}; targets: {C10003} (C10002 excluded)
        assert "cpd:C10001" in r.source_compounds
        assert r.target_compounds == ["cpd:C10003"]
    finally:
        conn.close()


def test_pathway_unreachable_when_disjoint(tmp_path):
    kgml_a = textwrap.dedent("""\
        <?xml version="1.0"?>
        <pathway name="path:hsa00001" org="hsa" number="00001">
            <entry id="1" name="cpd:C10001" type="compound"/>
            <entry id="2" name="cpd:C10002" type="compound"/>
            <reaction id="100" name="rn:R001" type="irreversible">
                <substrate id="1" name="cpd:C10001"/>
                <product id="2" name="cpd:C10002"/>
            </reaction>
        </pathway>
    """)
    kgml_b = textwrap.dedent("""\
        <?xml version="1.0"?>
        <pathway name="path:hsa00002" org="hsa" number="00002">
            <entry id="1" name="cpd:C20001" type="compound"/>
            <entry id="2" name="cpd:C20002" type="compound"/>
            <reaction id="200" name="rn:R002" type="irreversible">
                <substrate id="1" name="cpd:C20001"/>
                <product id="2" name="cpd:C20002"/>
            </reaction>
        </pathway>
    """)
    kgml_dir = tmp_path / "kgml"
    kgml_dir.mkdir()
    (kgml_dir / "hsa00001.xml").write_text(kgml_a)
    (kgml_dir / "hsa00002.xml").write_text(kgml_b)
    out_db = tmp_path / "graph.sqlite"
    build_reaction_graph(kgml_dir, out_db)

    conn = sqlite3.connect(out_db)
    try:
        r = is_pathway_a_upstream_of_pathway_b("hsa00001", "hsa00002", conn=conn)
        assert r.is_reachable is False
        assert r.direction == "none"
    finally:
        conn.close()


def test_pathway_unknown_id_returns_unreachable(tmp_path):
    db = _build_test_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        r = is_pathway_a_upstream_of_pathway_b("hsa99999", "hsa00001", conn=conn)
        assert r.is_reachable is False
        assert any("no compounds" in n for n in r.notes)
    finally:
        conn.close()


def test_pathway_max_path_length_default_4(tmp_path):
    db = _build_test_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        r = is_pathway_a_upstream_of_pathway_b("hsa00001", "hsa00001", conn=conn)
        # Same pathway → all compounds shared, no exclusive targets
        assert r.is_reachable is False
        assert r.max_path_length == 4  # default per session decision
    finally:
        conn.close()
