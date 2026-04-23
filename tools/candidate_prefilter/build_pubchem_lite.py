"""Build script for the local pubchem_lite SQLite DB.

Ingests one or both of:
  - HMDB's `hmdb_metabolites.xml` dump (source='hmdb', compound_id=HMDB ID)
  - PubChemLite for Exposomics CSV (source='pubchem', compound_id='CID:<cid>')

Both sources write into the same table defined in `pubchem_index.py`.
`INSERT OR IGNORE` on `compound_id` prevents duplicate keys across sources
(HMDB uses 'HMDB…' prefixes, PubChemLite uses 'CID:…' — no collision
expected, but the guard is cheap).

Usage
-----

    # HMDB only (v0)
    python -m tools.candidate_prefilter.build_pubchem_lite \\
        --hmdb-xml hmdb_metabolites.xml \\
        --output   pubchem_lite.sqlite

    # HMDB + PubChemLite for Exposomics (v0.1)
    python -m tools.candidate_prefilter.build_pubchem_lite \\
        --hmdb-xml         hmdb_metabolites.xml \\
        --pubchemlite-csv  PubChemLite_exposomics_20260327.csv \\
        --output           pubchem_lite.sqlite

    # PubChemLite only
    python -m tools.candidate_prefilter.build_pubchem_lite \\
        --pubchemlite-csv  PubChemLite_exposomics_20260327.csv \\
        --output           pubchem_lite.sqlite

    export METAGENT_PUBCHEM_LITE_PATH=$(pwd)/pubchem_lite.sqlite

Data sources
------------

HMDB:          https://hmdb.ca/downloads  (hmdb_metabolites.zip → XML)
PubChemLite:   https://zenodo.org/records/19346011  (single CSV, ~250 MB)
               Schymanski group; MetFrag-compatible; ~570k compounds
               curated from 11 PubChem TOC categories.

Memory behaviour: HMDB path uses xml.etree.iterparse with element clearing,
peak RAM under ~500 MB. PubChemLite path streams csv.DictReader row-by-row.

RDKit is used to (a) validate SMILES, (b) recompute monoisotopic exact mass
from the parsed molecule for consistency across sources, and (c) compute a
canonical SMILES. Rows whose SMILES RDKit cannot parse are skipped. Use
--no-rdkit to trust source-supplied formula/mass verbatim (faster but may
introduce cross-source precision differences).
"""
from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

logger = logging.getLogger("build_pubchem_lite")


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pubchem_lite (
    compound_id       TEXT PRIMARY KEY,
    source            TEXT NOT NULL,
    name              TEXT,
    smiles            TEXT NOT NULL,
    canonical_smiles  TEXT,
    inchikey          TEXT,
    molecular_formula TEXT NOT NULL,
    exact_mass        REAL NOT NULL,
    pubchem_cid       INTEGER,
    hmdb_id           TEXT
);
"""

_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_exact_mass ON pubchem_lite(exact_mass);",
    "CREATE INDEX IF NOT EXISTS idx_formula ON pubchem_lite(molecular_formula);",
    "CREATE INDEX IF NOT EXISTS idx_inchikey ON pubchem_lite(inchikey);",
]


# ---------------------------------------------------------------------------
# HMDB XML streaming parse
# ---------------------------------------------------------------------------


def _localname(tag: str) -> str:
    """Drop any XML namespace prefix from a tag."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


_WANTED_HMDB_TAGS = {
    "accession",
    "name",
    "chemical_formula",
    "monisotopic_molecular_weight",  # HMDB's historical typo, kept verbatim
    "smiles",
    "inchikey",
}


def iter_hmdb_metabolites(xml_path: str | Path) -> Iterator[dict]:
    """Yield per-metabolite dicts with the fields pubchem_lite needs."""
    path = Path(xml_path)
    context = ET.iterparse(str(path), events=("end",))
    for _, elem in context:
        if _localname(elem.tag) != "metabolite":
            continue

        out = {
            "accession": None,
            "name": None,
            "formula": None,
            "monoisotopic_mass": None,
            "smiles": None,
            "inchikey": None,
        }
        for child in elem:
            name = _localname(child.tag)
            if name not in _WANTED_HMDB_TAGS:
                continue
            text = (child.text or "").strip() or None
            if name == "accession":
                out["accession"] = text
            elif name == "name":
                out["name"] = text
            elif name == "chemical_formula":
                out["formula"] = text
            elif name == "monisotopic_molecular_weight":
                try:
                    out["monoisotopic_mass"] = float(text) if text else None
                except ValueError:
                    out["monoisotopic_mass"] = None
            elif name == "smiles":
                out["smiles"] = text
            elif name == "inchikey":
                out["inchikey"] = text

        elem.clear()

        if out["accession"]:
            yield out


# ---------------------------------------------------------------------------
# PubChemLite CSV streaming parse
# ---------------------------------------------------------------------------


def iter_pubchemlite_rows(csv_path: str | Path) -> Iterator[dict]:
    """Yield per-compound dicts from a PubChemLite for Exposomics CSV.

    Columns used: Identifier (CID), MolecularFormula, SMILES, InChIKey,
    MonoisotopicMass, CompoundName. Other columns (XLogP, annotation counts,
    etc.) are ignored — we only index what candidate_prefilter cares about.
    """
    path = Path(csv_path)
    # Long InChI strings can exceed the default field size.
    csv.field_size_limit(10_000_000)

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid_raw = (row.get("Identifier") or "").strip()
            if not cid_raw:
                continue
            try:
                cid = int(cid_raw)
            except ValueError:
                continue

            def _nonempty(key: str) -> str | None:
                val = (row.get(key) or "").strip()
                return val or None

            mass_raw = _nonempty("MonoisotopicMass")
            try:
                monoisotopic_mass = float(mass_raw) if mass_raw else None
            except ValueError:
                monoisotopic_mass = None

            yield {
                "cid": cid,
                "name": _nonempty("CompoundName"),
                "smiles": _nonempty("SMILES"),
                "inchikey": _nonempty("InChIKey"),
                "formula": _nonempty("MolecularFormula"),
                "monoisotopic_mass": monoisotopic_mass,
            }


# ---------------------------------------------------------------------------
# RDKit-backed record normalisation
# ---------------------------------------------------------------------------


def _rdkit_normalise(smiles: str) -> tuple[str | None, str | None, str | None, float | None]:
    """Return (canonical_smiles, inchikey, formula, exact_mass) or Nones on failure."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, rdMolDescriptors
    except ImportError:
        return None, None, None, None

    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None, None, None, None
        canonical = Chem.MolToSmiles(mol)
        inchikey = Chem.MolToInchiKey(mol) or None
        formula = rdMolDescriptors.CalcMolFormula(mol)
        exact = float(Descriptors.ExactMolWt(mol))
        if exact <= 0:
            return None, None, None, None
        return canonical, inchikey, formula, exact
    except Exception:
        return None, None, None, None


# ---------------------------------------------------------------------------
# Per-source ingest
# ---------------------------------------------------------------------------


_INSERT_HMDB_SQL = (
    "INSERT OR IGNORE INTO pubchem_lite "
    "(compound_id, source, name, smiles, canonical_smiles, inchikey, "
    " molecular_formula, exact_mass, pubchem_cid, hmdb_id) "
    "VALUES (?, 'hmdb', ?, ?, ?, ?, ?, ?, NULL, ?)"
)

_INSERT_PUBCHEM_SQL = (
    "INSERT OR IGNORE INTO pubchem_lite "
    "(compound_id, source, name, smiles, canonical_smiles, inchikey, "
    " molecular_formula, exact_mass, pubchem_cid, hmdb_id) "
    "VALUES (?, 'pubchem', ?, ?, ?, ?, ?, ?, ?, NULL)"
)


def _ingest_hmdb(
    conn: sqlite3.Connection,
    hmdb_xml_path: str | Path,
    *,
    use_rdkit: bool,
    batch_size: int,
    log_every: int,
) -> tuple[int, int]:
    batch: list[tuple] = []
    n_inserted = 0
    n_skipped = 0
    n_seen = 0

    for rec in iter_hmdb_metabolites(hmdb_xml_path):
        n_seen += 1
        if n_seen % log_every == 0:
            logger.info(
                "hmdb progress: %d seen, %d inserted, %d skipped",
                n_seen, n_inserted, n_skipped,
            )

        smiles = rec["smiles"]
        if not smiles:
            n_skipped += 1
            continue

        if use_rdkit:
            canonical, inchikey, formula, exact = _rdkit_normalise(smiles)
            if canonical is None or formula is None or exact is None:
                n_skipped += 1
                continue
        else:
            canonical = None
            inchikey = rec["inchikey"]
            formula = rec["formula"]
            exact = rec["monoisotopic_mass"]
            if not formula or exact is None or exact <= 0:
                n_skipped += 1
                continue

        batch.append(
            (
                rec["accession"],   # compound_id
                rec["name"],
                smiles,
                canonical,
                inchikey,
                formula,
                exact,
                rec["accession"],   # hmdb_id
            )
        )
        n_inserted += 1

        if len(batch) >= batch_size:
            conn.executemany(_INSERT_HMDB_SQL, batch)
            conn.commit()
            batch.clear()

    if batch:
        conn.executemany(_INSERT_HMDB_SQL, batch)
        conn.commit()

    logger.info("hmdb ingest: %d inserted, %d skipped", n_inserted, n_skipped)
    return n_inserted, n_skipped


def _ingest_pubchemlite(
    conn: sqlite3.Connection,
    csv_path: str | Path,
    *,
    use_rdkit: bool,
    batch_size: int,
    log_every: int,
) -> tuple[int, int]:
    batch: list[tuple] = []
    n_inserted = 0
    n_skipped = 0
    n_seen = 0

    for rec in iter_pubchemlite_rows(csv_path):
        n_seen += 1
        if n_seen % log_every == 0:
            logger.info(
                "pubchemlite progress: %d seen, %d inserted, %d skipped",
                n_seen, n_inserted, n_skipped,
            )

        smiles = rec["smiles"]
        if not smiles:
            n_skipped += 1
            continue

        if use_rdkit:
            canonical, inchikey, formula, exact = _rdkit_normalise(smiles)
            if canonical is None or formula is None or exact is None:
                n_skipped += 1
                continue
        else:
            canonical = None
            inchikey = rec["inchikey"]
            formula = rec["formula"]
            exact = rec["monoisotopic_mass"]
            if not formula or exact is None or exact <= 0:
                n_skipped += 1
                continue

        cid = rec["cid"]
        compound_id = f"CID:{cid}"
        batch.append(
            (
                compound_id,
                rec["name"],
                smiles,
                canonical,
                inchikey,
                formula,
                exact,
                cid,                # pubchem_cid
            )
        )
        n_inserted += 1

        if len(batch) >= batch_size:
            conn.executemany(_INSERT_PUBCHEM_SQL, batch)
            conn.commit()
            batch.clear()

    if batch:
        conn.executemany(_INSERT_PUBCHEM_SQL, batch)
        conn.commit()

    logger.info("pubchemlite ingest: %d inserted, %d skipped", n_inserted, n_skipped)
    return n_inserted, n_skipped


# ---------------------------------------------------------------------------
# Top-level build
# ---------------------------------------------------------------------------


def build(
    output_db_path: str | Path,
    *,
    hmdb_xml_path: str | Path | None = None,
    pubchemlite_csv_path: str | Path | None = None,
    use_rdkit: bool = True,
    batch_size: int = 1000,
    log_every: int = 5000,
) -> dict[str, tuple[int, int]]:
    """Build the pubchem_lite SQLite DB from HMDB and/or PubChemLite sources.

    Returns {source: (n_inserted, n_skipped)} keyed by 'hmdb' / 'pubchem' for
    whichever sources were requested.
    """
    output_db_path = Path(output_db_path)
    if hmdb_xml_path is None and pubchemlite_csv_path is None:
        raise ValueError(
            "At least one of hmdb_xml_path / pubchemlite_csv_path must be given."
        )
    if hmdb_xml_path is not None and not Path(hmdb_xml_path).exists():
        raise FileNotFoundError(hmdb_xml_path)
    if pubchemlite_csv_path is not None and not Path(pubchemlite_csv_path).exists():
        raise FileNotFoundError(pubchemlite_csv_path)

    # Overwrite any pre-existing DB — builds are idempotent.
    if output_db_path.exists():
        output_db_path.unlink()

    conn = sqlite3.connect(str(output_db_path))
    stats: dict[str, tuple[int, int]] = {}
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

        if hmdb_xml_path is not None:
            logger.info("ingesting HMDB from %s", hmdb_xml_path)
            stats["hmdb"] = _ingest_hmdb(
                conn, hmdb_xml_path,
                use_rdkit=use_rdkit,
                batch_size=batch_size,
                log_every=log_every,
            )

        if pubchemlite_csv_path is not None:
            logger.info("ingesting PubChemLite from %s", pubchemlite_csv_path)
            stats["pubchem"] = _ingest_pubchemlite(
                conn, pubchemlite_csv_path,
                use_rdkit=use_rdkit,
                batch_size=batch_size,
                log_every=log_every,
            )

        for stmt in _INDEX_SQL:
            conn.execute(stmt)
        conn.commit()
        conn.execute("ANALYZE;")
        conn.commit()
    finally:
        conn.close()

    summary = ", ".join(
        f"{src}={ins} inserted ({skip} skipped)"
        for src, (ins, skip) in stats.items()
    )
    logger.info("build complete: %s, DB at %s", summary, output_db_path)
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Build the pubchem_lite SQLite DB. "
            "At least one of --hmdb-xml / --pubchemlite-csv is required."
        ),
    )
    p.add_argument("--hmdb-xml", help="Path to hmdb_metabolites.xml")
    p.add_argument(
        "--pubchemlite-csv",
        help="Path to PubChemLite_exposomics_*.csv (from Zenodo).",
    )
    p.add_argument("--output", required=True, help="Output .sqlite path")
    p.add_argument(
        "--no-rdkit",
        action="store_true",
        help="Trust source-supplied formula/mass instead of recomputing with RDKit.",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.hmdb_xml and not args.pubchemlite_csv:
        print("ERROR: at least one of --hmdb-xml / --pubchemlite-csv is required.")
        return 2
    stats = build(
        output_db_path=args.output,
        hmdb_xml_path=args.hmdb_xml,
        pubchemlite_csv_path=args.pubchemlite_csv,
        use_rdkit=not args.no_rdkit,
    )
    for src, (ins, skip) in stats.items():
        print(f"{src}: inserted={ins} skipped={skip}")
    print(f"db={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
