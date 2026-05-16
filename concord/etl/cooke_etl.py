"""Cooke 2025 SAMBA Tier-A benchmark ETL (W6 D1.2).

Builds ConcordMet TierATask records from the Cooke et al. SAMBA z-score
matrix. Each row of the input TSV is a Human1/Recon2.2 reaction (MAR);
each column is one pathway-knockout perturbation. We:

  1. Filter to the *exchange* reaction subset (the only MARs that map to
     a single observable metabolite — Cooke's exometabolome design).
  2. 2-hop-join MAR → MAM (via simulatedPA `metab_dict.tsv`) → ChEBI /
     KEGG / HMDB (via Human-GEM `model/metabolites.tsv`).
  3. For each pathway column, threshold ``|z| > z_threshold`` to get the
     differential exchange-metabolite set; resolve each to a v0.3
     CompoundRef via ``concord.reconcile.id_resolve``.
  4. The column header (``group1``, ``group3``, …) is the ground-truth
     pathway label; ``pathway_dict.tsv`` maps each group to its
     subsystem name. We emit pathway IDs under the ``HUMAN1:`` namespace
     and defer KEGG / Reactome name-fuzzy-match to the Gate-2 metric
     phase (W6 D4).

Inputs are repo-local + small ChEBI sqlite; no external API calls.
"""
from __future__ import annotations
import dataclasses
import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from concord.lookup.chebi import ChebiLookup
from concord.reconcile.id_resolve import resolve_ids_to_compound_refs
from concord.schema.enrichment import CompoundRef

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TierATask:
    task_id: str
    perturbation_pathway_name: str
    perturbation_pathway_id: str            # always ``HUMAN1:<slug>`` for v1
    organism: str                           # "human1" / "recon2"
    z_threshold: float
    differential_metabolites: list[CompoundRef]
    differential_mars: list[str]            # raw MAR IDs used (debug / trace)
    z_scores: dict[str, float]              # MAR → z (for ranked methods)
    n_input_raw: int                        # n MARs with |z| > threshold (before mapping)
    n_input_resolved: int                   # len(differential_metabolites)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "perturbation_pathway_name": self.perturbation_pathway_name,
            "perturbation_pathway_id": self.perturbation_pathway_id,
            "organism": self.organism,
            "z_threshold": self.z_threshold,
            "differential_metabolites": [
                {"primary_id": r.primary_id, "inchikey": r.inchikey,
                 "chebi_id": r.chebi_id, "kegg_compound_id": r.kegg_compound_id,
                 "hmdb_id": r.hmdb_id, "display_name": r.display_name}
                for r in self.differential_metabolites
            ],
            "differential_mars": self.differential_mars,
            "z_scores": self.z_scores,
            "n_input_raw": self.n_input_raw,
            "n_input_resolved": self.n_input_resolved,
        }


def _slug(s: str) -> str:
    """Slugify a pathway name into a stable HUMAN1: tail."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()[:64]


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


def etl_cooke_tasks(
    zscore_tsv: Path,
    metab_dict_tsv: Path,
    human1_metabolites_tsv: Path,
    pathway_dict_tsv: Path,
    *,
    z_threshold: float = 2.0,
    organism: str = "human1",
    min_differential: int = 3,
    output_path: Path | None = None,
    chebi_lookup: ChebiLookup | None = None,
) -> list[TierATask]:
    """Run the Cooke z-score → TierATask ETL.

    Args:
        zscore_tsv:         Cooke Zenodo Human1_zscores.tsv (or Recon2.2)
        metab_dict_tsv:     simulatedPA data/Human1/r_input/metab_dict.tsv
        human1_metabolites_tsv: Human-GEM model/metabolites.tsv
        pathway_dict_tsv:   simulatedPA data/Human1/r_input/pathway_dict.tsv
        z_threshold:        |z| > threshold for differential metabolite (paper default 2.0)
        organism:           "human1" or "recon2"
        min_differential:   skip tasks with < this many resolved metabolites
        output_path:        if set, write one JSON record per task to this path
        chebi_lookup:       shared ChebiLookup (avoid re-opening sqlite)
    """
    if chebi_lookup is None:
        chebi_lookup = ChebiLookup()

    id_table = build_id_table(metab_dict_tsv, human1_metabolites_tsv)
    id_table = id_table[id_table["chebi_id"].notna()].copy()
    logger.info("ID table: %d exchange MARs with ChEBI", len(id_table))

    pathway_lookup = load_pathway_dict(pathway_dict_tsv)
    logger.info("Pathway dict: %d groups", len(pathway_lookup))

    z = pd.read_csv(zscore_tsv, sep="\t")
    z = z.rename(columns={"Metab": "mar"})
    z_join = z.merge(id_table, on="mar", how="inner")
    logger.info("z-score rows joined to ID table: %d / %d", len(z_join), len(z))

    chebi_to_numeric = lambda x: str(x).replace("CHEBI:", "")
    z_join["chebi_numeric"] = z_join["chebi_id"].apply(chebi_to_numeric)

    perturbation_cols = [c for c in z_join.columns if c.startswith("group")]
    logger.info("perturbation columns: %d", len(perturbation_cols))

    tasks: list[TierATask] = []
    skipped_under = 0
    skipped_no_pname = 0

    for col in perturbation_cols:
        sub = z_join[["mar", "chebi_numeric", "display_name", col]].dropna(subset=[col])
        diff = sub[sub[col].abs() > z_threshold]
        if len(diff) < min_differential:
            skipped_under += 1
            continue

        pname = pathway_lookup.get(col)
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

        z_scores = dict(zip(diff["mar"], diff[col].astype(float)))
        task = TierATask(
            task_id=f"cooke_{organism}_{col}",
            perturbation_pathway_name=pname,
            perturbation_pathway_id=f"HUMAN1:{_slug(pname)}",
            organism=organism,
            z_threshold=z_threshold,
            differential_metabolites=refs,
            differential_mars=diff["mar"].tolist(),
            z_scores=z_scores,
            n_input_raw=len(diff),
            n_input_resolved=len(refs),
        )
        tasks.append(task)

    logger.info(
        "produced %d tasks (skipped %d under threshold, %d missing pathway name)",
        len(tasks), skipped_under, skipped_no_pname,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w") as fout:
            for t in tasks:
                fout.write(json.dumps(t.to_dict()) + "\n")
        logger.info("wrote %d tasks → %s", len(tasks), output_path)

    return tasks
