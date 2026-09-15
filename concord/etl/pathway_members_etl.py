"""W7 D1.1 — pathway_members.sqlite ETL.

Builds the V2 metric dependency: for each subsystem-style pathway
present in the Cooke ground-truth label space (Human1 + Recon2.2),
emit the canonical ChEBI member set.

Chain:
  pathway_name → MAM(s) via simulatedPA `metabolite_pathways.tsv`
  MAM → ChEBI via Human-GEM `model/metabolites.tsv`

Schema:
  pathway_member(pathway_namespace, pathway_label_slug,
                 pathway_name, member_chebi_id, member_mam_id, source)
"""
from __future__ import annotations
import logging
import re
import sqlite3
from pathlib import Path

import pandas as pd

from concord.etl.cooke_etl import (
    build_id_table, _slug, DEFAULT_AUX_DIR,
)

logger = logging.getLogger(__name__)

DEFAULT_OUT = Path("data/concord/pathway_members.sqlite")
DEFAULT_HUMAN1_PATH = Path("/tmp/simulatedPA/data/Human1/r_input/metabolite_pathways.tsv")
DEFAULT_RECON2_PATH = Path("/tmp/simulatedPA/data/Recon2.2/r_input/metabolite_pathways.tsv")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pathway_member (
    pathway_namespace TEXT NOT NULL,
    pathway_label_slug TEXT NOT NULL,
    pathway_name TEXT NOT NULL,
    member_chebi_id TEXT NOT NULL,
    member_mam_id TEXT,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pathway_member_pn ON pathway_member(pathway_namespace, pathway_label_slug);
CREATE INDEX IF NOT EXISTS idx_pathway_member_ch ON pathway_member(member_chebi_id);
"""


def _build_recon2_id_table_from_simulatedpa(metab_dict_recon: Path) -> pd.DataFrame:
    """Recon2.2 metab_dict columns: ID (EX_<bigg>_e), Name, metabID (mam-style 'biomass')."""
    md = pd.read_csv(metab_dict_recon, sep="\t")
    return md.rename(columns={"ID": "ex_id", "Name": "display_name", "metabID": "mam"})


def _build_recon2_member_chain() -> pd.DataFrame:
    """Build Recon2.2 pathway → member chain via simulatedPA tables + MetaNetX BIGG bridge."""
    from concord.etl.cooke_etl import build_recon2_id_table
    bigg2chebi = build_recon2_id_table(Path("data/concord/metanetx.sqlite"))
    mp = pd.read_csv("/tmp/simulatedPA/data/Recon2.2/r_input/metabolite_pathways.tsv", sep="\t")
    # mp.metabolite is e.g. '10fthf5glu_c' / 'biomass_c' — just strip the
    # final compartment letter ``_[a-z]``. There is no EX_ prefix in this
    # file (the EX_ prefix is only in the zscore TSV).
    def _strip(s):
        s = str(s)
        m = re.match(r"^(.+?)_[a-z]$", s)
        return m.group(1) if m else s
    mp["bigg_met"] = mp["metabolite"].apply(_strip)
    mp["chebi_id"] = mp["bigg_met"].map(bigg2chebi)
    mp = mp[mp["chebi_id"].notna() & mp["subsystem"].notna()].copy()
    mp["chebi_norm"] = "CHEBI:" + mp["chebi_id"].astype(str)
    mp = mp.rename(columns={"subsystem": "pathway_name", "metabolite": "raw_id"})
    return mp[["pathway_name", "chebi_norm", "raw_id"]]


def _build_human1_member_chain() -> pd.DataFrame:
    """Human1 pathway_name → MAM → ChEBI chain."""
    hm = pd.read_csv(DEFAULT_AUX_DIR / "human_gem_metabolites.tsv", sep="\t")
    hm = hm.drop_duplicates("metsNoComp")
    chebi_re = re.compile(r"^CHEBI:\d+$")
    hm = hm[hm["metChEBIID"].astype(str).str.match(chebi_re)].copy()
    mp = pd.read_csv(DEFAULT_HUMAN1_PATH, sep="\t")

    # mp.metabolite = MAM00001c (with compartment); strip last lowercase letter
    def _strip_comp(s):
        m = re.match(r"^(MAM\d+)[a-z]?$", str(s))
        return m.group(1) if m else str(s)
    mp["mam"] = mp["metabolite"].apply(_strip_comp)
    chain = mp.merge(
        hm[["metsNoComp", "metChEBIID"]],
        left_on="mam", right_on="metsNoComp", how="inner",
    ).rename(columns={"subsystem": "pathway_name",
                       "metChEBIID": "chebi_norm",
                       "metabolite": "raw_id"})
    return chain[["pathway_name", "chebi_norm", "raw_id"]].drop_duplicates()


def build_pathway_members_sqlite(out_path: Path = DEFAULT_OUT) -> dict:
    """Write the pathway_members sqlite + return summary."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    h1 = _build_human1_member_chain()
    r2 = _build_recon2_member_chain()
    h1["source"] = "human1"
    r2["source"] = "recon2"
    h1["pathway_namespace"] = "HUMAN1"
    r2["pathway_namespace"] = "RECON2"
    h1["pathway_label_slug"] = h1["pathway_name"].apply(_slug)
    r2["pathway_label_slug"] = r2["pathway_name"].apply(_slug)
    rows = pd.concat([h1, r2], ignore_index=True).rename(
        columns={"chebi_norm": "member_chebi_id",
                  "raw_id": "member_mam_id"})

    conn = sqlite3.connect(out_path)
    conn.executescript(SCHEMA)
    rows[["pathway_namespace", "pathway_label_slug", "pathway_name",
           "member_chebi_id", "member_mam_id", "source"]].to_sql(
        "pathway_member", conn, if_exists="append", index=False,
    )
    conn.commit()
    conn.close()

    n_human1 = (rows["source"] == "human1").sum()
    n_recon2 = (rows["source"] == "recon2").sum()
    n_pw_h1 = h1["pathway_label_slug"].nunique()
    n_pw_r2 = r2["pathway_label_slug"].nunique()
    summary = {
        "out_path": str(out_path),
        "n_rows_total": int(len(rows)),
        "n_rows_human1": int(n_human1),
        "n_rows_recon2": int(n_recon2),
        "n_pathways_human1": int(n_pw_h1),
        "n_pathways_recon2": int(n_pw_r2),
    }
    return summary


def load_pathway_members(pathway_namespace: str, pathway_label_slug: str,
                          sqlite_path: Path = DEFAULT_OUT) -> set[str]:
    """Return the set of member CHEBI: IDs for the given pathway slug."""
    if not sqlite_path.exists():
        return set()
    conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT member_chebi_id FROM pathway_member "
            "WHERE pathway_namespace=? AND pathway_label_slug=?",
            (pathway_namespace, pathway_label_slug),
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    s = build_pathway_members_sqlite()
    print(s)
