"""Shared fixtures for Sub-6 benchmark tests.

Builds a tiny in-memory RaMP / HMDB sqlite snapshot at session scope.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Tiny RaMP sqlite
#
# We seed a deliberately small graph that exercises:
#   - 2 strong pathways (anthocyanin + flavonoid) with ~6 compounds each
#   - 1 distractor pathway (random, 3 compounds)
#   - Pathway types: kegg, reactome, wiki, hmdb (+ pfocr to verify exclusion)
#   - Source-table entries for kegg / hmdb / inchikey lookups
# ---------------------------------------------------------------------------


def _make_ramp_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE pathway (
            pathwayRampId VARCHAR(30) PRIMARY KEY,
            sourceId VARCHAR(30),
            type VARCHAR(30),
            pathwayCategory VARCHAR(30),
            pathwayName VARCHAR(250)
        );
        CREATE TABLE analytehaspathway (
            rampId VARCHAR(30),
            pathwayRampId VARCHAR(30),
            pathwaySource VARCHAR(30)
        );
        CREATE INDEX ahp_RampID_IDX ON analytehaspathway (rampId);
        CREATE INDEX ahp_path_RampID_IDX ON analytehaspathway (pathwayRampId);
        CREATE TABLE source (
            sourceId VARCHAR(30) NOT NULL,
            rampId VARCHAR(30),
            IDtype VARCHAR(30),
            geneOrCompound VARCHAR(30),
            commonName VARCHAR(256),
            priorityHMDBStatus VARCHAR(32),
            dataSource VARCHAR(32),
            pathwayCount INTEGER DEFAULT 0 NOT NULL
        );
        CREATE INDEX idx_source_IDtype ON source (IDtype);
        CREATE INDEX source_sid_RampID_IDX ON source (sourceId);
        CREATE TABLE chem_props (
            ramp_id VARCHAR(30) NOT NULL,
            chem_data_source VARCHAR(32),
            chem_source_id VARCHAR(45),
            iso_smiles VARCHAR(256),
            inchi_key_prefix VARCHAR(32),
            inchi_key VARCHAR(32),
            inchi VARCHAR(4096),
            mw FLOAT,
            monoisotop_mass FLOAT,
            common_name VARCHAR(1024),
            mol_formula VARCHAR(64)
        );
        CREATE INDEX inchi_key_idx ON chem_props (inchi_key);
        CREATE INDEX inchi_key_prefix_idx ON chem_props (inchi_key_prefix);
    """)


# Compounds. Each tuple: (ramp_id, name, kegg_id, hmdb_id, inchikey_full)
_COMPOUNDS: list[tuple[str, str, str | None, str | None, str]] = [
    # Anthocyanin pathway members (6)
    ("RAMP_C_A001", "Cyanidin",            "C05905", "HMDB0030702", "VEVZSMAXJVBISB-UHFFFAOYSA-N"),
    ("RAMP_C_A002", "Cyanidin-3-glucoside","C08604", "HMDB0030700", "TUJKJAMUKRIRHC-UHFFFAOYSA-N"),
    ("RAMP_C_A003", "Pelargonidin",        "C05904", "HMDB0030701", "TZWPRBYOKZWFLY-UHFFFAOYSA-N"),
    ("RAMP_C_A004", "Delphinidin",         "C05908", "HMDB0029205", "JKHRCGUTYDNCLE-UHFFFAOYSA-N"),
    ("RAMP_C_A005", "Malvidin",            "C09631", "HMDB0030704", "GZSOSUNBTXMUFQ-UHFFFAOYSA-N"),
    ("RAMP_C_A006", "Peonidin",            "C09096", "HMDB0029253", "PFTAWBLQPZVEMU-UHFFFAOYSA-N"),
    # Flavonoid pathway members (6) — partly overlap with anthocyanin? no, distinct
    ("RAMP_C_F001", "Naringenin",          "C00509", "HMDB0002670", "FTVWIRXFELQLPI-UHFFFAOYSA-N"),
    ("RAMP_C_F002", "Apigenin",            "C01477", "HMDB0002124", "KZNIFHPLKGYRTM-UHFFFAOYSA-N"),
    ("RAMP_C_F003", "Quercetin",           "C00389", "HMDB0005794", "REFJWTPEDVJJIY-UHFFFAOYSA-N"),
    ("RAMP_C_F004", "Kaempferol",          "C05903", "HMDB0005801", "IYRMWMYZSQPJKC-UHFFFAOYSA-N"),
    ("RAMP_C_F005", "Luteolin",            "C01514", "HMDB0005800", "IQPNAANSBPBGFQ-UHFFFAOYSA-N"),
    ("RAMP_C_F006", "Eriodictyol",         "C05631", "HMDB0005808", "WTEVQBCEXWBHNA-VEYBVKAESA-N"),
    # Distractor pathway: 3 unrelated organic acids
    ("RAMP_C_D001", "Citric acid",         "C00158", "HMDB0000094", "KRKNYBCHXYNGOX-UHFFFAOYSA-N"),
    ("RAMP_C_D002", "Succinic acid",       "C00042", "HMDB0000254", "KDYFGRWQOYBRFD-UHFFFAOYSA-N"),
    ("RAMP_C_D003", "Lactic acid",         "C00186", "HMDB0000190", "JVTAAEKCZFNVCJ-UHFFFAOYSA-N"),
    # Pool filler: 30 compounds in only the noise/background pool to grow N
    # We give them their own pathway (BG) so background_size is reasonable.
]
# Pool-filler compounds (no pathway hit but expand background)
for i in range(1, 31):
    _COMPOUNDS.append((
        f"RAMP_C_BG{i:03d}",
        f"Background-{i}",
        f"C99{i:03d}",
        f"HMDB99{i:03d}",
        f"BG{i:03d}AAAAAAAAAA-AAAAAAAAAA-N"[:27],  # 27-char synthetic InChIKey
    ))


# Pathways. (ramp_id, source_id, type, name)
_PATHWAYS = [
    ("PATH_ANTHO",  "smp_00029",  "hmdb",     "Anthocyanin biosynthesis"),
    ("PATH_FLAV",   "C00010",     "kegg",     "Flavonoid biosynthesis"),
    ("PATH_DISTR",  "R-HSA-71291", "reactome", "Citric acid cycle (TCA cycle)"),
    # Three pfocr pathways:
    #   PATH_PFOCR  — 4 anthocyanin compounds + 6 BG fillers (K=10)
    #   PATH_PFOCR2 — same 4 anthocyanin compounds + 1 BG filler (K=5)
    #     (different K, identical matched-compound fingerprint when 4 antho
    #      compounds are queried → aggregation should keep PFOCR2 only.)
    #   PATH_PFOCR3 — 5 anthocyanin compounds (K=5)
    #     (different fingerprint; should not aggregate with PFOCR/PFOCR2.)
    ("PATH_PFOCR",  "PFOCR_X",    "pfocr",    "Anthocyanin diagram (figure 1)"),
    ("PATH_PFOCR2", "PFOCR_Y",    "pfocr",    "Anthocyanin diagram (figure 2)"),
    ("PATH_PFOCR3", "PFOCR_Z",    "pfocr",    "Anthocyanin schematic (alt)"),
    ("PATH_BG",     "BG_BG",      "wiki",     "Background pathway (filler)"),
]

# pathway membership: which compounds belong to which pathway.
_MEMBERSHIP = (
    [(f"RAMP_C_A00{i}", "PATH_ANTHO") for i in range(1, 7)]
    + [(f"RAMP_C_F00{i}", "PATH_FLAV") for i in range(1, 7)]
    + [(f"RAMP_C_D00{i}", "PATH_DISTR") for i in range(1, 4)]
    # PFOCR (K=10): 4 anthocyanin compounds + 6 BG fillers
    + [(f"RAMP_C_A00{i}", "PATH_PFOCR") for i in range(1, 5)]
    + [(f"RAMP_C_BG{i:03d}", "PATH_PFOCR") for i in range(1, 7)]
    # PFOCR2 (K=5): same 4 anthocyanin compounds + 1 BG filler
    + [(f"RAMP_C_A00{i}", "PATH_PFOCR2") for i in range(1, 5)]
    + [("RAMP_C_BG001", "PATH_PFOCR2")]
    # PFOCR3 (K=5): 5 anthocyanin compounds — distinct matched fingerprint
    + [(f"RAMP_C_A00{i}", "PATH_PFOCR3") for i in range(1, 6)]
    # Background pathway holds all BG fillers (so they're in background_size)
    + [(f"RAMP_C_BG{i:03d}", "PATH_BG") for i in range(1, 31)]
)


def _seed_ramp(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO pathway (pathwayRampId, sourceId, type, pathwayName) "
        "VALUES (?, ?, ?, ?)", _PATHWAYS)
    conn.executemany(
        "INSERT INTO analytehaspathway (rampId, pathwayRampId, pathwaySource) "
        "VALUES (?, ?, ?)",
        [(rid, pid, "test") for rid, pid in _MEMBERSHIP])
    # source rows: kegg + hmdb prefixed
    src_rows = []
    for rid, name, kegg, hmdb, ikey in _COMPOUNDS:
        if kegg:
            src_rows.append((f"kegg:{kegg}", rid, "kegg", "compound", name))
        if hmdb:
            src_rows.append((f"hmdb:{hmdb}", rid, "hmdb", "compound", name))
    conn.executemany(
        "INSERT INTO source (sourceId, rampId, IDtype, geneOrCompound, commonName) "
        "VALUES (?, ?, ?, ?, ?)", src_rows)
    # chem_props rows: full inchikey + first-block prefix
    cp_rows = []
    for rid, name, kegg, hmdb, ikey in _COMPOUNDS:
        cp_rows.append((rid, "hmdb", hmdb or "", ikey[:14], ikey, name))
    conn.executemany(
        "INSERT INTO chem_props "
        "(ramp_id, chem_data_source, chem_source_id, inchi_key_prefix, inchi_key, common_name) "
        "VALUES (?, ?, ?, ?, ?, ?)", cp_rows)


@pytest.fixture(scope="session")
def tiny_ramp_path(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("ramp") / "tiny_ramp.sqlite"
    conn = sqlite3.connect(p)
    try:
        _make_ramp_schema(conn)
        _seed_ramp(conn)
        conn.commit()
    finally:
        conn.close()
    return p


@pytest.fixture(autouse=True)
def _reset_agg_cache():
    """Clear the module-level aggregate cache between tests."""
    from tools.benchmark.sub6.ramp_enrichment import clear_aggregate_cache
    clear_aggregate_cache()
    yield
    clear_aggregate_cache()


# Expose compound metadata to tests
@pytest.fixture(scope="session")
def tiny_ramp_compounds() -> dict[str, dict]:
    """Return a dict keyed by ramp_id with name/kegg/hmdb/inchikey for each compound."""
    return {
        rid: {"name": name, "kegg": kegg, "hmdb": hmdb, "inchikey": ikey}
        for rid, name, kegg, hmdb, ikey in _COMPOUNDS
    }


@pytest.fixture(scope="session")
def anthocyanin_inchikeys(tiny_ramp_compounds) -> list[str]:
    """The 6 anthocyanin pathway InChIKeys (full keys)."""
    return [tiny_ramp_compounds[f"RAMP_C_A00{i}"]["inchikey"] for i in range(1, 7)]


@pytest.fixture(scope="session")
def random_inchikeys(tiny_ramp_compounds) -> list[str]:
    """5 background InChIKeys with no pathway overlap with anthocyanin/flavonoid."""
    return [tiny_ramp_compounds[f"RAMP_C_BG{i:03d}"]["inchikey"] for i in range(1, 6)]
