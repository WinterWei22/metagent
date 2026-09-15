from __future__ import annotations

import csv
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_PATH = ROOT / "data/reference/human_gem_metabolites.tsv"
ENABLE_ENV = "METAGENT_ENABLE_HUMAN1_CROSSWALK"


@dataclass(frozen=True)
class Human1CrosswalkHit:
    mam_id: str
    chosen_namespace: str
    chosen_id: str
    kegg_id: str = ""
    hmdb_id: str = ""
    chebi_id: str = ""
    pubchem_id: str = ""
    display_name: str = ""


class Human1Crosswalk:
    def __init__(self, hits: dict[str, Human1CrosswalkHit]) -> None:
        self._hits = hits

    @classmethod
    def from_tsv(cls, path: str | Path = DEFAULT_REFERENCE_PATH) -> "Human1Crosswalk":
        hits: dict[str, Human1CrosswalkHit] = {}
        with Path(path).open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                mam_id = _clean_cell(row.get("metsNoComp"))
                if not mam_id or mam_id in hits:
                    continue
                kegg = _first_id(row.get("metKEGGID"))
                hmdb = _first_id(row.get("metHMDBID"))
                chebi = _first_id(row.get("metChEBIID"))
                pubchem = _first_id(row.get("metPubChemID"))
                cascade = [
                    ("KEGG", _with_namespace(kegg, "KEGG") if kegg else ""),
                    ("HMDB", _with_namespace(hmdb, "HMDB") if hmdb else ""),
                    ("CHEBI", _with_namespace(chebi, "CHEBI") if chebi else ""),
                    ("PUBCHEM", pubchem),
                ]
                chosen_namespace, chosen_id = next(
                    ((ns, value) for ns, value in cascade if value),
                    ("", ""),
                )
                if not chosen_id:
                    continue
                hits[mam_id] = Human1CrosswalkHit(
                    mam_id=mam_id,
                    chosen_namespace=chosen_namespace,
                    chosen_id=chosen_id,
                    kegg_id=_with_namespace(kegg, "KEGG") if kegg else "",
                    hmdb_id=_with_namespace(hmdb, "HMDB") if hmdb else "",
                    chebi_id=_with_namespace(chebi, "CHEBI") if chebi else "",
                    pubchem_id=pubchem,
                    display_name=_clean_cell(row.get("metBiGGID")) or mam_id,
                )
        return cls(hits)

    def resolve(self, mam_id: str) -> Human1CrosswalkHit | None:
        return self._hits.get(_strip_compartment(mam_id))


_CACHE: dict[Path, Human1Crosswalk] = {}


def apply_human1_crosswalk_to_task(
    task: dict[str, Any],
    *,
    reference_path: str | Path = DEFAULT_REFERENCE_PATH,
    enabled: bool | None = None,
) -> dict[str, Any]:
    if enabled is None:
        enabled = _env_enabled()
    if not enabled or not _is_human1_task(task):
        return task

    reference = Path(reference_path)
    crosswalk = _CACHE.get(reference)
    if crosswalk is None:
        crosswalk = Human1Crosswalk.from_tsv(reference)
        _CACHE[reference] = crosswalk

    original = list(task.get("differential_metabolites") or [])
    converted: list[dict[str, Any]] = []
    namespace_counts: Counter[str] = Counter({"KEGG": 0, "HMDB": 0, "CHEBI": 0, "PUBCHEM": 0})
    mapped = 0
    for metabolite in original:
        item = dict(metabolite)
        raw_id = str(item.get("id") or item.get("primary_id") or "")
        hit = crosswalk.resolve(raw_id)
        if hit is None:
            converted.append(item)
            continue
        mapped += 1
        namespace_counts[hit.chosen_namespace] += 1
        item["id"] = hit.chosen_id
        item["id_type"] = hit.chosen_namespace
        item["human1_original_id"] = raw_id
        item["human1_crosswalk_namespace"] = hit.chosen_namespace
        item["human1_crosswalk_id"] = hit.chosen_id
        if hit.display_name and not item.get("name"):
            item["name"] = hit.display_name
        converted.append(item)

    out = dict(task)
    out["differential_metabolites"] = converted
    out["human1_crosswalk"] = {
        "enabled": True,
        "reference_path": str(reference),
        "n_input": len(original),
        "n_mapped": mapped,
        "n_unmapped": len(original) - mapped,
        "namespace_counts": dict(namespace_counts),
    }
    return out


def _is_human1_task(task: dict[str, Any]) -> bool:
    gt = task.get("ground_truth_pathway") or {}
    ontology = str(gt.get("ontology") or gt.get("pathway_ontology") or "")
    if ontology.lower() == "human1":
        return True
    for metabolite in task.get("differential_metabolites") or []:
        if str(metabolite.get("id_type") or "").lower() == "human1":
            return ontology == "" or ontology.lower() == "human1"
    return False


def _env_enabled() -> bool:
    return os.environ.get(ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _clean_cell(value: str | None) -> str:
    if value is None:
        return ""
    value = value.strip()
    return "" if value.lower() in {"", "nan", "none", "null"} else value


def _first_id(value: str | None) -> str:
    value = _clean_cell(value)
    if not value:
        return ""
    parts = re.split(r"[;,|]\s*|\s+", value)
    return next((part.strip() for part in parts if part.strip()), "")


def _with_namespace(value: str, namespace: str) -> str:
    value = value.strip()
    prefix = f"{namespace}:"
    return value if value.upper().startswith(prefix) else f"{prefix}{value}"


def _strip_compartment(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"MAM\d+[a-z]", value):
        return value[:-1]
    return value


__all__ = [
    "ENABLE_ENV",
    "Human1Crosswalk",
    "Human1CrosswalkHit",
    "apply_human1_crosswalk_to_task",
]
