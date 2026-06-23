"""V3 Part 2 — build the unified structure index sqlite (2A-2 ETL).

Builds `data/concord/metanetx_struct.sqlite` (owned by this worktree; the
existing `metanetx.sqlite` is a symlink to a shared worktree and must NOT be
mutated). Tables:

    mnx_structure(mnx_id PK, smiles, inchikey, inchikey_block14)
        -- from full MetaNetX chem_prop.tsv (col0=MNX, col7=InChIKey, col8=SMILES)
    bigg_mnx(bigg_id PK, mnx_id)
        -- from full MetaNetX chem_xref.tsv, prefixes biggM / bigg.metabolite
    xref_mnx(ns, ext_id, mnx_id)  PK(ns, ext_id)
        -- generic {BIGG,KEGG,HMDB,LIPIDMAPS} -> MNX bridge (chem_xref)

Sources (auto-download chem_prop if missing; chem_xref reused from the
investigation cache or downloaded):
    chem_prop.tsv : https://www.metanetx.org/cgi-bin/mnxget/mnxref/chem_prop.tsv
    chem_xref.tsv : https://www.metanetx.org/cgi-bin/mnxget/mnxref/chem_xref.tsv

Idempotent: skips download if the file exists; rebuilds sqlite from scratch.
"""
from __future__ import annotations

import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data/concord/metanetx_cache"
CHEM_PROP = CACHE / "chem_prop_full.tsv"
CHEM_XREF = CACHE / "chem_xref_full.tsv"
INV_XREF = Path(
    "/home/weiwentao/workspace/llm_agent_metabolomics/"
    "metagent_day1_v5_investigation/data/investigation/metanetx_cache/chem_xref.tsv"
)
DB = ROOT / "data/concord/metanetx_struct.sqlite"
BASE_URL = "https://www.metanetx.org/cgi-bin/mnxget/mnxref"
UA = {"User-Agent": "curl/7"}  # MetaNetX rejects HEAD / blank UA; GET+UA works


def download(name: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BASE_URL}/{name}"
    print(f"  downloading {url} -> {dest} ...")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r, dest.open("wb") as out:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    print(f"  done ({dest.stat().st_size/1e6:.0f} MB)")


def ensure_sources() -> Path:
    if not CHEM_PROP.exists():
        download("chem_prop.tsv", CHEM_PROP)
    else:
        print(f"  chem_prop present ({CHEM_PROP.stat().st_size/1e6:.0f} MB)")
    # prefer the locally cached full chem_xref from the investigation worktree
    if CHEM_XREF.exists():
        return CHEM_XREF
    if INV_XREF.exists():
        print(f"  reusing investigation chem_xref ({INV_XREF})")
        return INV_XREF
    download("chem_xref.tsv", CHEM_XREF)
    return CHEM_XREF


def build(xref_path: Path) -> None:
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.executescript(
        """
        CREATE TABLE mnx_structure (
            mnx_id           TEXT PRIMARY KEY,
            smiles           TEXT,
            inchikey         TEXT,
            inchikey_block14 TEXT
        );
        CREATE TABLE bigg_mnx (
            bigg_id TEXT PRIMARY KEY,
            mnx_id  TEXT NOT NULL
        );
        CREATE TABLE xref_mnx (
            ns      TEXT NOT NULL,
            ext_id  TEXT NOT NULL,
            mnx_id  TEXT NOT NULL,
            PRIMARY KEY (ns, ext_id)
        );
        """
    )

    n_struct = 0
    rows = []
    with CHEM_PROP.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 9:
                continue
            mnx, ik, smi = p[0], p[7].strip(), p[8].strip()
            if not smi:
                continue
            blk = ik.split("-")[0] if ik else None
            rows.append((mnx, smi, ik or None, blk))
            if len(rows) >= 50000:
                conn.executemany(
                    "INSERT OR IGNORE INTO mnx_structure VALUES (?,?,?,?)", rows)
                n_struct += len(rows)
                rows.clear()
    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO mnx_structure VALUES (?,?,?,?)", rows)
        n_struct += len(rows)

    # {BIGG,KEGG,HMDB,LIPIDMAPS} -> MNX from chem_xref. MetaNetX source prefixes:
    pfx_map = {"biggm": "BIGG", "bigg.metabolite": "BIGG",
               "keggc": "KEGG", "kegg.compound": "KEGG",
               "hmdb": "HMDB", "lipidmaps": "LIPIDMAPS"}
    n_bigg = n_xref = 0
    bigg_rows, xref_rows = [], []
    with xref_path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 2 or ":" not in p[0]:
                continue
            pfx, ext = p[0].split(":", 1)
            ns = pfx_map.get(pfx.lower())
            if not ns:
                continue
            if ns == "BIGG":
                bigg_rows.append((ext, p[1]))
            xref_rows.append((ns, ext, p[1]))
            if len(xref_rows) >= 50000:
                conn.executemany("INSERT OR IGNORE INTO bigg_mnx VALUES (?,?)", bigg_rows)
                conn.executemany("INSERT OR IGNORE INTO xref_mnx VALUES (?,?,?)", xref_rows)
                n_bigg += len(bigg_rows); n_xref += len(xref_rows)
                bigg_rows.clear(); xref_rows.clear()
    if xref_rows:
        conn.executemany("INSERT OR IGNORE INTO bigg_mnx VALUES (?,?)", bigg_rows)
        conn.executemany("INSERT OR IGNORE INTO xref_mnx VALUES (?,?,?)", xref_rows)
        n_bigg += len(bigg_rows); n_xref += len(xref_rows)

    conn.execute(
        "CREATE INDEX idx_mnx_struct_block14 ON mnx_structure(inchikey_block14)")
    conn.commit()
    c1 = conn.execute("SELECT COUNT(*) FROM mnx_structure").fetchone()[0]
    c2 = conn.execute("SELECT COUNT(*) FROM bigg_mnx").fetchone()[0]
    c3 = conn.execute("SELECT COUNT(*) FROM xref_mnx").fetchone()[0]
    conn.close()
    print(f"  mnx_structure rows = {c1}")
    print(f"  bigg_mnx rows      = {c2}")
    print(f"  xref_mnx rows      = {c3}")
    print(f"  wrote {DB} ({DB.stat().st_size/1e6:.0f} MB)")


def main() -> int:
    print("V3 structure-index ETL")
    xref = ensure_sources()
    build(xref)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
