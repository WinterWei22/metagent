"""Cooke 2025 SAMBA Tier-A benchmark ETL (W6 D1.2, refactored D1.5 for
3-cohort pre-registration).

Builds ConcordMet TierATask records from the Cooke et al. SAMBA z-score
matrix. Two GEM sources are supported:

  * Human1 — zscore rows are MAR (reaction) IDs; the exchange-reaction
    subset is 2-hop-joined MAR → MAM (via simulatedPA `metab_dict.tsv`)
    → ChEBI (via Human-GEM `model/metabolites.tsv`).
  * Recon2.2 — zscore rows are BIGG exchange-reaction IDs of the form
    ``EX_<metabolite>_<comp>``; the metabolite slug is joined directly
    to MetaNetX MNXref (BIGG → MNX → ChEBI).

For each pathway-perturbation column, threshold ``|z| > z_threshold``
to get the differential exchange-metabolite set; resolve each to a
v0.3 CompoundRef via ``concord.reconcile.id_resolve``.

W6 D1 emits three pre-registered cohorts (decision 2026-05-17):

  Cohort       GEM      z_threshold  min_diff  expected N
  PRIMARY      Human1   1.0          2         49
  SENS_A       Human1   2.0          3         19   (paper-canonical)
  SENS_B       Recon2.2 1.0          2         12   (GEM robustness)

Inputs are repo-local + small ChEBI sqlite + MetaNetX sqlite; no
external API calls.
"""
from __future__ import annotations
import dataclasses
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from concord.lookup.chebi import ChebiLookup
from concord.reconcile.id_resolve import resolve_ids_to_compound_refs
from concord.schema.enrichment import CompoundRef

logger = logging.getLogger(__name__)

# Default paths inside the worktree
DEFAULT_AUX_DIR = Path("data/concord/tier_a_cooke/aux")
DEFAULT_RAW_DIR = Path("data/concord/tier_a_cooke/raw")
DEFAULT_METANETX_SQLITE = Path("data/concord/metanetx.sqlite")

# Pre-registered cohort specs (W6 D1, 2026-05-17 decision)
COHORTS: dict[str, dict[str, Any]] = {
    "primary": {"gem": "human1", "z_threshold": 1.0, "min_differential": 2,
                "role": "Gate 2 primary"},
    "sens_a":  {"gem": "human1", "z_threshold": 2.0, "min_differential": 3,
                "role": "paper-canonical sensitivity"},
    "sens_b":  {"gem": "recon2", "z_threshold": 1.0, "min_differential": 2,
                "role": "GEM-choice sensitivity"},
}


@dataclasses.dataclass
class TierATask:
    task_id: str
    perturbation_pathway_name: str
    perturbation_pathway_id: str            # always ``HUMAN1:<slug>`` for v1
    organism: str                           # "human1" / "recon2"
    cohort: str                             # "primary" / "sens_a" / "sens_b"
    z_threshold: float
    differential_metabolites: list[CompoundRef]
    differential_raw_ids: list[str]         # raw MAR (human1) or BIGG (recon2) IDs
    z_scores: dict[str, float]              # raw_id → z (for ranked methods)
    n_input_raw: int                        # n IDs with |z| > threshold (before mapping)
    n_input_resolved: int                   # len(differential_metabolites)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "perturbation_pathway_name": self.perturbation_pathway_name,
            "perturbation_pathway_id": self.perturbation_pathway_id,
            "organism": self.organism,
            "cohort": self.cohort,
            "z_threshold": self.z_threshold,
            "differential_metabolites": [
                {"primary_id": r.primary_id, "inchikey": r.inchikey,
                 "chebi_id": r.chebi_id, "kegg_compound_id": r.kegg_compound_id,
                 "hmdb_id": r.hmdb_id, "display_name": r.display_name}
                for r in self.differential_metabolites
            ],
            "differential_raw_ids": self.differential_raw_ids,
            "z_scores": self.z_scores,
            "n_input_raw": self.n_input_raw,
            "n_input_resolved": self.n_input_resolved,
        }


def _slug(s: str) -> str:
    """Slugify a pathway name into a stable HUMAN1: tail."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()[:64]


def build_recon2_id_table(metanetx_sqlite: Path) -> dict[str, str]:
    """BIGG metabolite slug → ChEBI numeric str via MetaNetX.

    Recon2.2 zscore rows are ``EX_<bigg_met>_<comp>``. We strip prefix +
    compartment, then MNXref-bridge BIGG → MNX → ChEBI. ``MetaNetX`` has
    ~17 k BIGG entries which cover the Recon2.2 exchange-metabolite set.
    """
    conn = sqlite3.connect(f"file:{metanetx_sqlite}?mode=ro", uri=True)
    try:
        df_mnx = pd.read_sql(
            "SELECT mnx_id, external_id AS bigg_met FROM mnx_xref WHERE external_ns='BIGG'",
            conn,
        )
        df_che = pd.read_sql(
            "SELECT mnx_id, external_id AS chebi_id FROM mnx_xref WHERE external_ns='CHEBI'",
            conn,
        ).drop_duplicates("mnx_id")
    finally:
        conn.close()
    bridged = (df_mnx.merge(df_che, on="mnx_id", how="inner")
               .drop_duplicates("bigg_met"))
    return bridged.set_index("bigg_met")["chebi_id"].astype(str).to_dict()


def build_id_table(
    metab_dict_tsv: Path,
    human1_metabolites_tsv: Path,
) -> pd.DataFrame:
    """Build the MAR → (ChEBI, KEGG, HMDB, display_name) join table."""
    md = pd.read_csv(metab_dict_tsv, sep="\t")
    hm = pd.read_csv(human1_metabolites_tsv, sep="\t")
    hm_dedup = hm.drop_duplicates("metsNoComp", keep="first")
    joined = md.merge(
        hm_dedup[["metsNoComp", "metChEBIID", "metKEGGID", "metHMDBID"]],
        left_on="metabID", right_on="metsNoComp", how="left",
    )
    return joined.rename(columns={
        "ID": "mar", "Name": "display_name", "metabID": "mam",
        "metChEBIID": "chebi_id", "metKEGGID": "kegg_id",
        "metHMDBID": "hmdb_id",
    })[["mar", "mam", "display_name", "chebi_id", "kegg_id", "hmdb_id"]]


def load_pathway_dict(pathway_dict_tsv: Path) -> dict[str, str]:
    """group → pathway-name dict from simulatedPA r_input."""
    df = pd.read_csv(pathway_dict_tsv, sep="\t")
    return dict(zip(df["Group"], df["Pathway"]))


def _load_zscore_human1(
    zscore_tsv: Path,
    metab_dict_tsv: Path,
    human1_metabolites_tsv: Path,
) -> tuple[pd.DataFrame, list[str]]:
    """Read Human1 zscores + 2-hop join. Returns (joined_df, pert_cols).

    Filters to strictly ``CHEBI:<int>``-formatted IDs; the upstream
    Human-GEM ``metChEBIID`` column occasionally carries non-CHEBI
    glycan / drug codes (e.g. ``G00124``) which would crash the
    downstream ``ChebiLookup.normalize_chebi_id`` validator.
    """
    id_table = build_id_table(metab_dict_tsv, human1_metabolites_tsv)
    id_table = id_table[id_table["chebi_id"].notna()].copy()
    chebi_re = re.compile(r"^CHEBI:\d+$")
    id_table = id_table[id_table["chebi_id"].astype(str).str.match(chebi_re)].copy()
    z = pd.read_csv(zscore_tsv, sep="\t").rename(columns={"Metab": "raw_id"})
    z_join = z.merge(id_table, left_on="raw_id", right_on="mar", how="inner")
    z_join["chebi_numeric"] = z_join["chebi_id"].astype(str).str.replace("CHEBI:", "")
    pert_cols = [c for c in z_join.columns if c.startswith("group")]
    logger.info("Human1 join: %d rows; %d perturbation cols", len(z_join), len(pert_cols))
    return z_join, pert_cols


def _load_zscore_recon2(
    zscore_tsv: Path,
    metanetx_sqlite: Path,
) -> tuple[pd.DataFrame, list[str]]:
    """Read Recon2.2 zscores + BIGG → MNX → ChEBI bridge."""
    bigg2chebi = build_recon2_id_table(metanetx_sqlite)
    z = pd.read_csv(zscore_tsv, sep="\t").rename(columns={"Metab": "raw_id"})

    def _strip_ex(s: str) -> str | None:
        m = re.match(r"^EX_(.+?)(_[a-z])?$", str(s))
        return m.group(1) if m else None

    z["bigg_met"] = z["raw_id"].apply(_strip_ex)
    z["chebi_numeric"] = z["bigg_met"].map(bigg2chebi)
    z["display_name"] = z["bigg_met"]
    z_join = z[z["chebi_numeric"].notna()].copy()
    pert_cols = [c for c in z_join.columns if c.startswith("subsystem")]
    logger.info("Recon2.2 join: %d rows with ChEBI; %d perturbation cols",
                len(z_join), len(pert_cols))
    return z_join, pert_cols


def _recon2_perturbation_label(col: str) -> str:
    """Recon2.2 perturbation column = ``subsystemN``. The pathway-name
    mapping is not in the simulatedPA repo for Recon2.2 (R-input is
    Human1-only). Emit the raw column header as the label and rely on
    Gate-2 fuzzy-match (W6 D4) to bridge it to KEGG/Reactome names.
    Acceptable because Cooke's Recon2.2 subsystems are stable
    identifiers within the model."""
    return col


def etl_cooke_tasks(
    zscore_tsv: Path,
    *,
    gem: Literal["human1", "recon2"] = "human1",
    z_threshold: float = 2.0,
    min_differential: int = 3,
    cohort: str = "primary",
    metab_dict_tsv: Path | None = None,
    human1_metabolites_tsv: Path | None = None,
    pathway_dict_tsv: Path | None = None,
    metanetx_sqlite: Path = DEFAULT_METANETX_SQLITE,
    output_path: Path | None = None,
    chebi_lookup: ChebiLookup | None = None,
) -> list[TierATask]:
    """Run the Cooke z-score → TierATask ETL for one GEM/cohort.

    Args (Human1 only):
        metab_dict_tsv:         simulatedPA data/Human1/r_input/metab_dict.tsv
        human1_metabolites_tsv: Human-GEM model/metabolites.tsv
        pathway_dict_tsv:       simulatedPA data/Human1/r_input/pathway_dict.tsv

    Args (Recon2.2 only):
        metanetx_sqlite: pre-built MNXref sqlite from W4 D3

    Common:
        zscore_tsv:        Cooke Zenodo Human1_zscores.tsv or Recon2.2_zscores.tsv
        gem:               "human1" or "recon2"
        z_threshold:       |z| > threshold for differential metabolite
        min_differential:  skip tasks with < this many resolved metabolites
        cohort:            cohort label stored on each TierATask (primary / sens_a / sens_b)
        output_path:       if set, write one JSON record per task
        chebi_lookup:      shared ChebiLookup (avoid re-opening sqlite)
    """
    if chebi_lookup is None:
        chebi_lookup = ChebiLookup()

    if gem == "human1":
        if not (metab_dict_tsv and human1_metabolites_tsv and pathway_dict_tsv):
            raise ValueError("human1 ETL requires metab_dict_tsv + "
                              "human1_metabolites_tsv + pathway_dict_tsv")
        z_join, pert_cols = _load_zscore_human1(
            zscore_tsv, metab_dict_tsv, human1_metabolites_tsv,
        )
        pathway_lookup = load_pathway_dict(pathway_dict_tsv)
        label_fn = lambda col: pathway_lookup.get(col)
    elif gem == "recon2":
        z_join, pert_cols = _load_zscore_recon2(zscore_tsv, metanetx_sqlite)
        label_fn = _recon2_perturbation_label
    else:
        raise ValueError(f"unknown gem: {gem!r}")

    tasks: list[TierATask] = []
    skipped_under = 0
    skipped_no_pname = 0

    for col in pert_cols:
        sub = z_join[["raw_id", "chebi_numeric", "display_name", col]].dropna(subset=[col])
        diff = sub[sub[col].abs() > z_threshold]
        if len(diff) < min_differential:
            skipped_under += 1
            continue

        pname = label_fn(col)
        if not pname:
            skipped_no_pname += 1
            continue

        chebi_ids = diff["chebi_numeric"].drop_duplicates().tolist()
        refs, _ = resolve_ids_to_compound_refs(
            chebi_ids, source_namespace="CHEBI", chebi_lookup=chebi_lookup,
        )
        if len(refs) < min_differential:
            skipped_under += 1
            continue

        z_scores = dict(zip(diff["raw_id"], diff[col].astype(float)))
        task = TierATask(
            task_id=f"cooke_{gem}_{col}",
            perturbation_pathway_name=pname,
            perturbation_pathway_id=f"HUMAN1:{_slug(pname)}" if gem == "human1"
                                     else f"RECON2:{_slug(pname)}",
            organism=gem,
            cohort=cohort,
            z_threshold=z_threshold,
            differential_metabolites=refs,
            differential_raw_ids=diff["raw_id"].tolist(),
            z_scores=z_scores,
            n_input_raw=len(diff),
            n_input_resolved=len(refs),
        )
        tasks.append(task)

    logger.info(
        "[cohort=%s gem=%s z=%.1f min=%d] produced %d tasks "
        "(skipped %d under threshold, %d missing label)",
        cohort, gem, z_threshold, min_differential,
        len(tasks), skipped_under, skipped_no_pname,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w") as fout:
            for t in tasks:
                fout.write(json.dumps(t.to_dict()) + "\n")
        logger.info("wrote %d tasks → %s", len(tasks), output_path)

    return tasks


def run_all_cohorts(
    *,
    raw_dir: Path = DEFAULT_RAW_DIR,
    aux_dir: Path = DEFAULT_AUX_DIR,
    out_dir: Path = Path("data/concord/tier_a_cooke"),
    metanetx_sqlite: Path = DEFAULT_METANETX_SQLITE,
    chebi_lookup: ChebiLookup | None = None,
) -> dict[str, list[TierATask]]:
    """Run the three W6 D1 pre-registered cohorts.

    Outputs:
      ``out_dir/tasks_primary.jsonl``
      ``out_dir/tasks_sens_a.jsonl``
      ``out_dir/tasks_sens_b.jsonl``
    """
    if chebi_lookup is None:
        chebi_lookup = ChebiLookup()
    out: dict[str, list[TierATask]] = {}
    for cohort, cfg in COHORTS.items():
        gem = cfg["gem"]
        zscore_tsv = raw_dir / (
            "Human1_zscores.tsv" if gem == "human1" else "Recon2.2_zscores.tsv"
        )
        kwargs: dict[str, Any] = dict(
            zscore_tsv=zscore_tsv,
            gem=gem,
            z_threshold=cfg["z_threshold"],
            min_differential=cfg["min_differential"],
            cohort=cohort,
            output_path=out_dir / f"tasks_{cohort}.jsonl",
            chebi_lookup=chebi_lookup,
            metanetx_sqlite=metanetx_sqlite,
        )
        if gem == "human1":
            kwargs["metab_dict_tsv"] = aux_dir / "metab_dict_human1.tsv"
            kwargs["human1_metabolites_tsv"] = aux_dir / "human_gem_metabolites.tsv"
            kwargs["pathway_dict_tsv"] = aux_dir / "pathway_dict_human1.tsv"
        out[cohort] = etl_cooke_tasks(**kwargs)
    return out
