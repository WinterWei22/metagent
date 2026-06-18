#!/usr/bin/env python3
"""Convert Sub-6B mammalian enrichment tasks into MetAgent-Bench easy tasks."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SUB6_PATH = ROOT / "data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl"
S4_PATH = ROOT / "data/benchmark/metagent_bench/tasks_s4.jsonl"
OUT_DIR = ROOT / "data/benchmark/metagent_bench_v2"
REPORT_DIR = ROOT / "reports/benchmark/metagent_bench_v2"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(item)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def choose_compound_id(compound: dict[str, Any]) -> tuple[str, str]:
    kegg_id = (compound.get("kegg_id") or "").strip()
    if kegg_id:
        return kegg_id, "KEGG"
    hmdb_id = (compound.get("hmdb_id") or "").strip()
    if hmdb_id:
        return hmdb_id, "HMDB"
    pubchem_cid = compound.get("pubchem_cid")
    if pubchem_cid:
        return str(pubchem_cid), "PubChem"
    inchikey = (compound.get("inchikey") or compound.get("inchikey_first_block") or "").strip()
    if inchikey:
        return inchikey, "InChIKey"
    return "", ""


def convert_metabolites(compounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metabolites: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for compound in compounds:
        compound_id, id_type = choose_compound_id(compound)
        if not compound_id:
            continue
        key = (id_type, compound_id)
        if key in seen:
            continue
        seen.add(key)
        met = {"id": compound_id, "id_type": id_type}
        name = (compound.get("name") or "").strip()
        if name:
            met["name"] = name
        metabolites.append(met)
    return metabolites


def convert_task(task: dict[str, Any]) -> dict[str, Any]:
    pathway = task["ground_truth_pathway"]
    source = pathway.get("pathway_source") or "RaMP"
    signal = task.get("ground_truth_signal_compounds") or []
    noise = task.get("ground_truth_noise_compounds") or []
    source_ref = (
        "Sub-6B mammalian HMDB/RaMP constructed enrichment task; "
        f"signal_count={len(signal)}, noise_count={len(noise)}, "
        f"source_task_id={task['task_id']}"
    )
    return {
        "task_id": f"sub6_easy_{task['task_id']}",
        "difficulty": "easy",
        "input": {
            "differential_metabolites": convert_metabolites(task.get("differential_metabolites") or []),
            "context": {},
        },
        "ground_truth": {
            "perturbed_pathway": {
                "id": pathway["pathway_id"],
                "ontology": f"RaMP:{source}",
                "name": pathway["pathway_name"],
            },
            "mechanism_evidence": {
                "gene_or_enzyme": "not_applicable_constructed_enrichment",
                "causal_chain": (
                    "Sub-6 constructed this compound set from known pathway members plus noise compounds; "
                    "the pathway label is membership/enrichment-derived, not a real perturbation mechanism."
                ),
                "source_ref": source_ref,
            },
        },
        "provenance": {
            "source": "Sub-6 HMDB/RaMP mammalian constructed enrichment",
            "source_id": task["task_id"],
            "license": "derived from local HMDB/RaMP/Sub-6 benchmark snapshot; redistribution license requires project-level confirmation",
        },
    }


def validate_task(task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if task.get("difficulty") != "easy":
        errors.append("difficulty must be easy")
    inp = task.get("input")
    if not isinstance(inp, dict):
        errors.append("input missing")
        return errors
    if inp.get("context") != {}:
        errors.append("easy context must be empty object")
    mets = inp.get("differential_metabolites")
    if not isinstance(mets, list) or not mets:
        errors.append("differential_metabolites must be non-empty")
    else:
        for index, met in enumerate(mets):
            if not met.get("id") or not met.get("id_type"):
                errors.append(f"metabolite {index} missing id/id_type")
    pathway = task.get("ground_truth", {}).get("perturbed_pathway", {})
    if not pathway.get("id") or not pathway.get("ontology") or not pathway.get("name"):
        errors.append("ground_truth pathway incomplete")
    evidence = task.get("ground_truth", {}).get("mechanism_evidence", {})
    if not evidence.get("source_ref"):
        errors.append("mechanism_evidence.source_ref missing")
    provenance = task.get("provenance", {})
    if not provenance.get("source") or not provenance.get("source_id") or not provenance.get("license"):
        errors.append("provenance incomplete")
    return errors


def audit(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    errors = []
    task_ids = Counter()
    sources = Counter()
    ontologies = Counter()
    id_types = Counter()
    met_counts = []
    for line_no, task in enumerate(tasks, start=1):
        task_ids[task.get("task_id", "")] += 1
        task_errors = validate_task(task)
        if task_errors:
            errors.append({"line": line_no, "task_id": task.get("task_id"), "errors": task_errors})
        sources[task["provenance"]["source"]] += 1
        ontologies[task["ground_truth"]["perturbed_pathway"]["ontology"]] += 1
        mets = task["input"]["differential_metabolites"]
        met_counts.append(len(mets))
        for met in mets:
            id_types[met["id_type"]] += 1
    duplicate_task_ids = sorted(task_id for task_id, count in task_ids.items() if count > 1)
    return {
        "tasks": len(tasks),
        "validation_errors": len(errors),
        "errors": errors[:25],
        "duplicate_task_ids": duplicate_task_ids,
        "sources": dict(sources),
        "pathway_ontologies": dict(ontologies),
        "metabolite_id_types": dict(id_types),
        "metabolites_per_task": {
            "min": min(met_counts) if met_counts else 0,
            "mean": round(sum(met_counts) / len(met_counts), 2) if met_counts else 0,
            "max": max(met_counts) if met_counts else 0,
        },
    }


def write_report(sub6_tasks: list[dict[str, Any]], combined_tasks: list[dict[str, Any]]) -> None:
    sub6_audit = audit(sub6_tasks)
    combined_audit = audit(combined_tasks)
    (REPORT_DIR / "sub6_easy_conversion_audit.json").write_text(
        json.dumps({"sub6_easy": sub6_audit, "combined_easy_v2": combined_audit}, ensure_ascii=False, indent=2, sort_keys=True)
    )
    lines = [
        "# Sub-6 Easy Conversion Audit",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Input Sub-6 file: `{SUB6_PATH}`",
        f"- Output Sub-6 easy tasks: `{OUT_DIR / 'tasks_sub6_easy.jsonl'}`",
        f"- Output combined easy v2: `{OUT_DIR / 'metagent_bench_easy_v2.jsonl'}`",
        "",
        "## Sub-6 Converted Tasks",
        "",
        f"- Tasks: {sub6_audit['tasks']}",
        f"- Validation errors: {sub6_audit['validation_errors']}",
        f"- Duplicate task IDs: {len(sub6_audit['duplicate_task_ids'])}",
        f"- Metabolites per task: min={sub6_audit['metabolites_per_task']['min']}, mean={sub6_audit['metabolites_per_task']['mean']}, max={sub6_audit['metabolites_per_task']['max']}",
        "",
        "### Sub-6 Pathway Ontologies",
        "",
    ]
    for ontology, count in sorted(sub6_audit["pathway_ontologies"].items()):
        lines.append(f"- {ontology}: {count}")
    lines.extend(["", "### Sub-6 Metabolite ID Types", ""])
    for id_type, count in sorted(sub6_audit["metabolite_id_types"].items()):
        lines.append(f"- {id_type}: {count}")
    lines.extend(
        [
            "",
            "## Combined Easy V2",
            "",
            f"- Tasks: {combined_audit['tasks']}",
            f"- Validation errors: {combined_audit['validation_errors']}",
            f"- Duplicate task IDs: {len(combined_audit['duplicate_task_ids'])}",
            "",
            "### Sources",
            "",
        ]
    )
    for source, count in sorted(combined_audit["sources"].items()):
        lines.append(f"- {source}: {count}")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Sub-6 tasks are constructed enrichment-derived easy tasks, not real perturbation tasks.",
            "- Combined easy v2 now has two source families: S4 synthetic perturbation and Sub-6 HMDB/RaMP constructed enrichment.",
            "- License/provenance for HMDB/RaMP-derived redistribution still needs project-level confirmation before public release.",
        ]
    )
    (REPORT_DIR / "sub6_easy_conversion_audit.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    sub6_raw = read_jsonl(SUB6_PATH)
    sub6_tasks = [convert_task(task) for task in sub6_raw]
    s4_tasks = read_jsonl(S4_PATH)
    combined_tasks = s4_tasks + sub6_tasks

    sub6_audit = audit(sub6_tasks)
    combined_audit = audit(combined_tasks)
    if sub6_audit["validation_errors"] or sub6_audit["duplicate_task_ids"]:
        raise ValueError(json.dumps(sub6_audit, ensure_ascii=False, indent=2))
    if combined_audit["validation_errors"] or combined_audit["duplicate_task_ids"]:
        raise ValueError(json.dumps(combined_audit, ensure_ascii=False, indent=2))

    write_jsonl(OUT_DIR / "tasks_sub6_easy.jsonl", sub6_tasks)
    write_jsonl(OUT_DIR / "metagent_bench_easy_v2.jsonl", combined_tasks)
    write_report(sub6_tasks, combined_tasks)
    print(
        json.dumps(
            {
                "sub6_easy_tasks": len(sub6_tasks),
                "combined_easy_v2_tasks": len(combined_tasks),
                "sub6_audit": sub6_audit,
                "combined_audit": combined_audit,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
