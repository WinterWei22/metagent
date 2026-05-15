"""ChEBI rel251 → sqlite ETL(W3 D1-D2).

Input  (under ``data/investigation/chebi_cache/`` — Session 2 download):
    compounds.tsv.gz          (6.6 MB)   主表
    names.tsv.gz              (8.7 MB)   synonyms / IUPAC
    chemical_data.tsv.gz      (4.9 MB)   formula / mass / charge
    structures.tsv.gz         (85 MB)    molfile / SMILES / InChI / InChIKey  ← D1 download
    database_accession.tsv.gz (3.7 MB)   跨库 xref
    source.tsv.gz             (3.7 KB)   source_id → DB name 字典
    relation.tsv.gz           (2.5 MB)   is_a / has_part(W3 D2)

structures.tsv.gz schema (wide table):
    id  compound_id  status_id  molfile  smiles  standard_inchi  standard_inchi_key
    dimension  default_structure
    NOTE: molfile field contains embedded newlines (quoted multiline) — must
    parse via csv.reader, not naive str.split('\t').

Output: ``data/concord/chebi.sqlite``

Schema(per W3 prompt §D1):
    compound (chebi_id PK, primary_id UNIQUE, name, inchikey, inchikey_block14,
              smiles, monoisotopic_mass, charge, formula)
    compound_name (chebi_id FK, name, name_type)
    compound_xref (chebi_id FK, external_ns, external_id)
    compound_isa (child_chebi_id FK, parent_chebi_id FK, depth)  -- W3 D2 填

Usage:
    python -m concord.etl.chebi_etl
    python -m concord.etl.chebi_etl --skip-structures   # 若 structures.tsv.gz 未下完

Source ID legend(source.tsv.gz,Session 2 已验证):
    35 = HMDB         45 = KEGG COMPOUND   46 = KEGG DRUG    47 = KEGG GLYCAN
    50 = LIPID MAPS   54 = MetaCyc         68 = PubChem CID  72 = Reactome   79 = SwissLipids

ChEBI status_id legend(per ChEBI docs):
    1 = CHECKED       2 = SUBMITTED        3 = RELEASED      9 = OK
"""
from __future__ import annotations

import argparse
import csv
import gzip
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("chebi_etl")
logging.basicConfig(
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)

WORKTREE = Path(__file__).resolve().parents[2]
CACHE_DIR = WORKTREE / "data" / "investigation" / "chebi_cache"
DB_PATH = WORKTREE / "data" / "concord" / "chebi.sqlite"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Filter to ConcordMet primary cross-source namespaces (Sprint 1 scope)
XREF_SOURCE_MAP = {
    "35": "HMDB",
    "45": "KEGG",
    "46": "KEGG_DRUG",
    "47": "KEGG_GLYCAN",
    "50": "LIPIDMAPS",
    "54": "METACYC",
    "68": "PUBCHEM",
    "72": "REACTOME",
    "79": "SWISSLIPIDS",
}
KEEP_SOURCE_IDS = set(XREF_SOURCE_MAP.keys())

BATCH_SIZE = 5000


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
DROP TABLE IF EXISTS compound;
DROP TABLE IF EXISTS compound_name;
DROP TABLE IF EXISTS compound_xref;
DROP TABLE IF EXISTS compound_isa;

CREATE TABLE compound (
    chebi_id          TEXT PRIMARY KEY,    -- numeric str, no prefix ("17234")
    primary_id        TEXT NOT NULL UNIQUE, -- "CHEBI:17234"
    name              TEXT NOT NULL,
    inchikey          TEXT,
    inchikey_block14  TEXT,
    smiles            TEXT,
    monoisotopic_mass REAL,
    charge            INTEGER,
    formula           TEXT
);
CREATE INDEX idx_compound_inchikey ON compound(inchikey);
CREATE INDEX idx_compound_inchikey_block14 ON compound(inchikey_block14);

CREATE TABLE compound_name (
    chebi_id  TEXT NOT NULL,
    name      TEXT NOT NULL,
    name_type TEXT NOT NULL,  -- "IUPAC" / "SYNONYM" / "BRAND" / "INN" / etc.
    FOREIGN KEY (chebi_id) REFERENCES compound(chebi_id)
);
CREATE INDEX idx_compound_name_name ON compound_name(name COLLATE NOCASE);
CREATE INDEX idx_compound_name_chebi ON compound_name(chebi_id);

CREATE TABLE compound_xref (
    chebi_id    TEXT NOT NULL,
    external_ns TEXT NOT NULL,
    external_id TEXT NOT NULL,
    FOREIGN KEY (chebi_id) REFERENCES compound(chebi_id)
);
CREATE INDEX idx_compound_xref_external ON compound_xref(external_ns, external_id);
CREATE UNIQUE INDEX uq_compound_xref ON compound_xref(chebi_id, external_ns, external_id);

CREATE TABLE compound_isa (
    -- W3 D2 fill-in (this script's --is-a flag)
    child_chebi_id  TEXT NOT NULL,
    parent_chebi_id TEXT NOT NULL,
    depth           INTEGER NOT NULL,    -- 1=direct parent, 2=grandparent, max 5
    FOREIGN KEY (child_chebi_id) REFERENCES compound(chebi_id),
    FOREIGN KEY (parent_chebi_id) REFERENCES compound(chebi_id)
);
CREATE INDEX idx_isa_child ON compound_isa(child_chebi_id);
CREATE INDEX idx_isa_parent ON compound_isa(parent_chebi_id);
CREATE UNIQUE INDEX uq_isa ON compound_isa(child_chebi_id, parent_chebi_id, depth);
"""


# ---------------------------------------------------------------------------
# TSV row iteration helpers
# ---------------------------------------------------------------------------


def _open_tsv(path: Path):
    """Open gz-compressed TSV (header row,tab-delimited)."""
    return gzip.open(path, "rt", encoding="utf-8")


def _iter_rows(path: Path):
    """Iter (header_dict, value_list) — yields dict per row."""
    if not path.exists():
        raise FileNotFoundError(path)
    with _open_tsv(path) as f:
        header = f.readline().rstrip("\n").split("\t")
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) != len(header):
                # Skip malformed
                continue
            yield dict(zip(header, cols))


# ---------------------------------------------------------------------------
# ETL Step 1 — compound (compounds.tsv + chemical_data.tsv merge)
# ---------------------------------------------------------------------------


def etl_compounds(conn: sqlite3.Connection) -> None:
    """Insert ChEBI compounds + merge chemical_data(formula/mass/charge)."""
    t0 = time.time()
    chem_data: dict[str, dict] = {}
    for row in _iter_rows(CACHE_DIR / "chemical_data.tsv.gz"):
        cid = row["compound_id"]
        # Prefer non-autogenerated entries when multiple per compound
        if cid in chem_data and chem_data[cid].get("is_autogenerated") == "false":
            continue
        chem_data[cid] = {
            "formula": row.get("formula") or None,
            "charge": int(row["charge"]) if row.get("charge") not in (None, "", "null") else None,
            "monoisotopic_mass": (
                float(row["monoisotopic_mass"])
                if row.get("monoisotopic_mass") not in (None, "", "null")
                else None
            ),
            "is_autogenerated": row.get("is_autogenerated"),
        }
    logger.info("chemical_data parsed: %d compound rows  (%.1fs)",
                len(chem_data), time.time() - t0)

    t0 = time.time()
    batch = []
    n_inserted = 0
    for row in _iter_rows(CACHE_DIR / "compounds.tsv.gz"):
        cid = row["id"]
        # Skip status 5 (deleted) — these have been merged elsewhere; status 9 = OK
        if row.get("status_id") in ("5",):
            continue
        chem = chem_data.get(cid, {})
        batch.append((
            cid,
            f"CHEBI:{cid}",
            row.get("name") or row.get("ascii_name") or f"ChEBI {cid}",
            None,  # inchikey -- W3 D1 structures step
            None,  # inchikey_block14
            None,  # smiles
            chem.get("monoisotopic_mass"),
            chem.get("charge"),
            chem.get("formula"),
        ))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR IGNORE INTO compound "
                "(chebi_id, primary_id, name, inchikey, inchikey_block14, smiles, "
                "monoisotopic_mass, charge, formula) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
            n_inserted += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR IGNORE INTO compound "
            "(chebi_id, primary_id, name, inchikey, inchikey_block14, smiles, "
            "monoisotopic_mass, charge, formula) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            batch,
        )
        n_inserted += len(batch)
    conn.commit()
    logger.info("compounds inserted: %d  (%.1fs)", n_inserted, time.time() - t0)


# ---------------------------------------------------------------------------
# ETL Step 2 — names
# ---------------------------------------------------------------------------


def etl_names(conn: sqlite3.Connection) -> None:
    t0 = time.time()
    batch = []
    n_inserted = 0
    # Pre-load valid chebi_ids
    valid = {r[0] for r in conn.execute("SELECT chebi_id FROM compound")}
    for row in _iter_rows(CACHE_DIR / "names.tsv.gz"):
        cid = row["compound_id"]
        if cid not in valid:
            continue
        batch.append((cid, row["name"], row.get("type") or "SYNONYM"))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT INTO compound_name (chebi_id, name, name_type) VALUES (?, ?, ?)",
                batch,
            )
            n_inserted += len(batch); batch.clear()
    if batch:
        conn.executemany(
            "INSERT INTO compound_name (chebi_id, name, name_type) VALUES (?, ?, ?)",
            batch,
        )
        n_inserted += len(batch)
    conn.commit()
    logger.info("names inserted: %d  (%.1fs)", n_inserted, time.time() - t0)


# ---------------------------------------------------------------------------
# ETL Step 3 — xref (database_accession.tsv → compound_xref)
# ---------------------------------------------------------------------------


def etl_xref(conn: sqlite3.Connection) -> None:
    t0 = time.time()
    batch = []
    n_inserted = 0
    valid = {r[0] for r in conn.execute("SELECT chebi_id FROM compound")}
    src_dist = defaultdict(int)
    seen_pair: set[tuple] = set()
    for row in _iter_rows(CACHE_DIR / "database_accession.tsv.gz"):
        cid = row["compound_id"]
        src_id = row["source_id"]
        if src_id not in KEEP_SOURCE_IDS:
            continue
        if cid not in valid:
            continue
        ns = XREF_SOURCE_MAP[src_id]
        ext = row["accession_number"]
        # Drop duplicates within this ETL run (multiple ChEBI accession entries
        # can have the same (chebi, ns, ext) tuple)
        key = (cid, ns, ext)
        if key in seen_pair:
            continue
        seen_pair.add(key)
        batch.append((cid, ns, ext))
        src_dist[ns] += 1
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR IGNORE INTO compound_xref (chebi_id, external_ns, external_id) "
                "VALUES (?, ?, ?)", batch,
            )
            n_inserted += len(batch); batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR IGNORE INTO compound_xref (chebi_id, external_ns, external_id) "
            "VALUES (?, ?, ?)", batch,
        )
        n_inserted += len(batch)
    conn.commit()
    logger.info("xref inserted: %d  (%.1fs)", n_inserted, time.time() - t0)
    for ns, n in sorted(src_dist.items(), key=lambda x: -x[1]):
        logger.info("  %s: %d xrefs", ns, n)


# ---------------------------------------------------------------------------
# ETL Step 4 — structures (InChIKey / SMILES) — depends on structures.tsv.gz
# ---------------------------------------------------------------------------


def etl_structures(conn: sqlite3.Connection) -> None:
    """ETL structures.tsv (wide table with molfile/SMILES/InChI/InChIKey cols).

    molfile field is multiline-quoted → must use csv.reader to parse.
    Pick **default_structure='Y'** rows preferentially;keep one row per compound.
    """
    path = CACHE_DIR / "structures.tsv.gz"
    if not path.exists():
        logger.warning("structures.tsv.gz not found at %s — skip InChIKey/SMILES ETL", path)
        return
    t0 = time.time()
    valid = {r[0] for r in conn.execute("SELECT chebi_id FROM compound")}
    by_compound: dict[str, dict] = {}
    n_rows = 0
    with _open_tsv(path) as f:
        reader = csv.reader(f, delimiter="\t", quotechar='"')
        header = next(reader)
        # Expected cols (rel251 verified 2026-05-15):
        # id, compound_id, status_id, molfile, smiles, standard_inchi,
        # standard_inchi_key, dimension, default_structure
        idx_cid = header.index("compound_id")
        idx_smi = header.index("smiles")
        idx_ik = header.index("standard_inchi_key")
        idx_default = header.index("default_structure")
        for row in reader:
            n_rows += 1
            if len(row) <= max(idx_cid, idx_smi, idx_ik, idx_default):
                continue
            cid = row[idx_cid]
            if not cid or cid not in valid:
                continue
            smi = (row[idx_smi] or "").strip()
            ik = (row[idx_ik] or "").strip()
            is_default = (row[idx_default] or "").strip().upper() in ("Y", "T", "TRUE", "1")
            entry = by_compound.setdefault(cid, {})
            if is_default or "inchikey" not in entry:
                if ik:
                    entry["inchikey"] = ik
                if smi:
                    entry["smiles"] = smi

    logger.info("structures parsed: %d rows → %d compounds with structure  (%.1fs)",
                n_rows, len(by_compound), time.time() - t0)

    t0 = time.time()
    upd = []
    for cid, ent in by_compound.items():
        ik = ent.get("inchikey")
        block14 = ik.split("-")[0] if ik else None
        upd.append((ik, block14, ent.get("smiles"), cid))
        if len(upd) >= BATCH_SIZE:
            conn.executemany(
                "UPDATE compound SET inchikey=?, inchikey_block14=?, smiles=? "
                "WHERE chebi_id=?", upd,
            )
            upd.clear()
    if upd:
        conn.executemany(
            "UPDATE compound SET inchikey=?, inchikey_block14=?, smiles=? "
            "WHERE chebi_id=?", upd,
        )
    conn.commit()
    n_with_ik = conn.execute(
        "SELECT COUNT(*) FROM compound WHERE inchikey IS NOT NULL AND inchikey != ''"
    ).fetchone()[0]
    n_with_smi = conn.execute(
        "SELECT COUNT(*) FROM compound WHERE smiles IS NOT NULL AND smiles != ''"
    ).fetchone()[0]
    logger.info("structures applied: %d compounds with InChIKey, %d with SMILES  (%.1fs)",
                n_with_ik, n_with_smi, time.time() - t0)


# ---------------------------------------------------------------------------
# ETL Step 5 — is_a hierarchy (W3 D2)
# ---------------------------------------------------------------------------


IS_A_RELATION_TYPE_ID = "5"  # per ChEBI rel251 relation_type.tsv lookup


def etl_isa(conn: sqlite3.Connection, max_depth: int = 5) -> None:
    """relation.tsv (rel251) schema:
        id, relation_type_id, init_id, final_id, status_id,
        evidence_accession, evidence_source_id

    is_a: relation_type_id == 5,init_id IS_A final_id (init = more specific child).
    """
    t0 = time.time()
    valid = {r[0] for r in conn.execute("SELECT chebi_id FROM compound")}
    direct_parents: dict[str, list[str]] = defaultdict(list)
    n_skip_invalid = 0
    for row in _iter_rows(CACHE_DIR / "relation.tsv.gz"):
        if row.get("relation_type_id") != IS_A_RELATION_TYPE_ID:
            continue
        init = row.get("init_id")
        final = row.get("final_id")
        if not init or not final:
            continue
        if init not in valid or final not in valid:
            n_skip_invalid += 1
            continue
        direct_parents[init].append(final)
    logger.info("is_a parsed: %d compounds with ≥1 direct parent  "
                "(%d skipped — parent/child not in compound table)  (%.1fs)",
                len(direct_parents), n_skip_invalid, time.time() - t0)
    n_direct = sum(len(v) for v in direct_parents.values())
    logger.info("is_a direct edges: %d (over %d compounds with ≥1 parent)  (%.1fs)",
                n_direct, len(direct_parents), time.time() - t0)

    # Flatten transitive ancestors up to max_depth (BFS per compound)
    t0 = time.time()
    rows_out: list[tuple[str, str, int]] = []
    for child, parents in direct_parents.items():
        # depth 1 = direct
        seen = {child}
        current_level = list(parents)
        for depth in range(1, max_depth + 1):
            next_level = []
            for p in current_level:
                if p in seen:
                    continue
                seen.add(p)
                rows_out.append((child, p, depth))
                next_level.extend(direct_parents.get(p, []))
            current_level = next_level
            if not current_level:
                break
    logger.info("is_a flattened: %d (child, parent, depth) triples  (%.1fs)",
                len(rows_out), time.time() - t0)

    t0 = time.time()
    n_inserted = 0
    for i in range(0, len(rows_out), BATCH_SIZE):
        chunk = rows_out[i : i + BATCH_SIZE]
        conn.executemany(
            "INSERT OR IGNORE INTO compound_isa "
            "(child_chebi_id, parent_chebi_id, depth) VALUES (?, ?, ?)",
            chunk,
        )
        n_inserted += len(chunk)
    conn.commit()
    logger.info("is_a inserted: %d  (%.1fs)", n_inserted, time.time() - t0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(args: argparse.Namespace) -> int:
    t_total = time.time()
    if DB_PATH.exists() and not args.append:
        logger.info("Removing existing %s", DB_PATH)
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    if not args.append:
        conn.executescript(SCHEMA)
    try:
        if args.compounds_only or not args.skip_compounds:
            etl_compounds(conn)
        if not args.skip_names:
            etl_names(conn)
        if not args.skip_xref:
            etl_xref(conn)
        if not args.skip_structures:
            etl_structures(conn)
        if args.with_isa:
            etl_isa(conn, max_depth=args.isa_max_depth)
    finally:
        conn.close()

    logger.info("DONE — total wall %.1fs;  db at %s  (%.1f MB)",
                time.time() - t_total, DB_PATH,
                DB_PATH.stat().st_size / 1024 / 1024)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ChEBI rel251 → sqlite ETL")
    p.add_argument("--skip-compounds", action="store_true")
    p.add_argument("--compounds-only", action="store_true")
    p.add_argument("--skip-names", action="store_true")
    p.add_argument("--skip-xref", action="store_true")
    p.add_argument("--skip-structures", action="store_true")
    p.add_argument("--with-isa", action="store_true",
                   help="Run is_a hierarchy ETL (W3 D2)")
    p.add_argument("--isa-max-depth", type=int, default=5)
    p.add_argument("--append", action="store_true",
                   help="Do NOT drop existing DB; append (debug only)")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main(parse_args()))
