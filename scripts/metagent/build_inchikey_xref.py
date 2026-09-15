"""Build aggregated InChIKey → cross-reference lookup table.

Sources (in order of priority):
  1. PubChem Extras (primary, most complete):
       CID-Identifiers.tsv.gz  → CID → {KEGG_ID, HMDB_ID, CHEBI_ID, LIPIDMAPS_ID}
       CID-InChI-Key.gz        → CID → InChIKey
     Join: InChIKey → CID → all xrefs

  2. HMDB JSON fallback (local, for HMDB-only metabolites not in PubChem):
       MetaKG/hmdb_metabolites.json → HMDB_ID → {InChIKey, KEGG_ID}

Output: data/concord/inchikey_xref.sqlite
Table : inchikey_xref(inchikey TEXT PK, chebi_id, kegg_id, hmdb_id, lipidmaps_id)

Usage:
    PYTHONPATH=. python scripts/metagent/build_inchikey_xref.py
    PYTHONPATH=. python scripts/metagent/build_inchikey_xref.py \\
        --cid-identifiers /tmp/pubchem_dl/CID-Identifiers.tsv.gz \\
        --cid-inchikey /tmp/pubchem_dl/CID-InChI-Key.gz \\
        --hmdb /path/to/hmdb_metabolites.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_DEFAULT_CID_IDENTIFIERS = Path("/tmp/pubchem_dl/CID-Identifiers.tsv.gz")
_DEFAULT_CID_INCHIKEY    = Path("/tmp/pubchem_dl/CID-InChI-Key.gz")
_DEFAULT_HMDB_JSON       = Path("/home/weiwentao/workspace/Enzyme_Networks/data/enzyme_networks/MetaKG/hmdb_metabolites.json")
_OUT_DB                  = Path("data/concord/inchikey_xref.sqlite")

# PubChem source type strings we care about
_WANTED_TYPES = {"KEGG ID", "HMDB ID", "ChEBI ID", "Lipid Maps ID (LM_ID)"}
_TYPE_TO_KEY  = {
    "KEGG ID":              "kegg_id",
    "HMDB ID":              "hmdb_id",
    "ChEBI ID":             "chebi_id",
    "Lipid Maps ID (LM_ID)":"lipidmaps_id",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build InChIKey → xref lookup table from PubChem")
    p.add_argument("--cid-identifiers", default=str(_DEFAULT_CID_IDENTIFIERS))
    p.add_argument("--cid-inchikey",    default=str(_DEFAULT_CID_INCHIKEY))
    p.add_argument("--hmdb",            default=str(_DEFAULT_HMDB_JSON))
    p.add_argument("--out",             default=str(_OUT_DB))
    return p.parse_args()


def _normalise_hmdb(raw: str) -> str | None:
    """Normalise HMDB IDs to HMDB0000xxx zero-padded form."""
    s = raw.strip().upper()
    if s.startswith("HMDB:"):
        s = s[5:]
    if not s.startswith("HMDB"):
        return None
    digits = s[4:]
    if not digits.isdigit():
        return None
    return f"HMDB{digits.zfill(7)}"


# ---------------------------------------------------------------------------
# Step 1: stream CID-Identifiers → {cid: {kegg_id, hmdb_id, chebi_id, ...}}
# ---------------------------------------------------------------------------

def _load_cid_xrefs(path: str) -> dict[str, dict[str, str]]:
    log.info("Pass 1: scanning %s for KEGG/HMDB/ChEBI/LIPIDMAPS …", path)
    cid_xrefs: dict[str, dict[str, str]] = defaultdict(dict)
    n_lines = 0
    n_kept  = 0
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            n_lines += 1
            if n_lines % 5_000_000 == 0:
                log.info("  … %dM lines, %d CIDs with xrefs", n_lines // 1_000_000, len(cid_xrefs))
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            cid, ext_id, src_type = parts[0], parts[1], parts[2]
            if src_type not in _WANTED_TYPES:
                continue
            key = _TYPE_TO_KEY[src_type]
            # Normalise HMDB to zero-padded form; skip if already set
            if key == "hmdb_id":
                ext_id = _normalise_hmdb(ext_id) or ext_id
            if key not in cid_xrefs[cid]:
                cid_xrefs[cid][key] = ext_id
            n_kept += 1

    log.info("Pass 1 done: %dM lines scanned, %d CIDs kept, %d xref rows",
             n_lines // 1_000_000, len(cid_xrefs), n_kept)
    return dict(cid_xrefs)


# ---------------------------------------------------------------------------
# Step 2: stream CID-InChI-Key → join with cid_xrefs → {inchikey: xrefs}
# ---------------------------------------------------------------------------

def _build_inchikey_map(
    inchikey_path: str,
    cid_xrefs: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    log.info("Pass 2: scanning %s to join InChIKey …", inchikey_path)
    result: dict[str, dict[str, str]] = {}
    n_lines = 0
    n_joined = 0
    with gzip.open(inchikey_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            n_lines += 1
            if n_lines % 5_000_000 == 0:
                log.info("  … %dM lines, %d joined", n_lines // 1_000_000, n_joined)
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            cid, _inchi, inchikey = parts[0], parts[1], parts[2]
            if cid not in cid_xrefs:
                continue
            xrefs = cid_xrefs[cid]
            if inchikey in result:
                # Merge: fill gaps
                existing = result[inchikey]
                for k, v in xrefs.items():
                    if k not in existing:
                        existing[k] = v
            else:
                result[inchikey] = dict(xrefs)
                n_joined += 1

    log.info("Pass 2 done: %dM lines, %d unique InChIKeys with xrefs", n_lines // 1_000_000, len(result))
    return result


# ---------------------------------------------------------------------------
# Step 3: HMDB JSON fallback — add InChIKeys not in PubChem result
# ---------------------------------------------------------------------------

def _merge_hmdb_json(result: dict[str, dict[str, str]], hmdb_path: str) -> None:
    if not Path(hmdb_path).exists():
        log.warning("HMDB JSON not found at %s — skipping fallback", hmdb_path)
        return
    log.info("Pass 3: merging HMDB JSON fallback from %s …", hmdb_path)
    d = json.load(open(hmdb_path, encoding="utf-8"))
    added = 0
    merged = 0
    for hmdb_id, entry in d.items():
        ik = entry.get("inchikey")
        if not ik:
            continue
        norm_hmdb = _normalise_hmdb(hmdb_id) or hmdb_id
        kegg_id   = entry.get("kegg_id") or None
        chebi_id  = entry.get("chebi_id") or None
        if ik in result:
            row = result[ik]
            if not row.get("hmdb_id"):
                row["hmdb_id"] = norm_hmdb
                merged += 1
            if kegg_id and not row.get("kegg_id"):
                row["kegg_id"] = kegg_id
        else:
            result[ik] = {
                "hmdb_id":    norm_hmdb,
                "kegg_id":    kegg_id,
                "chebi_id":   chebi_id,
                "lipidmaps_id": None,
            }
            added += 1
    log.info("HMDB JSON: %d new InChIKeys added, %d HMDB IDs filled in existing", added, merged)


# ---------------------------------------------------------------------------
# Step 4: write sqlite
# ---------------------------------------------------------------------------

def _write(out_path: str, data: dict[str, dict[str, str]]) -> None:
    log.info("Writing %d rows to %s …", len(data), out_path)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    if Path(out_path).exists():
        Path(out_path).unlink()

    conn = sqlite3.connect(out_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE inchikey_xref (
            inchikey     TEXT PRIMARY KEY,
            chebi_id     TEXT,
            kegg_id      TEXT,
            hmdb_id      TEXT,
            lipidmaps_id TEXT
        )
    """)
    c.execute("CREATE INDEX idx_kegg  ON inchikey_xref(kegg_id)")
    c.execute("CREATE INDEX idx_hmdb  ON inchikey_xref(hmdb_id)")
    c.execute("CREATE INDEX idx_chebi ON inchikey_xref(chebi_id)")

    batch = [
        (ik,
         v.get("chebi_id"), v.get("kegg_id"),
         v.get("hmdb_id"),  v.get("lipidmaps_id"))
        for ik, v in data.items()
    ]
    c.executemany("INSERT INTO inchikey_xref VALUES (?,?,?,?,?)", batch)
    conn.commit()
    conn.close()

    kegg_n = sum(1 for v in data.values() if v.get("kegg_id"))
    hmdb_n = sum(1 for v in data.values() if v.get("hmdb_id"))
    log.info("Done: %d rows | with KEGG: %d | with HMDB: %d", len(batch), kegg_n, hmdb_n)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    t0 = time.time()

    # Check inputs
    for label, path in [
        ("CID-Identifiers", args.cid_identifiers),
        ("CID-InChI-Key",   args.cid_inchikey),
    ]:
        if not Path(path).exists():
            raise FileNotFoundError(f"{label} not found: {path}")

    cid_xrefs = _load_cid_xrefs(args.cid_identifiers)
    ik_map    = _build_inchikey_map(args.cid_inchikey, cid_xrefs)
    _merge_hmdb_json(ik_map, args.hmdb)
    _write(args.out, ik_map)

    log.info("Total wall time: %.1fs", time.time() - t0)


if __name__ == "__main__":
    main()
