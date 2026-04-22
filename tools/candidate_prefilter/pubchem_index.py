"""SQLite-backed mass index for the pubchem_lite candidate pool.

v0 data source: HMDB-only. Future v0.1+ will append DrugBank, ChEBI, and a
PubChem subset into the same table; the schema is designed for that growth.
See README_PUBCHEM_SETUP.md for build instructions.

Schema (identical to what build_pubchem_lite.py writes):

    CREATE TABLE pubchem_lite (
        compound_id       TEXT PRIMARY KEY,   -- native id: HMDB0000122, CID:5793, etc.
        source            TEXT NOT NULL,      -- "hmdb" | "drugbank" | "chebi" | "pubchem"
        name              TEXT,
        smiles            TEXT NOT NULL,
        canonical_smiles  TEXT,
        inchikey          TEXT,
        molecular_formula TEXT NOT NULL,
        exact_mass        REAL NOT NULL,
        pubchem_cid       INTEGER,            -- if known, else NULL
        hmdb_id           TEXT                -- if known, else NULL
    );
    CREATE INDEX idx_exact_mass ON pubchem_lite(exact_mass);
    CREATE INDEX idx_formula    ON pubchem_lite(molecular_formula);
    CREATE INDEX idx_inchikey   ON pubchem_lite(inchikey);

All candidates emitted by this index carry `source_pool="pubchem_lite"` in the
returned PrefilteredCandidate — the brand of the local DB is intentionally
stable even though the v0 content is HMDB-only.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from schemas.common import PrefilteredCandidate

from tools.candidate_prefilter.errors import PubChemLiteNotBuiltError

logger = logging.getLogger(__name__)


ENV_PATH_VAR = "METAGENT_PUBCHEM_LITE_PATH"


class PubChemLiteIndex:
    """Thin SQLite wrapper over the pubchem_lite table.

    Connection is opened lazily on first query and held open for the process
    lifetime. SQLite's shared-cache mode is not used; queries are read-only
    and sub-millisecond thanks to the exact_mass B-tree index.
    """

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if not self._db_path.exists():
            raise PubChemLiteNotBuiltError(
                f"PubChem Lite SQLite DB not found at {self._db_path}. "
                f"Run tools/candidate_prefilter/build_pubchem_lite.py first; "
                f"see README_PUBCHEM_SETUP.md."
            )
        # read-only URI — cheap safety against accidental writes
        uri = f"file:{self._db_path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def search(
        self,
        neutral_mass: float,
        tolerance_ppm: float,
        formula: str | None = None,
        *,
        limit: int | None = None,
        gnps_inchikeys: frozenset[str] | set[str] = frozenset(),
    ) -> list[PrefilteredCandidate]:
        """Return candidates whose exact_mass is within tolerance of
        `neutral_mass`. Optional formula is applied as a hard equality filter
        on the indexed `molecular_formula` column.

        `gnps_inchikeys` is used to stamp has_reference_spectrum=True on
        candidates whose InChIKey also appears in GNPS (cross-pool bridge).

        `limit` is an optional hard cap applied in SQL; pass the tool-level
        max_candidates so we don't pull millions of rows on a wide tolerance.
        """
        if neutral_mass <= 0:
            return []

        abs_tol = tolerance_ppm * 1e-6 * neutral_mass
        lo, hi = neutral_mass - abs_tol, neutral_mass + abs_tol

        sql_parts = [
            "SELECT compound_id, source, name, smiles, inchikey, "
            "molecular_formula, exact_mass, pubchem_cid, hmdb_id "
            "FROM pubchem_lite "
            "WHERE exact_mass BETWEEN ? AND ?"
        ]
        params: list = [lo, hi]
        if formula is not None:
            sql_parts.append("AND molecular_formula = ?")
            params.append(formula)
        sql_parts.append("ORDER BY ABS(exact_mass - ?) ASC")
        params.append(neutral_mass)
        if limit is not None:
            sql_parts.append("LIMIT ?")
            params.append(int(limit))
        sql = " ".join(sql_parts)

        conn = self._connect()
        cur = conn.execute(sql, params)

        out: list[PrefilteredCandidate] = []
        for row in cur.fetchall():
            compound_id, source, name, smiles, inchikey, mol_formula, exact_mass, cid, hmdb_id = row
            ppm_err = abs(exact_mass - neutral_mass) / neutral_mass * 1e6
            # Prefer the native stable id: for HMDB rows use hmdb_id, for
            # pubchem rows use "CID:<cid>". Falls back to compound_id which
            # is already populated with the native id by build script.
            source_id = hmdb_id or (f"CID:{cid}" if cid else compound_id)
            has_ref = bool(inchikey and inchikey in gnps_inchikeys)
            out.append(
                PrefilteredCandidate(
                    smiles=smiles,
                    name=name,
                    source_pool="pubchem_lite",
                    source_id=source_id,
                    molecular_formula=mol_formula,
                    exact_mass=float(exact_mass),
                    mass_error_ppm=ppm_err,
                    has_reference_spectrum=has_ref,
                )
            )
        return out


# ---------------------------------------------------------------------------
# Module-level default index (lazy, overridable for tests)
# ---------------------------------------------------------------------------


_DEFAULT_INDEX: PubChemLiteIndex | None = None


def get_default_index() -> PubChemLiteIndex:
    """Return the cached process-wide PubChem Lite index.

    Reads METAGENT_PUBCHEM_LITE_PATH on first call. Raises
    PubChemLiteNotBuiltError if the env var is unset. The file existence
    check itself runs lazily on first query (so this function is cheap and
    safe to call even in environments where the DB isn't installed).
    """
    global _DEFAULT_INDEX
    if _DEFAULT_INDEX is not None:
        return _DEFAULT_INDEX

    path = os.environ.get(ENV_PATH_VAR)
    if not path:
        raise PubChemLiteNotBuiltError(
            f"{ENV_PATH_VAR} is not set. Build the DB via "
            f"tools/candidate_prefilter/build_pubchem_lite.py and export "
            f"{ENV_PATH_VAR} to point at the resulting .sqlite file."
        )

    _DEFAULT_INDEX = PubChemLiteIndex(path)
    return _DEFAULT_INDEX


def set_default_index(index: PubChemLiteIndex | None) -> None:
    """Replace the cached default index.

    Use for test setUp/tearDown. Passing None resets back to lazy load.
    """
    global _DEFAULT_INDEX
    if _DEFAULT_INDEX is not None and _DEFAULT_INDEX is not index:
        _DEFAULT_INDEX.close()
    _DEFAULT_INDEX = index
