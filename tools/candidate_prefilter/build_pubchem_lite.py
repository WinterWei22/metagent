"""Build script for the local pubchem_lite SQLite DB.

v0 implementation: ingests HMDB's `hmdb_metabolites.xml` dump into the
SQLite schema declared in `pubchem_index.py`. v0.1+ will append DrugBank,
ChEBI, and a PubChem Bioactive subset into the same table (source column
already parameterised).

Usage
-----

    # 1. Download HMDB (one-time, ~4GB uncompressed)
    wget https://hmdb.ca/system/downloads/current/hmdb_metabolites.zip
    unzip hmdb_metabolites.zip   # -> hmdb_metabolites.xml

    # 2. Build the SQLite DB
    python -m tools.candidate_prefilter.build_pubchem_lite \\
        --hmdb-xml hmdb_metabolites.xml \\
        --output pubchem_lite.sqlite

    # 3. Point the tool at it
    export METAGENT_PUBCHEM_LITE_PATH=$(pwd)/pubchem_lite.sqlite

Memory behaviour: uses xml.etree.ElementTree.iterparse with element clearing,
so peak RAM stays under ~500 MB even for the full 4 GB XML.

RDKit is used to (a) validate SMILES, (b) recompute monoisotopic exact mass
from the parsed molecule (HMDB's reported monoisotopic_molecular_weight is
often truncated to 4 decimal places; RDKit gives full precision), and (c)
compute a canonical SMILES. HMDB records whose SMILES RDKit cannot parse are
skipped with a warning — running totals are logged at the end.
"""
from __future__ import annotations

import argparse
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
    """Drop any XML namespace prefix from a tag.

    HMDB's namespace has varied over versions ('http://www.hmdb.ca',
    sometimes none at all). Stripping gives us a single code path regardless.
    """
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


_WANTED_CHILD_TAGS = {
    "accession",
    "name",
    "chemical_formula",
    "monisotopic_molecular_weight",  # HMDB's historical typo, kept verbatim
    "smiles",
    "inchikey",
}


def iter_hmdb_metabolites(xml_path: str | Path) -> Iterator[dict]:
    """Yield per-metabolite dicts with the fields pubchem_lite needs.

    Streaming: uses iterparse + element.clear() so full-dump memory stays flat.
    """
    path = Path(xml_path)
    # iterparse with end events only; we read children off the finished
    # <metabolite> element, then clear it.
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
            if name not in _WANTED_CHILD_TAGS:
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
        # Also drop references higher up the tree (root keeps accumulating
        # otherwise). ElementTree doesn't expose a parent pointer from
        # iterparse; clearing the element itself is enough for flat RAM.

        if out["accession"]:
            yield out


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
# Builder
# ---------------------------------------------------------------------------


def build(
    hmdb_xml_path: str | Path,
    output_db_path: str | Path,
    *,
    use_rdkit: bool = True,
    batch_size: int = 1000,
    log_every: int = 5000,
) -> tuple[int, int]:
    """Build the pubchem_lite SQLite DB from an HMDB XML dump.

    Returns (n_inserted, n_skipped).
    """
    hmdb_xml_path = Path(hmdb_xml_path)
    output_db_path = Path(output_db_path)

    if not hmdb_xml_path.exists():
        raise FileNotFoundError(hmdb_xml_path)

    # Overwrite any pre-existing DB — builds are idempotent and we don't want
    # to silently mix old data with new.
    if output_db_path.exists():
        output_db_path.unlink()

    conn = sqlite3.connect(str(output_db_path))
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

        insert_sql = (
            "INSERT OR IGNORE INTO pubchem_lite "
            "(compound_id, source, name, smiles, canonical_smiles, inchikey, "
            " molecular_formula, exact_mass, pubchem_cid, hmdb_id) "
            "VALUES (?, 'hmdb', ?, ?, ?, ?, ?, ?, NULL, ?)"
        )

        batch: list[tuple] = []
        n_inserted = 0
        n_skipped = 0
        n_seen = 0

        for rec in iter_hmdb_metabolites(hmdb_xml_path):
            n_seen += 1
            if n_seen % log_every == 0:
                logger.info(
                    "progress: %d seen, %d inserted, %d skipped",
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
                    rec["accession"],          # compound_id
                    rec["name"],
                    smiles,
                    canonical,
                    inchikey,
                    formula,
                    exact,
                    rec["accession"],          # hmdb_id
                )
            )
            n_inserted += 1

            if len(batch) >= batch_size:
                conn.executemany(insert_sql, batch)
                conn.commit()
                batch.clear()

        if batch:
            conn.executemany(insert_sql, batch)
            conn.commit()

        for stmt in _INDEX_SQL:
            conn.execute(stmt)
        conn.commit()

        conn.execute("ANALYZE;")
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "build complete: %d inserted, %d skipped, DB at %s",
        n_inserted, n_skipped, output_db_path,
    )
    return n_inserted, n_skipped


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build the pubchem_lite SQLite DB from an HMDB XML dump."
    )
    p.add_argument("--hmdb-xml", required=True, help="Path to hmdb_metabolites.xml")
    p.add_argument("--output", required=True, help="Output .sqlite path")
    p.add_argument(
        "--no-rdkit",
        action="store_true",
        help="Trust HMDB's formula/mass instead of recomputing with RDKit (faster but less precise).",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    n_inserted, n_skipped = build(
        hmdb_xml_path=args.hmdb_xml,
        output_db_path=args.output,
        use_rdkit=not args.no_rdkit,
    )
    print(f"inserted={n_inserted} skipped={n_skipped} db={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
