"""Unit tests for Layer 6d — PATHWAY_RELATIONSHIP verification."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from schemas.sub6_report import SubsixSourceReport
from verifier.layers.pathway_relationship import verify_pathway_relationship
from verifier.schemas import (
    ClaimSubtype,
    ClaimType,
    ClaimVerdict,
    ClassifiedClaim,
)


# ---------------------------------------------------------------------------
# In-memory RaMP fixture: minimal pathway + analytehaspathway rows.
# ---------------------------------------------------------------------------


@pytest.fixture
def ramp_conn() -> sqlite3.Connection:
    """Build a tiny in-memory RaMP-like DB with two related pathways."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE pathway (
            pathwayRampId VARCHAR(30) PRIMARY KEY,
            sourceId VARCHAR(30),
            type VARCHAR(30),
            pathwayCategory VARCHAR(30),
            pathwayName VARCHAR(250) COLLATE NOCASE
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE analytehaspathway (
            rampId VARCHAR(30),
            pathwayRampId VARCHAR(30),
            pathwaySource VARCHAR(30)
        )
        """
    )
    cur.executemany(
        "INSERT INTO pathway VALUES (?, ?, ?, ?, ?)",
        [
            ("RAMP_P_000000001", "map00350", "kegg", None, "Tyrosine metabolism"),
            ("RAMP_P_000000002", "map00360", "kegg", None, "Phenylalanine metabolism"),
            ("RAMP_P_000000003", "map00052", "kegg", None, "Galactose metabolism"),
            ("RAMP_P_000000004", "smp00500", "smpdb", None, "Tyrosine metabolism"),
        ],
    )
    # Tyrosine ↔ Phenylalanine share 3 compounds.
    # Tyrosine ↔ Galactose share 0 compounds.
    cur.executemany(
        "INSERT INTO analytehaspathway VALUES (?, ?, ?)",
        [
            ("RAMP_C_TYR1", "RAMP_P_000000001", "kegg"),
            ("RAMP_C_TYR2", "RAMP_P_000000001", "kegg"),
            ("RAMP_C_TYR3", "RAMP_P_000000001", "kegg"),
            ("RAMP_C_TYR4", "RAMP_P_000000001", "kegg"),
            ("RAMP_C_TYR1", "RAMP_P_000000002", "kegg"),  # shared 1
            ("RAMP_C_TYR2", "RAMP_P_000000002", "kegg"),  # shared 2
            ("RAMP_C_TYR3", "RAMP_P_000000002", "kegg"),  # shared 3
            ("RAMP_C_PHE1", "RAMP_P_000000002", "kegg"),  # only PHE
            ("RAMP_C_GAL1", "RAMP_P_000000003", "kegg"),
            ("RAMP_C_GAL2", "RAMP_P_000000003", "kegg"),
            # SMPDB duplicate of Tyrosine shares 1 compound with Galactose.
            ("RAMP_C_TYR1", "RAMP_P_000000004", "smpdb"),
            ("RAMP_C_GAL1", "RAMP_P_000000004", "smpdb"),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def task() -> SubsixSourceReport:
    return SubsixSourceReport(
        task_id="rel_test",
        task_type="compound_only_enrichment",
        ground_truth_pathway={"pathway_id": "RAMP_P_000000001"},
        ground_truth_signal_compounds=[],
        ground_truth_noise_compounds=[],
        ramp_enrichment_result={"top_pathways": []},
    )


def _claim(text: str) -> ClassifiedClaim:
    return ClassifiedClaim(
        claim_text=text,
        claim_type=ClaimType.PATHWAY_RELATIONSHIP,
        classifier_source="rule",
    )


# ---------------------------------------------------------------------------
# SUPPORTED — shared intermediates / cross-talk
# ---------------------------------------------------------------------------


def test_relationship_shared_intermediates_supported(task, ramp_conn):
    r = verify_pathway_relationship(
        _claim(
            "Tyrosine metabolism and Phenylalanine metabolism share several "
            "intermediates."
        ),
        task,
        conn=ramp_conn,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert r.enrichment_context is not None
    assert r.enrichment_context.shared_compound_count == 3
    assert r.enrichment_context.relationship_type == "shared_intermediates"


def test_relationship_cross_talk_supported(task, ramp_conn):
    r = verify_pathway_relationship(
        _claim(
            "There is significant cross-talk between Tyrosine metabolism "
            "and Phenylalanine metabolism."
        ),
        task,
        conn=ramp_conn,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert r.enrichment_context.relationship_type == "cross_talk"


# ---------------------------------------------------------------------------
# CONTRADICTED — no shared compounds
# ---------------------------------------------------------------------------


def test_relationship_no_shared_compounds_contradicted(task, ramp_conn):
    r = verify_pathway_relationship(
        _claim(
            "Tyrosine metabolism and Galactose metabolism share several "
            "intermediates."
        ),
        task,
        conn=ramp_conn,
    )
    assert r.verdict == ClaimVerdict.CONTRADICTED
    assert r.enrichment_context.shared_compound_count == 0


# ---------------------------------------------------------------------------
# UNSUPPORTED — exactly 1 shared compound (weak)
# ---------------------------------------------------------------------------


def test_relationship_one_shared_compound_unsupported(task, ramp_conn):
    """SMPDB-Tyrosine duplicate shares exactly 1 compound with Galactose
    (RAMP_C_TYR1 ↔ RAMP_C_GAL1) — weak overlap."""
    # Use unique-pathway phrasing so resolution picks SMPDB row.
    # The fixture has one pathway named "Tyrosine metabolism" (KEGG),
    # but two rows share the same name. We resolve by length-asc, so
    # both compete; prefer-KEGG rule means KEGG wins — KEGG-Tyrosine
    # vs Galactose has 0 shared. The SMPDB-Tyrosine has 1 shared but
    # never beats KEGG.
    # To exercise the "exactly 1" branch, we need a different fixture
    # path. Add a direct ID claim to bypass name resolution.
    r = verify_pathway_relationship(
        _claim(
            "Pathway RAMP_P_000000004 and pathway RAMP_P_000000003 share intermediates."
        ),
        task,
        conn=ramp_conn,
    )
    assert r.verdict == ClaimVerdict.UNSUPPORTED
    assert r.enrichment_context.shared_compound_count == 1


# ---------------------------------------------------------------------------
# Directional claims — pre-D5 the layer always returned UNVERIFIABLE_V0.
# After track_verifier_kegg_hierarchy D5 the layer falls through to KEGG;
# UNVERIFIABLE_V0 is only the verdict when KEGG is *unavailable* and
# RaMP can't help. Keep both branches under coverage.
# ---------------------------------------------------------------------------


def test_relationship_upstream_unverifiable_when_kegg_unavailable(task, ramp_conn, monkeypatch, tmp_path):
    """When METAGENT_KEGG_PATH is unset and the default reaction-graph
    file is missing, the directional branch must still fall back to
    UNVERIFIABLE_V0 with hierarchy_data_available=False (the historical
    contract documented in the verifier delivery report)."""
    # Ensure KEGG default + env both invisible
    monkeypatch.delenv("METAGENT_KEGG_PATH", raising=False)
    bogus = tmp_path / "no_kegg.sqlite"
    r = verify_pathway_relationship(
        _claim(
            "Tyrosine metabolism is upstream of Phenylalanine metabolism."
        ),
        task,
        conn=ramp_conn,
        kegg_db_path=str(bogus),  # explicit — bypasses default file lookup
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert r.enrichment_context.hierarchy_data_available is False
    assert r.enrichment_context.relationship_type == "upstream"


def test_relationship_downstream_unverifiable_when_kegg_unavailable(task, ramp_conn, monkeypatch, tmp_path):
    monkeypatch.delenv("METAGENT_KEGG_PATH", raising=False)
    bogus = tmp_path / "no_kegg.sqlite"
    r = verify_pathway_relationship(
        _claim(
            "Statin pathway is downstream of mevalonate biosynthesis."
        ),
        task,
        conn=ramp_conn,
        kegg_db_path=str(bogus),
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


# ---------------------------------------------------------------------------
# UNVERIFIABLE — pathway resolution failure
# ---------------------------------------------------------------------------


def test_relationship_pathway_name_unresolvable_unverifiable(task, ramp_conn):
    r = verify_pathway_relationship(
        _claim(
            "Foobarine metabolism and Quuxotide metabolism share intermediates."
        ),
        task,
        conn=ramp_conn,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_relationship_only_one_pathway_in_claim_unverifiable(task, ramp_conn):
    r = verify_pathway_relationship(
        _claim("Tyrosine metabolism shares compounds with other pathways."),
        task,
        conn=ramp_conn,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


def test_relationship_no_relationship_keyword_unverifiable(task, ramp_conn):
    r = verify_pathway_relationship(
        _claim(
            "Tyrosine metabolism and Phenylalanine metabolism are interesting."
        ),
        task,
        conn=ramp_conn,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


# ---------------------------------------------------------------------------
# UNVERIFIABLE — DB unavailable
# ---------------------------------------------------------------------------


def test_relationship_db_unavailable_unverifiable(task, monkeypatch):
    monkeypatch.delenv("METAGENT_RAMP_PATH", raising=False)
    r = verify_pathway_relationship(
        _claim(
            "Tyrosine metabolism and Phenylalanine metabolism share "
            "intermediates."
        ),
        task,
        # No conn injected, no env var → DB unavailable.
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0


# ---------------------------------------------------------------------------
# Subtype + layer attribution
# ---------------------------------------------------------------------------


def test_relationship_subtype_and_layer_attribution(task, ramp_conn):
    r = verify_pathway_relationship(
        _claim(
            "Tyrosine metabolism and Phenylalanine metabolism share several "
            "intermediates."
        ),
        task,
        conn=ramp_conn,
    )
    assert r.claim_subtype == ClaimSubtype.PATHWAY_SHARED_INTERMEDIATES
    assert r.verifier_layer == "pathway_relationship"
    assert r.tool_called == "ramp_db"


# ---------------------------------------------------------------------------
# D5 — KEGG reaction-graph hierarchy (track_verifier_kegg_hierarchy)
# ---------------------------------------------------------------------------


@pytest.fixture
def kegg_conn():
    """Open the live KEGG reaction graph; skip when not built."""
    p = Path(__file__).resolve().parents[2] / "data" / "kegg" / "reaction_graph.sqlite"
    if not p.is_file():
        pytest.skip("KEGG reaction graph not built")
    conn = sqlite3.connect(str(p))
    yield conn
    conn.close()


def test_layer_6d_upstream_supported_via_kegg(task, ramp_conn, kegg_conn):
    """Methionine → SAM → SAH → Homocysteine is textbook biology;
    Layer 6d should now SUPPORT the claim with the KEGG path."""
    r = verify_pathway_relationship(
        _claim("Methionine is upstream of homocysteine generation"),
        task,
        conn=ramp_conn,
        kegg_conn=kegg_conn,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert r.enrichment_context.hierarchy_data_available is True
    tool_ev = r.enrichment_context.tool_evidence
    assert tool_ev.get("kegg_resolution") == "compound"
    assert tool_ev.get("kegg_path_length") is not None
    assert tool_ev.get("kegg_path_length") <= 6
    # Path passes through SAM (cpd:C00019) or SAH (cpd:C00021)
    path = set(tool_ev.get("kegg_path") or [])
    assert "cpd:C00019" in path or "cpd:C00021" in path


def test_layer_6d_downstream_swap_correct(task, ramp_conn, kegg_conn):
    """'Homocysteine is downstream of Methionine' must produce the SAME
    SUPPORTED verdict as 'Methionine is upstream of Homocysteine'.
    The downstream→upstream direction swap is the layer's job."""
    r = verify_pathway_relationship(
        _claim("Homocysteine is downstream of Methionine"),
        task,
        conn=ramp_conn,
        kegg_conn=kegg_conn,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    assert r.enrichment_context.hierarchy_data_available is True


def test_layer_6d_inverted_methionine_cycle_is_bidirectional(task, ramp_conn, kegg_conn):
    """The methionine cycle's reactions are reversible in KEGG (R00946,
    etc.), so 'Homocysteine is upstream of Methionine' is also true at
    the graph level. The layer should report SUPPORTED with
    direction='bidirectional' so the audit trail captures the cycle."""
    r = verify_pathway_relationship(
        _claim("Homocysteine is upstream of Methionine"),
        task,
        conn=ramp_conn,
        kegg_conn=kegg_conn,
    )
    assert r.verdict == ClaimVerdict.SUPPORTED
    tool_ev = r.enrichment_context.tool_evidence
    assert tool_ev.get("kegg_direction") in {"forward", "bidirectional"}


def test_layer_6d_direction_inverted_contradicted_synthetic():
    """Synthetic graph with a strictly irreversible one-way edge:
    A → B (irreversible), so the claim "B is upstream of A" must be
    CONTRADICTED with a correction citing the reverse path."""
    import textwrap
    from tools.kegg.graph_builder import build_reaction_graph
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        kgml_dir = td_path / "kgml"
        kgml_dir.mkdir()
        (kgml_dir / "hsa99001.xml").write_text(textwrap.dedent("""\
            <?xml version="1.0"?>
            <pathway name="path:hsa99001" org="hsa" number="99001">
                <entry id="1" name="cpd:C90001" type="compound"/>
                <entry id="2" name="cpd:C90002" type="compound"/>
                <reaction id="100" name="rn:R90001" type="irreversible">
                    <substrate id="1" name="cpd:C90001"/>
                    <product id="2" name="cpd:C90002"/>
                </reaction>
            </pathway>
        """))
        curated = td_path / "curated.jsonl"
        curated.write_text(
            '{"name": "Alpha", "kegg_id": "C90001", "inchikey_first_block": "AAAAAAAAAAAAAA"}\n'
            '{"name": "Beta",  "kegg_id": "C90002", "inchikey_first_block": "BBBBBBBBBBBBBB"}\n'
        )
        kegg_db = td_path / "kegg.sqlite"
        build_reaction_graph(kgml_dir, kegg_db, curated_path=curated)

        kegg_conn = sqlite3.connect(str(kegg_db))
        try:
            # Build a minimal SubsixSourceReport for fixture parity.
            task = SubsixSourceReport(
                task_id="test",
                task_type="compound_only_enrichment",
                domain="mammalian",
                ground_truth_pathway={"pathway_name": "X"},
                ground_truth_signal_compounds=[],
                ground_truth_noise_compounds=[],
                ramp_enrichment_result={"top_pathways": []},
            )
            # Claim: "Beta is upstream of Alpha" — but graph has only
            # Alpha → Beta direction (irreversible). Should be
            # CONTRADICTED.
            r = verify_pathway_relationship(
                _claim("Beta is upstream of Alpha"),
                task,
                conn=None,           # RaMP not needed for compound branch
                kegg_conn=kegg_conn,
            )
            assert r.verdict == ClaimVerdict.CONTRADICTED
            assert r.correction is not None
            assert "inverted" in r.evidence.lower() or "reverse" in r.evidence.lower()
        finally:
            kegg_conn.close()


def test_layer_6d_unresolvable_compound_unverifiable(task, ramp_conn, kegg_conn):
    """A claim with endpoints not in the KEGG alias table falls through
    to UNVERIFIABLE_V0 with a *KEGG* reason (no longer the historical
    'no hierarchy table' reason)."""
    r = verify_pathway_relationship(
        _claim("CarbonSpaghetti is upstream of QuantumWidget"),
        task,
        conn=ramp_conn,
        kegg_conn=kegg_conn,
    )
    assert r.verdict == ClaimVerdict.UNVERIFIABLE_V0
    assert r.enrichment_context.hierarchy_data_available is True  # KEGG was tried
    assert "KEGG reaction graph" in r.evidence


def test_layer_6d_cross_talk_branch_unchanged(task, ramp_conn, kegg_conn):
    """Cross-talk / shared-intermediates verdict must NOT change when
    KEGG is wired in — KEGG only powers the directional branch."""
    r = verify_pathway_relationship(
        _claim(
            "Tyrosine metabolism and Phenylalanine metabolism share several "
            "intermediates."
        ),
        task,
        conn=ramp_conn,
        kegg_conn=kegg_conn,
    )
    assert r.claim_subtype == ClaimSubtype.PATHWAY_SHARED_INTERMEDIATES
    assert r.verifier_layer == "pathway_relationship"
    assert r.tool_called == "ramp_db"
    # The KEGG-specific tool_evidence keys must NOT be set — branch
    # untouched.
    tool_ev = r.enrichment_context.tool_evidence or {}
    assert "kegg_path" not in tool_ev
    assert "kegg_resolution" not in tool_ev
