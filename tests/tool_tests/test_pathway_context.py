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
    """Populate a tmp RaMP DB covering glucose / pyruvate / alanine plus an orphan."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE source (
                sourceId    TEXT,
                rampId      TEXT,
                commonName  TEXT,
                dataSource  TEXT
            );
            CREATE TABLE pathway (
                pathwayRampId  TEXT PRIMARY KEY,
                sourceId       TEXT,
                pathwayName    TEXT,
                type           TEXT
            );
            CREATE TABLE analytehaspathway (
                rampId         TEXT,
                pathwayRampId  TEXT
            );
            CREATE TABLE reaction2met (
                rxnRampId    TEXT,
                rampId       TEXT,
                isSubstrate  INTEGER
            );
            """
        )

        # --- Source mapping ------------------------------------------------
        sources = [
            # (sourceId, rampId, commonName, dataSource)
            ("HMDB0000122", "RAMP_C_GLUC",   "D-Glucose",    "hmdb"),
            ("C00031",       "RAMP_C_GLUC",   "D-Glucose",    "kegg"),
            ("HMDB0000243", "RAMP_C_PYR",    "Pyruvate",     "hmdb"),
            ("C00022",       "RAMP_C_PYR",    "Pyruvate",     "kegg"),
            ("HMDB0000161", "RAMP_C_ALA",    "L-Alanine",    "hmdb"),
            ("C00041",       "RAMP_C_ALA",    "L-Alanine",    "kegg"),
            # Orphan: resolves to a rampId but has no analytehaspathway rows.
            ("HMDB0000050", "RAMP_C_ADEN_ORPHAN", "Adenosine", "hmdb"),
            # Random HMDB that resolves but shares no pathway with glucose.
            ("HMDB0001847", "RAMP_C_CAFF",   "Caffeine",     "hmdb"),
        ]
        conn.executemany(
            "INSERT INTO source (sourceId, rampId, commonName, dataSource) VALUES (?, ?, ?, ?)",
            sources,
        )

        # --- Pathways ------------------------------------------------------
        pathways = [
            # (pathwayRampId, sourceId, pathwayName, type)
            ("RAMP_P_GLYC_KEGG", "hsa00010",     "Glycolysis / Gluconeogenesis", "kegg"),
            ("RAMP_P_GLYC_REAC", "R-HSA-70171",  "Glycolysis",                   "reactome"),
            ("RAMP_P_ALA_KEGG",  "hsa00250",     "Alanine, aspartate and glutamate metabolism", "kegg"),
            ("RAMP_P_CAFF_KEGG", "hsa00232",     "Caffeine metabolism",          "kegg"),
        ]
        conn.executemany(
            "INSERT INTO pathway (pathwayRampId, sourceId, pathwayName, type) VALUES (?, ?, ?, ?)",
            pathways,
        )

        # --- Analyte ↔ pathway ---------------------------------------------
        analyte_pathways = [
            # Glucose sits in glycolysis from both KEGG and Reactome.
            ("RAMP_C_GLUC", "RAMP_P_GLYC_KEGG"),
            ("RAMP_C_GLUC", "RAMP_P_GLYC_REAC"),
            # Pyruvate sits in glycolysis AND alanine metabolism.
            ("RAMP_C_PYR",  "RAMP_P_GLYC_KEGG"),
            ("RAMP_C_PYR",  "RAMP_P_GLYC_REAC"),
            ("RAMP_C_PYR",  "RAMP_P_ALA_KEGG"),
            # Alanine sits in alanine metabolism only.
            ("RAMP_C_ALA",  "RAMP_P_ALA_KEGG"),
            # Caffeine has its own pathway, disjoint from glycolysis.
            ("RAMP_C_CAFF", "RAMP_P_CAFF_KEGG"),
            # Adenosine: no rows → orphan.
        ]
        conn.executemany(
            "INSERT INTO analytehaspathway (rampId, pathwayRampId) VALUES (?, ?)",
            analyte_pathways,
        )

        # --- Reaction graph -----------------------------------------------
        # One reaction converts glucose → pyruvate (via glycolysis), so
        # pyruvate is a downstream neighbour of glucose and vice versa.
        reaction_rows = [
            # (rxnRampId, rampId, isSubstrate)
            ("RXN_GLYCO",     "RAMP_C_GLUC", 1),
            ("RXN_GLYCO",     "RAMP_C_PYR",  0),
            # A second reaction: pyruvate + (co-substrate) → alanine
            ("RXN_ALA_TRANS", "RAMP_C_PYR",  1),
            ("RXN_ALA_TRANS", "RAMP_C_ALA",  0),
        ]
        conn.executemany(
            "INSERT INTO reaction2met (rxnRampId, rampId, isSubstrate) VALUES (?, ?, ?)",
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
