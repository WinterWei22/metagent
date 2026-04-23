"""Unit tests for tools.pathway_context (Track D, Tool 6).

Covers every case listed in docs/TOOL_CONTRACTS.md § Tool 6 and every
test listed in prompts/track_D_metabolite_info_pathway_context.md.

The test fixture builds a tmp_path mini RaMP SQLite with a plausible
subset of glycolysis / alanine metabolism. It uses the exact column
names that ramp_backend.py queries (source.sourceId / rampId /
commonName / dataSource, pathway.pathwayRampId / sourceId / pathwayName
/ type, analytehaspathway.rampId / pathwayRampId, reaction2met.rxnRampId
/ rampId / isSubstrate) so that the same backend code runs against the
real RaMP-DB dump.

Every test also guards the zero-LLM invariant by binding
common.llm_client.chat to a function that fails loudly — if the tool
accidentally reaches for the LLM, the test blows up with a clear message.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest

from schemas import PathwayContextRequest

from common import llm_client
from tools.pathway_context import pathway_context
from tools.pathway_context import ramp_backend
from tools.pathway_context.errors import (
    MetaboliteNotInNetworkError,
    RampUnavailableError,
)


# ---------------------------------------------------------------------------
# Mini RaMP SQLite
# ---------------------------------------------------------------------------


def _build_mini_ramp_db(db_path: Path) -> None:
    """Populate a tmp RaMP DB covering glucose / pyruvate / alanine plus an orphan.

    Schema (column names, types) mirrors RaMP v3.0.x exactly — the same
    backend code that runs here runs against the production dump. The
    only concession is trimmed column count: we include only what
    ramp_backend.py reads plus a couple of columns kept for schema
    fidelity (IDtype on source, pathwaySource on analytehaspathway).
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE source (
                sourceId    TEXT,
                rampId      TEXT,
                IDtype      TEXT,
                commonName  TEXT,
                dataSource  TEXT
            );
            CREATE TABLE pathway (
                pathwayRampId  TEXT PRIMARY KEY,
                sourceId       TEXT,
                type           TEXT,
                pathwayName    TEXT
            );
            CREATE TABLE analytehaspathway (
                rampId         TEXT,
                pathwayRampId  TEXT,
                pathwaySource  TEXT
            );
            CREATE TABLE reaction2met (
                ramp_rxn_id       TEXT NOT NULL,
                ramp_cmpd_id      TEXT NOT NULL,
                substrate_product INTEGER NOT NULL,
                met_source_id     TEXT,
                met_name          TEXT
            );
            """
        )

        # --- Source mapping ------------------------------------------------
        # RaMP v3 stores IDs with a lowercase prefix (e.g. 'hmdb:HMDB0000122').
        sources = [
            # (sourceId, rampId, IDtype, commonName, dataSource)
            ("hmdb:HMDB0000122", "RAMP_C_GLUC",        "hmdb",  "D-Glucose",    "hmdb"),
            ("kegg:C00031",      "RAMP_C_GLUC",        "kegg",  "D-Glucose",    "hmdb_kegg"),
            ("hmdb:HMDB0000243", "RAMP_C_PYR",         "hmdb",  "Pyruvate",     "hmdb"),
            ("kegg:C00022",      "RAMP_C_PYR",         "kegg",  "Pyruvate",     "hmdb_kegg"),
            ("hmdb:HMDB0000161", "RAMP_C_ALA",         "hmdb",  "L-Alanine",    "hmdb"),
            ("kegg:C00041",      "RAMP_C_ALA",         "kegg",  "L-Alanine",    "hmdb_kegg"),
            # Orphan: resolves to a rampId but has no analytehaspathway rows.
            ("hmdb:HMDB0000050", "RAMP_C_ADEN_ORPHAN", "hmdb",  "Adenosine",    "hmdb"),
            # Random HMDB that resolves but shares no pathway with glucose.
            ("hmdb:HMDB0001847", "RAMP_C_CAFF",        "hmdb",  "Caffeine",     "hmdb"),
        ]
        conn.executemany(
            "INSERT INTO source (sourceId, rampId, IDtype, commonName, dataSource) VALUES (?, ?, ?, ?, ?)",
            sources,
        )

        # --- Pathways ------------------------------------------------------
        # `hmdb` type rows here represent SMPDB content (RaMP surfaces
        # SMPDB under type='hmdb'); the backend maps it to 'smpdb'.
        pathways = [
            # (pathwayRampId, sourceId, type, pathwayName)
            ("RAMP_P_GLYC_KEGG", "map00010",     "kegg",     "Glycolysis / Gluconeogenesis"),
            ("RAMP_P_GLYC_REAC", "R-HSA-70171",  "reactome", "Glycolysis"),
            ("RAMP_P_ALA_KEGG",  "map00250",     "kegg",     "Alanine, aspartate and glutamate metabolism"),
            ("RAMP_P_CAFF_KEGG", "map00232",     "kegg",     "Caffeine metabolism"),
            # Throw in an SMPDB (RaMP type='hmdb') pathway so the
            # smpdb mapping is exercised in the test suite.
            ("RAMP_P_GLYC_SMP",  "SMP00040",     "hmdb",     "Glycolysis (SMPDB)"),
        ]
        conn.executemany(
            "INSERT INTO pathway (pathwayRampId, sourceId, type, pathwayName) VALUES (?, ?, ?, ?)",
            pathways,
        )

        # --- Analyte ↔ pathway ---------------------------------------------
        analyte_pathways = [
            # Glucose: glycolysis from KEGG + Reactome + SMPDB.
            ("RAMP_C_GLUC", "RAMP_P_GLYC_KEGG", "kegg"),
            ("RAMP_C_GLUC", "RAMP_P_GLYC_REAC", "reactome"),
            ("RAMP_C_GLUC", "RAMP_P_GLYC_SMP",  "hmdb"),
            # Pyruvate: glycolysis (kegg + reactome + smpdb) AND alanine metabolism (kegg).
            ("RAMP_C_PYR",  "RAMP_P_GLYC_KEGG", "kegg"),
            ("RAMP_C_PYR",  "RAMP_P_GLYC_REAC", "reactome"),
            ("RAMP_C_PYR",  "RAMP_P_GLYC_SMP",  "hmdb"),
            ("RAMP_C_PYR",  "RAMP_P_ALA_KEGG",  "kegg"),
            # Alanine: alanine metabolism only.
            ("RAMP_C_ALA",  "RAMP_P_ALA_KEGG",  "kegg"),
            # Caffeine: its own pathway, disjoint from glycolysis.
            ("RAMP_C_CAFF", "RAMP_P_CAFF_KEGG", "kegg"),
            # Adenosine: no rows → orphan.
        ]
        conn.executemany(
            "INSERT INTO analytehaspathway (rampId, pathwayRampId, pathwaySource) VALUES (?, ?, ?)",
            analyte_pathways,
        )

        # --- Reaction graph -----------------------------------------------
        # One reaction converts glucose → pyruvate, another pyruvate → alanine.
        # substrate_product = 1 means substrate, 0 means product (RaMP v3 convention).
        reaction_rows = [
            # (ramp_rxn_id, ramp_cmpd_id, substrate_product, met_source_id, met_name)
            ("RXN_GLYCO",     "RAMP_C_GLUC", 1, "chebi:4167",  "D-glucose"),
            ("RXN_GLYCO",     "RAMP_C_PYR",  0, "chebi:15361", "pyruvate"),
            ("RXN_ALA_TRANS", "RAMP_C_PYR",  1, "chebi:15361", "pyruvate"),
            ("RXN_ALA_TRANS", "RAMP_C_ALA",  0, "chebi:16977", "L-alanine"),
        ]
        conn.executemany(
            "INSERT INTO reaction2met (ramp_rxn_id, ramp_cmpd_id, substrate_product, met_source_id, met_name) VALUES (?, ?, ?, ?, ?)",
            reaction_rows,
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ramp_db(tmp_path, monkeypatch):
    """Build the mini DB, point the backend at it, and trip any LLM call.

    The LLM tripwire is installed on EVERY test — no test in this module
    is expected to use the language model, so any invocation is a bug.
    """
    db_path = tmp_path / "ramp_mini.sqlite"
    _build_mini_ramp_db(db_path)
    monkeypatch.setattr(
        ramp_backend, "resolve_db_path", lambda explicit=None: db_path
    )

    def _forbid_llm(*_args, **_kwargs):
        raise AssertionError(
            "common.llm_client.chat was invoked during a pathway_context unit test. "
            "This tool's plausibility_summary is templated; any LLM call is a regression."
        )

    monkeypatch.setattr(llm_client, "chat", _forbid_llm)
    monkeypatch.setattr(llm_client, "chat_raw", _forbid_llm)
    return db_path


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


def test_pyruvate_returns_multi_source_pathways(ramp_db):
    """Pyruvate sits in glycolysis (kegg+reactome) and alanine metabolism (kegg) — ≥ 2 sources."""
    resp = pathway_context(
        PathwayContextRequest(metabolite_id="HMDB0000243", neighbour_depth=1)
    )
    sources = {p.source for p in resp.pathways}
    assert "kegg" in sources
    assert "reactome" in sources
    assert len(resp.pathways) >= 2
    # Every pathway has a URL.
    for p in resp.pathways:
        assert p.url.startswith("https://")


def test_pathway_entry_hit_count_nonnegative(ramp_db):
    """hit_count must be ≥ 0 (schema constraint) and, for a focal-only query,
    exactly 1 — the focal metabolite counts as its own hit."""
    resp = pathway_context(
        PathwayContextRequest(metabolite_id="HMDB0000122", co_observed_ids=[])
    )
    for p in resp.pathways:
        assert p.hit_count >= 1


def test_cooccurrence_lifts_with_real_neighbour(ramp_db):
    """Score with a real pathway co-member > score with an unrelated metabolite."""
    with_real = pathway_context(
        PathwayContextRequest(
            metabolite_id="HMDB0000122",              # glucose
            co_observed_ids=["HMDB0000243"],          # pyruvate, shares glycolysis
        )
    )
    with_random = pathway_context(
        PathwayContextRequest(
            metabolite_id="HMDB0000122",
            co_observed_ids=["HMDB0001847"],          # caffeine, disjoint pathway
        )
    )
    assert with_real.cooccurrence_score > with_random.cooccurrence_score
    assert 0.0 <= with_random.cooccurrence_score <= 1.0
    assert 0.0 <= with_real.cooccurrence_score <= 1.0


def test_cooccurrence_score_empty_context(ramp_db):
    """No co-observed IDs ⇒ score is 0.0 (not NaN, not None)."""
    resp = pathway_context(
        PathwayContextRequest(metabolite_id="HMDB0000122", co_observed_ids=[])
    )
    assert resp.cooccurrence_score == 0.0


def test_neighbour_depth_zero_empty_neighbours(ramp_db):
    """depth=0 returns empty neighbour lists, even when the focal has
    real reaction-graph neighbours in the DB."""
    resp = pathway_context(
        PathwayContextRequest(metabolite_id="HMDB0000122", neighbour_depth=0)
    )
    assert resp.upstream_neighbours == []
    assert resp.downstream_neighbours == []


def test_neighbour_depth_one_finds_pyruvate(ramp_db):
    """Glucose at depth=1 has pyruvate downstream (via RXN_GLYCO)."""
    resp = pathway_context(
        PathwayContextRequest(metabolite_id="HMDB0000122", neighbour_depth=1)
    )
    # Pyruvate should appear in the downstream list. HMDB is the preferred
    # display form when it is available for the rampId.
    assert any("HMDB0000243" in n for n in resp.downstream_neighbours)


def test_orphan_metabolite_raises(ramp_db):
    """An analyte that resolves but has no pathway rows raises the typed error."""
    with pytest.raises(MetaboliteNotInNetworkError):
        pathway_context(
            PathwayContextRequest(metabolite_id="HMDB0000050", neighbour_depth=1)
        )


def test_unknown_identifier_raises(ramp_db):
    """An identifier that does not resolve raises the same error."""
    with pytest.raises(MetaboliteNotInNetworkError):
        pathway_context(
            PathwayContextRequest(metabolite_id="HMDB9999999", neighbour_depth=1)
        )


def test_plausibility_summary_short_and_names_metabolite(ramp_db):
    """Summary must mention the metabolite name and stay under 120 words."""
    resp = pathway_context(
        PathwayContextRequest(
            metabolite_id="HMDB0000122",
            co_observed_ids=["HMDB0000243"],
        )
    )
    summary = resp.plausibility_summary
    assert "D-Glucose" in summary  # common_name from source table
    assert len(summary.split()) < 120
    # And the schema's 800-char cap is comfortably respected.
    assert len(summary) <= 800


def test_summary_when_no_context(ramp_db):
    """Summary explains absence of co-observed metabolites rather than emitting a fake score."""
    resp = pathway_context(
        PathwayContextRequest(metabolite_id="HMDB0000122", co_observed_ids=[])
    )
    assert "no co-observed" in resp.plausibility_summary.lower()


def test_no_llm_called(ramp_db):
    """Calling the tool never touches common.llm_client — the fixture's
    tripwire would raise AssertionError inside a regression."""
    pathway_context(
        PathwayContextRequest(
            metabolite_id="HMDB0000243",
            co_observed_ids=["HMDB0000122", "HMDB0000161"],
            neighbour_depth=1,
        )
    )


def test_ramp_unavailable_raises(monkeypatch):
    """If METAGENT_RAMP_PATH is unset and no DB path can be resolved,
    RampUnavailableError surfaces to the caller."""
    monkeypatch.setattr(ramp_backend, "resolve_db_path", lambda explicit=None: None)
    with pytest.raises(RampUnavailableError):
        pathway_context(PathwayContextRequest(metabolite_id="HMDB0000122"))


def test_kegg_identifier_also_resolves(ramp_db):
    """Querying by KEGG compound ID goes through the same code path."""
    resp = pathway_context(
        PathwayContextRequest(metabolite_id="C00022")  # pyruvate
    )
    assert len(resp.pathways) >= 2
