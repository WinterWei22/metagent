from __future__ import annotations

import sqlite3

from concord.agent import driver_gold as dg


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE source(sourceId TEXT, rampId TEXT, IDtype TEXT,
                            geneOrCompound TEXT, commonName TEXT,
                            priorityHMDBStatus TEXT, dataSource TEXT, pathwayCount INT);
        CREATE TABLE analytehaspathway(rampId TEXT, pathwayRampId TEXT, pathwaySource TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO source(sourceId,rampId,IDtype,geneOrCompound) VALUES (?,?,?,?)",
        [
            ("kegg:C00048", "RAMP_C_1", "kegg", "compound"),
            ("kegg:C00051", "RAMP_C_2", "kegg", "compound"),
            ("kegg:C99999", "RAMP_C_3", "kegg", "compound"),  # not a GT member
            ("chebi:16828", "RAMP_C_1", "chebi", "compound"),  # alt xref of same compound
        ],
    )
    conn.executemany(
        "INSERT INTO analytehaspathway VALUES (?,?,?)",
        [("RAMP_C_1", "P_GT", "kegg"), ("RAMP_C_2", "P_GT", "kegg")],
    )
    conn.commit()
    return conn


def test_resolve_handles_prefixes():
    conn = _conn()
    assert dg.resolve_to_ramp_id(conn, "C00048") == "RAMP_C_1"
    assert dg.resolve_to_ramp_id(conn, "KEGG:C00048") == "RAMP_C_1"
    assert dg.resolve_to_ramp_id(conn, "CHEBI:16828") == "RAMP_C_1"
    assert dg.resolve_to_ramp_id(conn, "C00000") is None


def test_gold_drivers_are_input_intersect_pathway_members():
    conn = _conn()
    gold = dg.build_gold_drivers_ramp(conn, ["C00048", "C00051", "C99999"], "P_GT")
    assert gold == {"RAMP_C_1", "RAMP_C_2"}
