"""ChEBI sqlite lookup wrapper(W3 D3).

Thread-safe(per-call connection)— W10/W11 K=10 ThreadPoolExecutor 可并发 query。

Schema(see ``concord/etl/chebi_etl.py``):
    compound (chebi_id PK, primary_id UNIQUE, name, inchikey,
              inchikey_block14, smiles, monoisotopic_mass, charge, formula)
    compound_name (chebi_id, name, name_type)
    compound_xref (chebi_id, external_ns, external_id)
    compound_isa (child_chebi_id, parent_chebi_id, depth)

API:
    >>> chebi = ChebiLookup()
    >>> chebi.get_compound("17234")               # D-glucose
    CompoundRecord(chebi_id='17234', primary_id='CHEBI:17234', name='D-glucose', ...)
    >>> chebi.lookup_by_inchikey("WQZGKKKJIJFFOK-GASJEMHNSA-N")
    >>> chebi.lookup_by_inchikey("WQZGKKKJIJFFOK", use_block14=True)
    >>> chebi.lookup_by_xref("KEGG", "C00031")
    >>> chebi.lookup_by_name("D-glucose", fuzzy=False)
    >>> chebi.climb_to_canonical("17634", max_depth=2)
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_DB_PATH = Path("data/concord/chebi.sqlite")


@dataclass(frozen=True)
class CompoundRecord:
    chebi_id: str            # numeric str, no prefix
    primary_id: str          # "CHEBI:NNNNN"
    name: str
    inchikey: str | None
    inchikey_block14: str | None
    smiles: str | None
    monoisotopic_mass: float | None
    charge: int | None
    formula: str | None


_CHEBI_NUM_RE = re.compile(r"^(?:CHEBI:)?(\d+)$", re.IGNORECASE)


def normalize_chebi_id(value: str) -> str:
    """Accept "17234" or "CHEBI:17234" or "chebi:17234" → return "17234"."""
    if not isinstance(value, str):
        raise TypeError(f"chebi_id must be str, got {type(value).__name__}")
    m = _CHEBI_NUM_RE.match(value.strip())
    if not m:
        raise ValueError(f"Not a valid ChEBI ID: {value!r}")
    return m.group(1)


class ChebiLookup:
    """Thread-safe ChEBI sqlite lookup.

    Each method opens a fresh read-only sqlite connection — sqlite is fine
    with concurrent readers via uri=true&mode=ro.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path).resolve()
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"ChEBI sqlite not found at {self.db_path}. "
                f"Run `python -m concord.etl.chebi_etl` first."
            )

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def _row_to_record(row: sqlite3.Row | None) -> CompoundRecord | None:
        if row is None:
            return None
        return CompoundRecord(
            chebi_id=row["chebi_id"],
            primary_id=row["primary_id"],
            name=row["name"],
            inchikey=row["inchikey"],
            inchikey_block14=row["inchikey_block14"],
            smiles=row["smiles"],
            monoisotopic_mass=row["monoisotopic_mass"],
            charge=row["charge"],
            formula=row["formula"],
        )

    # ---- get_compound -------------------------------------------------

    def get_compound(self, chebi_id: str) -> CompoundRecord | None:
        cid = normalize_chebi_id(chebi_id)
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM compound WHERE chebi_id = ?", (cid,)
            ).fetchone()
        return self._row_to_record(row)

    # ---- lookup_by_inchikey -------------------------------------------

    def lookup_by_inchikey(
        self, inchikey: str, *, use_block14: bool = False,
    ) -> list[CompoundRecord]:
        if not inchikey:
            return []
        ik = inchikey.strip()
        if use_block14:
            key = ik.split("-")[0]
            col = "inchikey_block14"
        else:
            key = ik
            col = "inchikey"
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM compound WHERE {col} = ?", (key,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows if r]

    # ---- lookup_by_xref ----------------------------------------------

    def lookup_by_xref(self, ns: str, ext_id: str) -> CompoundRecord | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT c.* FROM compound c JOIN compound_xref x "
                "ON c.chebi_id = x.chebi_id "
                "WHERE x.external_ns = ? AND x.external_id = ? LIMIT 1",
                (ns.upper(), ext_id),
            ).fetchone()
        return self._row_to_record(row)

    # ---- lookup_by_name -----------------------------------------------

    def lookup_by_name(
        self, name: str, *, fuzzy: bool = False, limit: int = 50,
    ) -> list[CompoundRecord]:
        if not name:
            return []
        if fuzzy:
            # Match anywhere case-insensitively
            pattern = f"%{name.strip()}%"
            sql = (
                "SELECT DISTINCT c.* FROM compound c "
                "JOIN compound_name n ON c.chebi_id = n.chebi_id "
                "WHERE c.name LIKE ? COLLATE NOCASE "
                "   OR n.name LIKE ? COLLATE NOCASE "
                "LIMIT ?"
            )
            params: tuple = (pattern, pattern, limit)
        else:
            sql = (
                "SELECT DISTINCT c.* FROM compound c "
                "LEFT JOIN compound_name n ON c.chebi_id = n.chebi_id "
                "WHERE c.name = ? COLLATE NOCASE "
                "   OR n.name = ? COLLATE NOCASE "
                "LIMIT ?"
            )
            params = (name.strip(), name.strip(), limit)
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._row_to_record(r) for r in rows if r]

    # ---- climb_to_canonical -------------------------------------------

    def climb_to_canonical(
        self, chebi_id: str, *, max_depth: int = 2,
    ) -> list[str]:
        """Return list of ancestor ChEBI IDs along is_a chain,sorted by depth ASC.

        Q-04 use:对 α-D-glucose 走 climb_to_canonical → 应找到 D-glucose / glucose 等
        共同 ancestor。Used to reconcile stereo/charge variants.
        """
        cid = normalize_chebi_id(chebi_id)
        with self._conn() as c:
            rows = c.execute(
                "SELECT parent_chebi_id FROM compound_isa "
                "WHERE child_chebi_id = ? AND depth <= ? "
                "ORDER BY depth ASC",
                (cid, max_depth),
            ).fetchall()
        return [r[0] for r in rows]

    # ---- bulk helpers -------------------------------------------------

    def lookup_many_by_xref(
        self, pairs: Iterable[tuple[str, str]],
    ) -> dict[tuple[str, str], CompoundRecord | None]:
        """Batch convenience for normalizer code.

        Returns: {(ns, ext_id): CompoundRecord or None}
        """
        out: dict[tuple[str, str], CompoundRecord | None] = {}
        with self._conn() as c:
            for ns, ext_id in pairs:
                row = c.execute(
                    "SELECT c.* FROM compound c JOIN compound_xref x "
                    "ON c.chebi_id = x.chebi_id "
                    "WHERE x.external_ns = ? AND x.external_id = ? LIMIT 1",
                    (ns.upper(), ext_id),
                ).fetchone()
                out[(ns, ext_id)] = self._row_to_record(row)
        return out
