from __future__ import annotations

import sqlite3

from concord.agent.pathway_prediction import norm_name
from scripts.metagent import build_gold_drivers as bgd
from scripts.metagent import build_relevant_pathway_sets as brs


def test_stratum_of():
    assert brs.stratum_of("s4_cooke_2025_human1_group1") == "human1"
    assert brs.stratum_of("s4_cooke_2025_recon2_2_subsystem27") == "recon2"
    assert brs.stratum_of("hmdb_ramp_easy_kegg_RAMP_P_1_rep0") == "hmdb_ramp"
    assert brs.stratum_of("sub6_easy_compound_only_enrich_mammalian_RAMP_P_1_seed0") == "sub6"


def test_gold_drivers_na_for_modelorg():
    assert bgd.stratum_of("s4_cooke_2025_human1_group1") == "human1"
    # human1/recon2 must map to null gold
    assert bgd.is_na_stratum("human1") is True
    assert bgd.is_na_stratum("recon2") is True
    assert bgd.is_na_stratum("sub6") is False
    assert bgd.is_na_stratum("hmdb_ramp") is False


# ---------------------------------------------------------------------------
# Helpers to build tiny in-memory sqlite dbs that mimic the real schemas
# ---------------------------------------------------------------------------

def _make_ramp_conn() -> sqlite3.Connection:
    """Minimal ramp.sqlite schema with a handful of rows."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE pathway (
            pathwayRampId TEXT PRIMARY KEY,
            sourceId TEXT,
            type TEXT,
            pathwayCategory TEXT,
            pathwayName TEXT
        );
        CREATE TABLE analytehaspathway (
            rampId TEXT,
            pathwayRampId TEXT,
            pathwaySource TEXT
        );
        CREATE TABLE pathway_duplicates (
            pathwayRampId1 TEXT,
            pathwayRampId2 TEXT
        );
        CREATE TABLE source (
            sourceId TEXT,
            rampId TEXT,
            IDtype TEXT,
            geneOrCompound TEXT
        );

        -- A real RAMP_P_* pathway with two compound members
        INSERT INTO pathway VALUES ('RAMP_P_1', 'HMDB:PW000001', 'pathway', NULL, 'Glycolysis');
        INSERT INTO analytehaspathway VALUES ('RAMP_C_1', 'RAMP_P_1', 'hmdb');
        INSERT INTO analytehaspathway VALUES ('RAMP_C_2', 'RAMP_P_1', 'hmdb');

        -- Compound xrefs so resolve_to_ramp_id can work
        INSERT INTO source VALUES ('kegg:C00031', 'RAMP_C_1', 'KEGG', 'compound');
        INSERT INTO source VALUES ('chebi:17234', 'RAMP_C_2', 'ChEBI', 'compound');
        """
    )
    return conn


def _make_members_conn() -> sqlite3.Connection:
    """Minimal pathway_members.sqlite schema (unused in these tests but required
    for build_all signature)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE pathway_members (
            pathway_name TEXT,
            stratum TEXT,
            member_name TEXT
        );
        """
    )
    return conn


# ---------------------------------------------------------------------------
# Fix A: relevant-set always contains the GT name, even for bogus GT ids
# ---------------------------------------------------------------------------

def _make_bench_row_bogus_id(task_id: str = "sub6_easy_bogus_id_seed0") -> dict:
    return {
        "task_id": task_id,
        "ground_truth": {
            "perturbed_pathway": {
                "id": "lm_pathway:WP167",
                "name": "Eicosanoid synthesis",
            }
        },
        "input": {"differential_metabolites": []},
    }


def test_relevant_set_always_seeds_gt_name_for_bogus_id():
    """GT id that doesn't exist in ramp.sqlite → relevant set still has norm_name(gt_name)."""
    row = _make_bench_row_bogus_id()
    ramp_conn = _make_ramp_conn()
    members_conn = _make_members_conn()
    result = brs.build_all([row], ramp_conn, members_conn)
    task_result = result["sub6_easy_bogus_id_seed0"]
    assert task_result["size"] >= 1, "size must be ≥ 1 (GT name always seeded)"
    expected_norm = norm_name("Eicosanoid synthesis")
    assert expected_norm in task_result["relevant_names"], (
        f"Expected '{expected_norm}' in relevant_names, got {task_result['relevant_names']}"
    )


# ---------------------------------------------------------------------------
# Fix B: gold is None when GT pathway has 0 members in ramp.sqlite
# ---------------------------------------------------------------------------

def _make_bench_row_resolvable(task_id: str = "sub6_easy_RAMP_P_1_seed0") -> dict:
    return {
        "task_id": task_id,
        "ground_truth": {
            "perturbed_pathway": {
                "id": "RAMP_P_1",
                "name": "Glycolysis",
            }
        },
        "input": {
            "differential_metabolites": [
                {"id": "kegg:C00031"},   # → RAMP_C_1 (member)
                {"id": "kegg:C99999"},   # not in DB
            ]
        },
    }


def _make_bench_row_unresolvable(task_id: str = "sub6_easy_bogus_gold_seed0") -> dict:
    return {
        "task_id": task_id,
        "ground_truth": {
            "perturbed_pathway": {
                "id": "lm_pathway:WP167",
                "name": "Eicosanoid synthesis",
            }
        },
        "input": {
            "differential_metabolites": [{"id": "kegg:C00031"}],
        },
    }


def test_gold_none_when_gt_pathway_unresolvable():
    """GT pathway with 0 members in ramp → None (N/A), not an empty gold set."""
    row = _make_bench_row_unresolvable()
    ramp_conn = _make_ramp_conn()
    result = bgd.build_all([row], ramp_conn)
    assert result["sub6_easy_bogus_gold_seed0"] is None, (
        "Expected None for unresolvable GT pathway id"
    )


def test_gold_empty_when_gt_resolvable_but_input_misses():
    """GT pathway exists (has members) but no input metabolite maps into it → empty gold set."""
    row = _make_bench_row_resolvable()
    # Use only a metabolite NOT in RAMP_P_1
    row["input"]["differential_metabolites"] = [{"id": "kegg:C99999"}]
    ramp_conn = _make_ramp_conn()
    result = bgd.build_all([row], ramp_conn)
    val = result["sub6_easy_RAMP_P_1_seed0"]
    assert val is not None, "Should be a dict, not None"
    assert val == {"gold_ramp_ids": []}, f"Expected empty gold set, got {val}"


def test_gold_populated_when_input_has_members():
    """GT pathway exists and at least one input metabolite maps into it."""
    row = _make_bench_row_resolvable()
    ramp_conn = _make_ramp_conn()
    result = bgd.build_all([row], ramp_conn)
    val = result["sub6_easy_RAMP_P_1_seed0"]
    assert val is not None
    assert "RAMP_C_1" in val["gold_ramp_ids"]
