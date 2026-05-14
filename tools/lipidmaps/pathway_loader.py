"""Load WikiPathways Lipids Portal pathway exports."""

from __future__ import annotations

import json
import re
from pathlib import Path


_LM_ID_RE = re.compile(r"\bLM[A-Z]{2}\d{8,}\b")


def _extract_lm_ids(entity: dict) -> set[str]:
    ids: set[str] = set()
    xref_source = (entity.get("xrefDataSource") or "").lower()
    xref_id = entity.get("xrefIdentifier") or ""
    if "lipid" in xref_source and xref_id.startswith("LM"):
        ids.add(xref_id)
    for item in entity.get("type") or []:
        if not isinstance(item, str):
            continue
        ids.update(_LM_ID_RE.findall(item))
    return ids


def _load_manifest(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("pathways"), list):
        return data["pathways"]
    if isinstance(data, list):
        return data
    raise ValueError(f"Unsupported pathway manifest shape: {path}")


def load_pathways(pathway_db_path: Path | str) -> dict[str, list[dict]]:
    """Load LM_ID -> lipid pathway records.

    ``pathway_db_path`` points to the manifest JSON produced from the
    WikiPathways Lipids Portal. Per-pathway JSON files are expected in a
    sibling ``wikipathways_json`` directory.
    """
    manifest_path = Path(pathway_db_path)
    pathways = _load_manifest(manifest_path)
    json_dir = manifest_path.parent / "wikipathways_json"
    out: dict[str, list[dict]] = {}
    seen_pathway_ids: set[str] = set()
    for item in pathways:
        pid = item.get("pathway_id") or item.get("id")
        if not pid:
            continue
        if pid in seen_pathway_ids:
            continue
        seen_pathway_ids.add(pid)
        fp = json_dir / f"{pid}.json"
        if not fp.is_file():
            continue
        data = json.loads(fp.read_text(encoding="utf-8"))
        meta = data.get("pathway") or {}
        if isinstance(meta.get("pathway"), dict):
            meta = meta["pathway"]
        name = item.get("name") or meta.get("name") or meta.get("displayName") or pid
        species = item.get("species") or meta.get("organism")
        version = meta.get("dataSourceVersion") or meta.get("pathwayVersion")
        lm_ids: set[str] = set()
        for entity in (data.get("entitiesById") or {}).values():
            if isinstance(entity, dict) and entity.get("wpType") == "Metabolite":
                lm_ids.update(_extract_lm_ids(entity))
        pathway_rec = {
            "id": f"lm_pathway:{pid}",
            "external_id": pid,
            "name": name,
            "source": "lipidmaps",
            "provider": "wikipathways_lipids_portal",
            "species": species,
            "version": version,
            "n_lipidmaps_compounds": len(lm_ids),
        }
        for lm_id in sorted(lm_ids):
            out.setdefault(lm_id, []).append(dict(pathway_rec))
    for records in out.values():
        records.sort(key=lambda r: (r["external_id"], r["name"]))
    return out
