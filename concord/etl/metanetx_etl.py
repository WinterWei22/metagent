"""MetaNetX MNXref → sqlite ETL (W4 D3).

Input (under ``data/investigation/metanetx_cache/`` — Session 2 partial download):
    chem_xref.tsv   — MNX_ID ↔ external xref(580+ MB partial from Session 2)
    chem_prop.tsv   — MNX_ID metadata: name, formula, charge, InChI, SMILES

Output: ``data/concord/metanetx.sqlite``

Schema(per W4 D3 spec):
    mnx_compound (mnx_id PK, name, formula, charge, inchikey, inchikey_block14)
    mnx_xref (mnx_id FK, external_ns, external_id)

Source ID legend(from chem_xref.tsv,Session 2 verified):
    Source prefixes seen: reactome, reactomeM, chebi, CHEBI, hmdb, HMDB,
        kegg.compound, keggC, keggD, keggG, metacyc.compound, metacycM,
        bigg.metabolite, biggM, slm, SLM, lipidmaps, LIPIDMAPS, ...
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("metanetx_etl")
logging.basicConfig(
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)

WORKTREE = Path(__file__).resolve().parents[2]
CACHE_DIR = WORKTREE / "data" / "investigation" / "metanetx_cache"
DB_PATH = WORKTREE / "data" / "concord" / "metanetx.sqlite"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Source-prefix → ConcordMet canonical namespace
XREF_NS_MAP = {
    "chebi":            "CHEBI",
    "CHEBI":            "CHEBI",
    "hmdb":             "HMDB",
    "HMDB":             "HMDB",
    "kegg.compound":    "KEGG",
    "keggC":            "KEGG",
    "kegg.drug":        "KEGG_DRUG",
    "keggD":            "KEGG_DRUG",
    "kegg.glycan":      "KEGG_GLYCAN",
    "keggG":            "KEGG_GLYCAN",
    "metacyc.compound": "METACYC",
    "metacycM":         "METACYC",
    "bigg.metabolite":  "BIGG",
    "biggM":            "BIGG",
    "slm":              "LIPIDMAPS",   # SwissLipids
    "SLM":              "LIPIDMAPS",
    "lipidmaps":        "LIPIDMAPS",
    "LIPIDMAPS":        "LIPIDMAPS",
    "reactome":         "REACTOME",
    "reactomeM":        "REACTOME",
    "pubchem.compound": "PUBCHEM",
    "pubchemC":         "PUBCHEM",
    "sabiork.compound": "SABIORK",
    "sabiorkM":         "SABIORK",
    "seed.compound":    "SEED",
    "seedM":            "SEED",
}

BATCH_SIZE = 5000

SCHEMA = """
DROP TABLE IF EXISTS mnx_compound;
DROP TABLE IF EXISTS mnx_xref;

CREATE TABLE mnx_compound (
    mnx_id           TEXT PRIMARY KEY,    -- "MNXM12345"
    name             TEXT,
    formula          TEXT,
    charge           INTEGER,
    inchikey         TEXT,
    inchikey_block14 TEXT
);
CREATE INDEX idx_mnx_inchikey_block14 ON mnx_compound(inchikey_block14);
CREATE INDEX idx_mnx_inchikey ON mnx_compound(inchikey);

CREATE TABLE mnx_xref (
    mnx_id      TEXT NOT NULL,
    external_ns TEXT NOT NULL,
    external_id TEXT NOT NULL,
    FOREIGN KEY (mnx_id) REFERENCES mnx_compound(mnx_id)
);
CREATE INDEX idx_mnx_xref_external ON mnx_xref(external_ns, external_id);
CREATE UNIQUE INDEX uq_mnx_xref ON mnx_xref(mnx_id, external_ns, external_id);
"""


def _iter_tsv_rows(path: Path):
    """Yield non-comment rows split on TAB. Handles partial download
    (skips truncated last line)."""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            if not line.endswith("\n"):
                # truncated last line (partial download artifact) — skip
                continue
            yield line.rstrip("\n").split("\t")


def etl_chem_prop(conn: sqlite3.Connection) -> None:
    """chem_prop.tsv schema(MetaNetX 4.5, no header row — data starts directly
    after the # comment block,verified 2026-05-16):
        column 0: MNX_ID         (e.g. "MNXM01")
        column 1: name           (e.g. "PMF")
        column 2: reference      (e.g. "mnx:PMF")
        column 3: formula        (e.g. "H")
        column 4: charge         (signed integer)
        column 5: mass           (float)
        column 6: InChI          ("InChI=1S/...")
        column 7: InChIKey       (27-char)
        column 8: SMILES
    """
    path = CACHE_DIR / "chem_prop.tsv"
    if not path.exists():
        logger.error("chem_prop.tsv missing — download from MetaNetX FTP first")
        return

    t0 = time.time()
    batch = []
    n_inserted = 0
    n_with_ik = 0

    for cols in _iter_tsv_rows(path):
        if len(cols) < 8:
            continue
        mnx_id = cols[0]
        if not mnx_id.startswith("MNX"):
            continue
        ik = cols[7].strip()
        block14 = ik.split("-")[0] if ik else None
        charge_raw = cols[4].strip() if len(cols) > 4 else ""
        try:
            charge_int = int(charge_raw) if charge_raw not in ("", "NA", "null") else None
        except ValueError:
            charge_int = None
        batch.append((
            mnx_id,
            cols[1].strip() or None,                  # name
            cols[3].strip() or None,                  # formula
            charge_int,
            ik or None,
            block14 or None,
        ))
        if ik:
            n_with_ik += 1
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR REPLACE INTO mnx_compound "
                "(mnx_id, name, formula, charge, inchikey, inchikey_block14) "
                "VALUES (?, ?, ?, ?, ?, ?)", batch,
            )
            n_inserted += len(batch); batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO mnx_compound "
            "(mnx_id, name, formula, charge, inchikey, inchikey_block14) "
            "VALUES (?, ?, ?, ?, ?, ?)", batch,
        )
        n_inserted += len(batch)
    conn.commit()
    logger.info("mnx_compound inserted: %d (%d w/ InChIKey)  (%.1fs)",
                n_inserted, n_with_ik, time.time() - t0)


def etl_chem_xref(conn: sqlite3.Connection) -> None:
    """chem_xref.tsv schema(MetaNetX 4.5):
        #source	ID	description
    Where ``source`` is "<source_prefix>:<external_id>" and ID is the MNX_ID.
    """
    path = CACHE_DIR / "chem_xref.tsv"
    if not path.exists():
        logger.error("chem_xref.tsv missing")
        return

    t0 = time.time()
    chem_prop_mnx = {r[0] for r in conn.execute("SELECT mnx_id FROM mnx_compound")}
    batch = []
    n_inserted = 0
    src_dist: dict[str, int] = defaultdict(int)
    seen_keys: set[tuple] = set()
    n_kept_lines = 0
    n_unstructured_mnx = 0
    # Stub-insert MNX entries from xref-only side so the FK works
    stub_batch = []

    for cols in _iter_tsv_rows(path):
        if len(cols) < 2:
            continue
        src_field = cols[0]
        mnx_id = cols[1]
        if not mnx_id.startswith("MNXM"):
            continue
        if mnx_id not in chem_prop_mnx:
            # Unstructured MNX entry — add a stub (no inchikey/structure)
            # so xref FK works + validator can still say "different MNX_IDs"
            stub_batch.append((mnx_id, None, None, None, None, None))
            chem_prop_mnx.add(mnx_id)  # avoid re-inserting
            n_unstructured_mnx += 1
        if ":" in src_field:
            src_prefix, ext_id = src_field.split(":", 1)
        else:
            src_prefix, ext_id = src_field, ""
        ns = XREF_NS_MAP.get(src_prefix)
        if ns is None:
            continue
        key = (mnx_id, ns, ext_id)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        batch.append((mnx_id, ns, ext_id))
        src_dist[ns] += 1
        n_kept_lines += 1
        if len(stub_batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR IGNORE INTO mnx_compound "
                "(mnx_id, name, formula, charge, inchikey, inchikey_block14) "
                "VALUES (?, ?, ?, ?, ?, ?)", stub_batch,
            )
            stub_batch.clear()
    if stub_batch:
        conn.executemany(
            "INSERT OR IGNORE INTO mnx_compound "
            "(mnx_id, name, formula, charge, inchikey, inchikey_block14) "
            "VALUES (?, ?, ?, ?, ?, ?)", stub_batch,
        )
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR IGNORE INTO mnx_xref "
                "(mnx_id, external_ns, external_id) VALUES (?, ?, ?)",
                batch,
            )
            n_inserted += len(batch); batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR IGNORE INTO mnx_xref "
            "(mnx_id, external_ns, external_id) VALUES (?, ?, ?)",
            batch,
        )
        n_inserted += len(batch)
    conn.commit()
    logger.info("mnx_xref inserted: %d  (%d unstructured-MNX stubs added)  (%.1fs)",
                n_inserted, n_unstructured_mnx, time.time() - t0)
    for ns, n in sorted(src_dist.items(), key=lambda x: -x[1]):
        logger.info("  %s: %d", ns, n)


def main(args: argparse.Namespace) -> int:
    t_total = time.time()
    if DB_PATH.exists() and not args.append:
        logger.info("Removing existing %s", DB_PATH)
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    if not args.append:
        conn.executescript(SCHEMA)
    try:
        if not args.skip_prop:
            etl_chem_prop(conn)
        if not args.skip_xref:
            etl_chem_xref(conn)
    finally:
        conn.close()
    logger.info("DONE — wall %.1fs;  %s  (%.1f MB)",
                time.time() - t_total, DB_PATH,
                DB_PATH.stat().st_size / 1024 / 1024)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MetaNetX → sqlite ETL")
    p.add_argument("--skip-prop", action="store_true")
    p.add_argument("--skip-xref", action="store_true")
    p.add_argument("--append", action="store_true")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main(parse_args()))
