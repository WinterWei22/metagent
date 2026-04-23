"""HMDB local SQLite backend for fetch_metabolite_info.

The on-disk schema (created by build_hmdb_db.py) is a single `metabolites`
table:

    hmdb_id                   TEXT PRIMARY KEY  -- normalised to 7-digit form
    primary_name              TEXT
    molecular_formula         TEXT
    exact_mass                REAL
    smiles                    TEXT
    inchikey                  TEXT
    chemical_class            TEXT              -- class_label from HMDB taxonomy
    kegg_id                   TEXT
    chebi_id                  TEXT
    pubchem_cid               TEXT              -- kept as TEXT because HMDB sometimes carries it that way
    chembl_id                 TEXT
    synonyms_json             TEXT              -- JSON list[str]
    tissue_locations_json     TEXT              -- JSON list[str]
    disease_associations_json TEXT              -- JSON list[str]

Four indices cover the lookup paths this tool needs:
  - primary key on hmdb_id
  - idx_inchikey
  - idx_kegg_id
  - idx_name_lower (COLLATE NOCASE)

No writes happen here. Writes are the exclusive responsibility of
build_hmdb_db.py.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from tools.metabolite_info.id_detect import normalise_hmdb

logger = logging.getLogger(__name__)

HMDB_ENV_VAR = "METAGENT_HMDB_PATH"

_COLUMNS = (
    "hmdb_id, primary_name, molecular_formula, exact_mass, smiles, inchikey, "
    "chemical_class, kegg_id, chebi_id, pubchem_cid, chembl_id, "
    "synonyms_json, tissue_locations_json, disease_associations_json"
)


@dataclass
class HmdbRow:
    """Decoded row from the HMDB SQLite table. JSON columns are already parsed.

    A None field here means the underlying HMDB record had no value — it is
    NEVER backfilled with a guess.
    """

    hmdb_id: str
    primary_name: str | None
    molecular_formula: str | None
    exact_mass: float | None
    smiles: str | None
    inchikey: str | None
    chemical_class: str | None
    kegg_id: str | None
    chebi_id: str | None
    pubchem_cid: str | None
    chembl_id: str | None
    synonyms: list[str]
    tissue_locations: list[str]
    disease_associations: list[str]


def resolve_db_path(explicit: str | os.PathLike | None = None) -> Path | None:
    """Return the DB path from (1) the explicit arg, (2) METAGENT_HMDB_PATH.

    Returns None when neither is set — caller decides whether to fall back
    to PubChem or report `found=False`. We do NOT raise here; a missing DB
    is an expected deployment state, not a programming error.
    """
    if explicit is not None:
        p = Path(explicit)
        return p if p.exists() else None
    env = os.environ.get(HMDB_ENV_VAR)
    if not env:
        return None
    p = Path(env)
    return p if p.exists() else None


def open_connection(path: str | os.PathLike) -> sqlite3.Connection:
    """Open the HMDB DB read-only. `path` must already exist.

    Uses URI mode to enforce read-only; a corrupted/non-SQLite file will
    raise sqlite3.DatabaseError on first query rather than silently
    returning zero rows.
    """
    p = Path(path).resolve()
    uri = f"file:{p}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Row decoding
# ---------------------------------------------------------------------------


def _decode_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("HMDB row carried non-JSON list column: %r", raw[:80])
        return []
    if not isinstance(value, list):
        return []
    return [str(x) for x in value if x is not None]


def _row_to_hmdb(row: sqlite3.Row | None) -> HmdbRow | None:
    if row is None:
        return None
    return HmdbRow(
        hmdb_id=row["hmdb_id"],
        primary_name=row["primary_name"],
        molecular_formula=row["molecular_formula"],
        exact_mass=row["exact_mass"],
        smiles=row["smiles"],
        inchikey=row["inchikey"],
        chemical_class=row["chemical_class"],
        kegg_id=row["kegg_id"],
        chebi_id=row["chebi_id"],
        pubchem_cid=row["pubchem_cid"],
        chembl_id=row["chembl_id"],
        synonyms=_decode_json_list(row["synonyms_json"]),
        tissue_locations=_decode_json_list(row["tissue_locations_json"]),
        disease_associations=_decode_json_list(row["disease_associations_json"]),
    )


# ---------------------------------------------------------------------------
# Lookup paths
# ---------------------------------------------------------------------------


def lookup_by_hmdb(conn: sqlite3.Connection, hmdb_id: str) -> HmdbRow | None:
    """Primary-key lookup. `hmdb_id` is normalised to 7-digit form first."""
    normed = normalise_hmdb(hmdb_id.strip())
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM metabolites WHERE hmdb_id = ? LIMIT 1",
        (normed,),
    )
    return _row_to_hmdb(cur.fetchone())


def lookup_by_kegg(conn: sqlite3.Connection, kegg_id: str) -> HmdbRow | None:
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM metabolites WHERE kegg_id = ? LIMIT 1",
        (kegg_id.strip(),),
    )
    return _row_to_hmdb(cur.fetchone())


def lookup_by_inchikey(conn: sqlite3.Connection, inchikey: str) -> HmdbRow | None:
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM metabolites WHERE inchikey = ? LIMIT 1",
        (inchikey.strip(),),
    )
    return _row_to_hmdb(cur.fetchone())


def lookup_by_name(conn: sqlite3.Connection, name: str) -> HmdbRow | None:
    """Case-insensitive exact match on primary_name.

    We intentionally do NOT do fuzzy matching or synonym expansion here:
    invented aliases are a hallucination vector. If the user supplies
    "glucose" and HMDB lists "D-Glucose", we rely on the synonyms_json
    column being populated with "glucose" in it, and join via a secondary
    query below.
    """
    name_clean = name.strip()
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM metabolites WHERE primary_name = ? COLLATE NOCASE LIMIT 1",
        (name_clean,),
    )
    row = _row_to_hmdb(cur.fetchone())
    if row is not None:
        return row
    # Fall back to a synonym search — slow linear scan, acceptable at the
    # size of HMDB human subset (~220k rows) for a one-shot lookup.
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM metabolites WHERE synonyms_json LIKE ? LIMIT 200",
        (f"%{name_clean}%",),
    )
    needle = name_clean.lower()
    for raw in cur.fetchall():
        syns = _decode_json_list(raw["synonyms_json"])
        if any(s.lower() == needle for s in syns):
            return _row_to_hmdb(raw)
    return None


def lookup_by_smiles(conn: sqlite3.Connection, smiles: str) -> HmdbRow | None:
    """Exact-string SMILES lookup.

    HMDB stores one canonical SMILES per compound, but the user-supplied
    SMILES may be a stereoisomer variant or a different canonicalisation.
    We try an exact match first; if the caller has RDKit available they can
    canonicalise upstream. We do NOT silently accept partial matches.
    """
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM metabolites WHERE smiles = ? LIMIT 1",
        (smiles.strip(),),
    )
    return _row_to_hmdb(cur.fetchone())
