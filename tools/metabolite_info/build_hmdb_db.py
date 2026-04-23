"""Build the HMDB SQLite backing store for fetch_metabolite_info.

One-shot ingest script, not invoked at query time. Takes the public
`hmdb_metabolites.xml` dump and produces a `metabolites` table matching
the schema hmdb_backend.py queries. Run once per HMDB release:

    python -m tools.metabolite_info.build_hmdb_db \\
        --xml /data/hmdb/hmdb_metabolites.xml \\
        --out /data/hmdb/hmdb.sqlite

The XML is ~5 GB and contains ~220k records. We stream with
lxml.etree.iterparse and clear as we go so peak RSS stays under ~1 GB.

Record coverage:
- Every HMDB ID and its primary name / formula / exact mass.
- InChIKey, canonical SMILES when present.
- KEGG, ChEBI, PubChem, ChEMBL cross-references.
- `class` from the HMDB taxonomy block.
- Synonyms (all), tissue locations, disease associations.

We intentionally do NOT store any field whose parent XML element is
absent — the value lands as NULL, which the query layer surfaces as
`None`. This is the trust-anchor invariant.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# The HMDB XML uses a default namespace. Children are referenced with
# the fully-qualified tag, e.g. `{http://www.hmdb.ca}accession`.
_NS = "{http://www.hmdb.ca}"

# Paths inside one <metabolite> element that we extract. Each entry is
# (output_column, xpath_relative_to_metabolite).
_SIMPLE_FIELDS: list[tuple[str, str]] = [
    ("hmdb_id", "accession"),
    ("primary_name", "name"),
    ("molecular_formula", "chemical_formula"),
    ("exact_mass", "monisotopic_molecular_weight"),
    ("smiles", "smiles"),
    ("inchikey", "inchikey"),
    ("chemical_class", "taxonomy/class"),
]


def _ns(path: str) -> str:
    """Prefix each path segment with the HMDB namespace."""
    return "/".join(_NS + seg for seg in path.split("/"))


def _text(element, path: str) -> str | None:
    child = element.find(_ns(path))
    if child is None:
        return None
    return (child.text or "").strip() or None


def _crossref_value(element, resource_name: str) -> str | None:
    """Extract one external-link value by <resource_name>…</resource_name>."""
    for link in element.findall(_ns("external_links/external_link")):
        name = _text(link, "resource_name")
        if name and name.strip().lower() == resource_name.lower():
            return _text(link, "external_id")
    return None


def _list_texts(element, container: str, item: str) -> list[str]:
    """Collect stripped text for every <item> under <container>."""
    node = element.find(_ns(container))
    if node is None:
        return []
    out: list[str] = []
    for child in node.findall(_ns(item)):
        text = (child.text or "").strip()
        if text:
            out.append(text)
    return out


def _parse_metabolite(element) -> dict | None:
    """Convert one <metabolite> element into a flat row dict.

    Returns None only if we can't extract the primary key (hmdb_id).
    """
    row: dict = {}
    for col, path in _SIMPLE_FIELDS:
        row[col] = _text(element, path)
    if not row.get("hmdb_id"):
        return None

    mass = row.get("exact_mass")
    if mass is not None:
        try:
            row["exact_mass"] = float(mass)
        except ValueError:
            row["exact_mass"] = None

    row["kegg_id"] = _text(element, "kegg_id") or _crossref_value(element, "KEGG")
    row["chebi_id"] = _text(element, "chebi_id") or _crossref_value(element, "ChEBI")
    row["pubchem_cid"] = _text(element, "pubchem_compound_id") or _crossref_value(
        element, "PubChem"
    )
    row["chembl_id"] = _text(element, "chembl_id") or _crossref_value(element, "ChEMBL")

    synonyms = _list_texts(element, "synonyms", "synonym")
    tissues = _list_texts(element, "biological_properties/tissue_locations", "tissue")
    diseases = [
        name
        for name in (
            _text(d, "name") for d in element.findall(_ns("diseases/disease"))
        )
        if name
    ]

    row["synonyms_json"] = json.dumps(synonyms)
    row["tissue_locations_json"] = json.dumps(tissues)
    row["disease_associations_json"] = json.dumps(diseases)

    return row


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metabolites (
    hmdb_id                   TEXT PRIMARY KEY,
    primary_name              TEXT,
    molecular_formula         TEXT,
    exact_mass                REAL,
    smiles                    TEXT,
    inchikey                  TEXT,
    chemical_class            TEXT,
    kegg_id                   TEXT,
    chebi_id                  TEXT,
    pubchem_cid               TEXT,
    chembl_id                 TEXT,
    synonyms_json             TEXT,
    tissue_locations_json     TEXT,
    disease_associations_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_inchikey ON metabolites(inchikey);
CREATE INDEX IF NOT EXISTS idx_kegg     ON metabolites(kegg_id);
CREATE INDEX IF NOT EXISTS idx_name     ON metabolites(primary_name COLLATE NOCASE);
"""

_INSERT_SQL = """
INSERT OR REPLACE INTO metabolites VALUES (
    :hmdb_id, :primary_name, :molecular_formula, :exact_mass,
    :smiles, :inchikey, :chemical_class, :kegg_id, :chebi_id,
    :pubchem_cid, :chembl_id, :synonyms_json,
    :tissue_locations_json, :disease_associations_json
)
"""


def build(xml_path: Path, out_path: Path, batch_size: int = 1000) -> int:
    """Parse the XML and write the SQLite. Returns number of rows inserted."""
    try:
        from lxml import etree
    except ImportError:  # pragma: no cover - build-time only
        raise SystemExit(
            "lxml is required for HMDB XML ingest. "
            "Install it from tools/metabolite_info/requirements.txt."
        )

    if out_path.exists():
        out_path.unlink()
    conn = sqlite3.connect(out_path)
    try:
        conn.executescript(_SCHEMA_SQL)
        batch: list[dict] = []
        n_in = 0

        context = etree.iterparse(
            str(xml_path),
            events=("end",),
            tag=_NS + "metabolite",
        )
        for _event, element in context:
            row = _parse_metabolite(element)
            # Free the subtree before we forget about it — keeps RAM flat.
            element.clear()
            parent = element.getparent()
            if parent is not None:
                while element.getprevious() is not None:
                    del parent[0]
            if row is None:
                continue
            batch.append(row)
            n_in += 1
            if len(batch) >= batch_size:
                conn.executemany(_INSERT_SQL, batch)
                conn.commit()
                batch.clear()
                if n_in % 20000 == 0:
                    logger.info("ingested %d rows", n_in)
        if batch:
            conn.executemany(_INSERT_SQL, batch)
            conn.commit()
        logger.info("Done. %d rows written to %s", n_in, out_path)
        return n_in
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--xml", required=True, type=Path, help="Path to hmdb_metabolites.xml")
    ap.add_argument("--out", required=True, type=Path, help="Output SQLite path")
    ap.add_argument("--batch", type=int, default=1000)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    n = build(args.xml, args.out, args.batch)
    print(f"wrote {n} rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
