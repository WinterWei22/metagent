# tests/test_pathway_relevant_set.py
from __future__ import annotations

import sqlite3

import pytest

from concord.agent import pathway_relevant_set as prs


def _ramp_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE pathway(pathwayRampId TEXT, sourceId TEXT, type TEXT,
                             pathwayCategory TEXT, pathwayName TEXT);
        CREATE TABLE analytehaspathway(rampId TEXT, pathwayRampId TEXT, pathwaySource TEXT);
        CREATE TABLE pathway_duplicates(pathwayRampId1 TEXT, pathwayRampId2 TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO pathway VALUES (?,?,?,?,?)",
        [
            ("P_GT", "map1", "kegg", "c", "Alanine metabolism"),
            ("P_DUP", "wp1", "wiki", "c", "Alanine Metabolism"),   # duplicate name/source
            ("P_NEAR", "map2", "kegg", "c", "Aspartate metabolism"),  # high overlap
            ("P_FAR", "map3", "kegg", "c", "Steroid biosynthesis"),   # no overlap
            ("P_HUGE", "map4", "kegg", "c", "Metabolism"),            # shares some, low jaccard
        ],
    )
    members = []
    for r in ["a", "b", "c", "d"]:
        members.append((r, "P_GT", "kegg"))
    for r in ["a", "b", "c", "e"]:   # 3/5 overlap with GT -> jaccard 3/5=0.6
        members.append((r, "P_NEAR", "kegg"))
    members.append(("z", "P_FAR", "kegg"))
    for r in ["a", "m1", "m2", "m3", "m4", "m5", "m6"]:  # shares 1, union large -> low jaccard
        members.append((r, "P_HUGE", "kegg"))
    conn.executemany("INSERT INTO analytehaspathway VALUES (?,?,?)", members)
    conn.execute("INSERT INTO pathway_duplicates VALUES ('P_GT','P_DUP')")
    conn.commit()
    return conn


def test_jaccard():
    assert prs.jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert prs.jaccard({"a"}, set()) == 0.0
    assert prs.jaccard({"a", "b", "c"}, {"a"}) == pytest.approx(1 / 3)


def test_relevant_set_includes_gt_dup_and_near_excludes_far_and_huge():
    conn = _ramp_conn()
    rel = prs.build_relevant_set_ramp(conn, "P_GT", jaccard_threshold=0.3)
    assert "alanine metabolism" in rel        # GT itself (normalized)
    assert "aspartate metabolism" in rel       # near neighbor (jaccard 0.6)
    assert "steroid biosynthesis" not in rel   # disjoint
    assert "metabolism" not in rel             # giant pathway, low jaccard


def _members_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE pathway_member(pathway_namespace TEXT, pathway_label_slug TEXT, "
        "pathway_name TEXT, member_chebi_id TEXT, member_mam_id TEXT, source TEXT)"
    )
    rows = []
    for m in ["c1", "c2", "c3", "c4"]:
        rows.append(("HUMAN1", "gt", "Acyl-CoA hydrolysis", m, m + "c", "human1"))
    for m in ["c1", "c2", "c3", "x"]:  # jaccard 3/5 = 0.6
        rows.append(("HUMAN1", "near", "Fatty acyl oxidation", m, m + "c", "human1"))
    rows.append(("HUMAN1", "far", "Glycolysis", "z", "zc", "human1"))
    rows.append(("RECON2", "other", "Acyl-CoA hydrolysis", "c1", "c1c", "recon2"))  # wrong source
    conn.executemany("INSERT INTO pathway_member VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


def test_relevant_set_modelorg_matches_name_within_source():
    conn = _members_conn()
    rel = prs.build_relevant_set_modelorg(
        conn, "Acyl-CoA hydrolysis", "human1", jaccard_threshold=0.3
    )
    # norm_name converts hyphens to spaces: "Acyl-CoA hydrolysis" -> "acyl coa hydrolysis"
    assert "acyl coa hydrolysis" in rel
    assert "fatty acyl oxidation" in rel
    assert "glycolysis" not in rel
