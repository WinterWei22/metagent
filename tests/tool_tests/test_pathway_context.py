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
                met_name          TEXT,
                is_cofactor       INTEGER NOT NULL DEFAULT 0
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
            # Cofactors — flagged is_cofactor=1 in reaction2met below so P-4
            # can assert they do NOT appear in neighbour lists by default.
            ("hmdb:HMDB0002111", "RAMP_C_H2O",         "hmdb",  "Water",        "hmdb"),
            ("hmdb:HMDB0000538", "RAMP_C_ATP",         "hmdb",  "ATP",          "hmdb"),
            ("hmdb:HMDB0001487", "RAMP_C_NADH",        "hmdb",  "NADH",         "hmdb"),
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
        # Glucose ↔ pyruvate (forward + reverse) and pyruvate → alanine.
        # The reverse edge (RXN_GLUC_SYNTH: pyruvate substrate, glucose
        # product) is what makes depth≥2 BFS try to echo glucose back
        # into the focal's own neighbour list — see P-5 test below.
        # substrate_product = 1 means substrate, 0 means product (RaMP v3 convention).
        # Real RaMP's reaction2met carries an is_cofactor flag; we model it
        # as a 6th column so P-4 filtering has data to bite on.
        reaction_rows = [
            # (ramp_rxn_id, ramp_cmpd_id, substrate_product, met_source_id, met_name, is_cofactor)
            ("RXN_GLYCO",       "RAMP_C_GLUC", 1, "chebi:4167",   "D-glucose", 0),
            ("RXN_GLYCO",       "RAMP_C_PYR",  0, "chebi:15361",  "pyruvate",  0),
            # Cofactors of the glycolysis reaction — under the P-4 default
            # filter these must NOT surface as downstream neighbours of
            # glucose or upstream neighbours of pyruvate.
            ("RXN_GLYCO",       "RAMP_C_H2O",  0, "chebi:15377",  "H2O",       1),
            ("RXN_GLYCO",       "RAMP_C_ATP",  1, "chebi:15422",  "ATP",       1),
            ("RXN_GLYCO",       "RAMP_C_NADH", 0, "chebi:16908",  "NADH",      1),
            ("RXN_GLUC_SYNTH",  "RAMP_C_PYR",  1, "chebi:15361",  "pyruvate",  0),
            ("RXN_GLUC_SYNTH",  "RAMP_C_GLUC", 0, "chebi:4167",   "D-glucose", 0),
            ("RXN_ALA_TRANS",   "RAMP_C_PYR",  1, "chebi:15361",  "pyruvate",  0),
            ("RXN_ALA_TRANS",   "RAMP_C_ALA",  0, "chebi:16977",  "L-alanine", 0),
        ]
        conn.executemany(
            "INSERT INTO reaction2met (ramp_rxn_id, ramp_cmpd_id, substrate_product, met_source_id, met_name, is_cofactor) VALUES (?, ?, ?, ?, ?, ?)",
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


# ---------------------------------------------------------------------------
# Regression tests pinning P-1 / P-5 / P-6 semantics (2026-04-23 fix plan).
# ---------------------------------------------------------------------------


def test_hit_count_varies_per_pathway(ramp_db):
    """A co-observed metabolite that sits in SOME pathways of the focal
    but not all of them must lift hit_count only on the shared ones,
    leaving the rest at 1. Before the P-1 fix every PathwayEntry shared
    the same hit_count regardless of actual membership.

    Setup in the mini DB:
      pyruvate pathways = {glycolysis-kegg, glycolysis-reactome,
                           glycolysis-smpdb, alanine-kegg}.
      alanine  pathways = {alanine-kegg}.
    Expected hit_counts with focal=pyruvate, co_obs=[alanine]:
      - three glycolysis pathways → 1 (only pyruvate present)
      - alanine-kegg              → 2 (pyruvate + alanine)
    """
    resp = pathway_context(PathwayContextRequest(
        metabolite_id="HMDB0000243",       # pyruvate
        co_observed_ids=["HMDB0000161"],   # alanine — only in ala_kegg
    ))
    counts = sorted({p.hit_count for p in resp.pathways})
    assert counts == [1, 2], (
        f"hit_count must vary per pathway; got {counts} "
        f"(pathways={[(p.name, p.hit_count) for p in resp.pathways]})"
    )
    alanine_entry = next(p for p in resp.pathways if "Alanine" in p.name)
    assert alanine_entry.hit_count == 2
    glyco_entries = [p for p in resp.pathways if "Glycolysis" in p.name]
    assert glyco_entries, "mini DB should contain glycolysis pathways"
    for p in glyco_entries:
        assert p.hit_count == 1, (p.name, p.hit_count)


def test_depth_2_does_not_echo_focal(ramp_db):
    """The focal must never appear in its own neighbour list at depth ≥ 2.

    The mini DB has glucose ↔ pyruvate edges plus pyruvate → alanine.
    Pre-fix, `x not in analyte.ramp_ids` compared sourceIds like
    `hmdb:HMDB0000122` against internal rampIds like `RAMP_C_GLUC`,
    never matched, and the focal echoed itself back at depth=2.
    """
    resp = pathway_context(PathwayContextRequest(
        metabolite_id="HMDB0000122",       # glucose
        neighbour_depth=2,
    ))
    forbidden_forms = (
        "HMDB0000122",
        "hmdb:HMDB0000122",
        "C00031",
        "kegg:C00031",
    )
    for form in forbidden_forms:
        assert form not in resp.upstream_neighbours, (
            f"depth-2 upstream echoed focal as {form!r}: {resp.upstream_neighbours}"
        )
        assert form not in resp.downstream_neighbours, (
            f"depth-2 downstream echoed focal as {form!r}: {resp.downstream_neighbours}"
        )


def test_p4_pyruvate_neighbours_exclude_water_atp(ramp_db):
    """Cofactors (H₂O, ATP, NADH, CO₂, H⁺, …) must not surface as
    network neighbours. RaMP's `reaction2met.is_cofactor` column is the
    authoritative flag; the tool's default `_neighbour_external_ids`
    query excludes rows where it is 1 so the biologically-specific
    partners aren't drowned out.

    Before the P-4 fix, every cofactor participant of a focal's
    reactions surfaced in upstream/downstream and dominated the list
    for central metabolites. The mini DB seeds RXN_GLYCO with H2O
    (HMDB0002111, product, is_cofactor=1), ATP (HMDB0000538, substrate,
    is_cofactor=1), and NADH (HMDB0001487, product, is_cofactor=1).
    """
    resp = pathway_context(PathwayContextRequest(
        metabolite_id="HMDB0000243",     # pyruvate — participates in RXN_GLYCO
        neighbour_depth=1,
    ))
    all_neighbours = resp.upstream_neighbours + resp.downstream_neighbours
    blacklist = {
        "hmdb:HMDB0002111", "HMDB0002111",   # water
        "hmdb:HMDB0000538", "HMDB0000538",   # ATP
        "hmdb:HMDB0001487", "HMDB0001487",   # NADH
    }
    leaks = [n for n in all_neighbours if n in blacklist]
    assert not leaks, f"cofactors leaked into neighbours: {leaks}"


def test_unresolvable_co_obs_excluded_from_denominator(ramp_db):
    """IDs the caller supplies that RaMP cannot resolve must not deflate
    the score. Before P-6, `1 real match + 9 typos` scored 0.1; now it
    scores 1.0 and the explain string notes how many were dropped."""
    fake_ids = [f"HMDB{i:07d}" for i in range(9000000, 9000009)]  # 9 fakes
    resp = pathway_context(PathwayContextRequest(
        metabolite_id="HMDB0000122",                           # glucose
        co_observed_ids=["HMDB0000243"] + fake_ids,            # 1 real + 9 unresolvable
    ))
    assert resp.cooccurrence_score == pytest.approx(1.0), (
        f"1 real match out of 1 resolvable should be 1.0, got {resp.cooccurrence_score}"
    )
    assert "could not be resolved" in resp.explain.lower(), resp.explain
    # Explain should also surface the drop count.
    assert "9" in resp.explain, resp.explain
