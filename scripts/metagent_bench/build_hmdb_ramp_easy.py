#!/usr/bin/env python3
"""Build HMDB/RaMP constructed easy tasks for MetAgent-Bench easy v3."""

from __future__ import annotations

import json
import random
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RAMP_DB = Path("/data/weiwentao/llm_agent_metabolomics/ramp.sqlite")
EASY_V2_PATH = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v2.jsonl"
OUT_DIR = ROOT / "data/benchmark/metagent_bench_v2"
REPORT_DIR = ROOT / "reports/benchmark/metagent_bench_v2"

OUTPUT_TASKS = OUT_DIR / "tasks_hmdb_ramp_easy.jsonl"
OUTPUT_COMBINED = OUT_DIR / "metagent_bench_easy_v3.jsonl"

SEED = 20260528
TARGET_TASKS = 100
TASKS_PER_PATHWAY = 2
SIGNAL_COUNT = 8
NOISE_COUNT = 3
MIN_PATHWAY_MEMBERS = 8
MAX_PATHWAY_MEMBERS = 300
SOURCE_TASK_TARGETS = {"kegg": 40, "reactome": 40, "wiki": 20}
SOURCE_PRIORITY = {"kegg": 0, "reactome": 1, "wiki": 2}

GENERIC_OR_BAD_RE = re.compile(
    r"("
    r"^metabolism$|^disease$|^biochemical pathways|mapping of differential|"
    r"metabolism overview|signal transduction|immune system|developmental biology|"
    r"hemostasis|transport of small molecules|cellular responses|sensory perception|"
    r"disease|deficien|syndrome|disorder|aciduria|acidemia|cancer|tumou?r|"
    r"carcinoma|leukemia|drug|action pathway|infection|viral|bacterial"
    r")",
    re.IGNORECASE,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open() as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def normalize_source_id(source_id: str, id_type: str) -> str:
    value = source_id.split(":", 1)[1] if ":" in source_id else source_id
    if id_type.lower() == "hmdb" and not value.startswith("HMDB"):
        return value
    return value


def normalize_id_type(id_type: str) -> str:
    lowered = id_type.lower()
    if lowered == "hmdb":
        return "HMDB"
    if lowered == "kegg":
        return "KEGG"
    if lowered == "chebi":
        return "ChEBI"
    if lowered == "pubchem":
        return "PubChem"
    return id_type


def normalize_pathway_ontology(source_type: str) -> str:
    if source_type == "wiki":
        return "wikipathways"
    return source_type


def choose_best_ids(rows: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    by_ramp: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for ramp_id, source_id, id_type, name in rows:
        by_ramp[ramp_id].append((source_id, id_type, name))

    compounds = []
    for ramp_id, ids in by_ramp.items():
        ids.sort(key=lambda item: {"kegg": 0, "hmdb": 1, "chebi": 2, "pubchem": 3}.get(item[1].lower(), 9))
        source_id, id_type, name = ids[0]
        compounds.append(
            {
                "ramp_id": ramp_id,
                "id": normalize_source_id(source_id, id_type),
                "id_type": normalize_id_type(id_type),
                "name": name or ramp_id,
            }
        )
    compounds.sort(key=lambda item: (item["id_type"], item["id"], item["ramp_id"]))
    return compounds


def load_existing_pathway_ids(tasks: list[dict[str, Any]]) -> set[str]:
    ids = set()
    for task in tasks:
        pathway_id = task["ground_truth"]["perturbed_pathway"].get("id")
        if pathway_id:
            ids.add(pathway_id)
    return ids


def query_candidate_pathways(con: sqlite3.Connection, existing_pathway_ids: set[str]) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        select p.pathwayRampId, p.sourceId, p.type, p.pathwayName, count(distinct ahp.rampId) as n
        from pathway p
        join analytehaspathway ahp on p.pathwayRampId = ahp.pathwayRampId
        join analyte a on a.rampId = ahp.rampId and a.type = 'compound'
        where p.type in ('kegg', 'reactome', 'wiki')
        group by p.pathwayRampId
        having n between ? and ?
        """,
        (MIN_PATHWAY_MEMBERS, MAX_PATHWAY_MEMBERS),
    ).fetchall()
    candidates = []
    for pathway_id, source_id, source_type, name, member_count in rows:
        if pathway_id in existing_pathway_ids:
            continue
        if GENERIC_OR_BAD_RE.search(name or ""):
            continue
        candidates.append(
            {
                "pathway_id": pathway_id,
                "external_id": source_id,
                "source_type": source_type,
                "name": name,
                "member_count": member_count,
            }
        )
    candidates.sort(key=lambda row: (SOURCE_PRIORITY.get(row["source_type"], 99), row["name"], row["pathway_id"]))
    return candidates


def query_pathway_members(con: sqlite3.Connection, pathway_id: str) -> list[dict[str, str]]:
    rows = con.execute(
        """
        select distinct ahp.rampId, s.sourceId, s.IDtype, coalesce(s.commonName, a.common_name)
        from analytehaspathway ahp
        join analyte a on a.rampId = ahp.rampId and a.type = 'compound'
        join source s on s.rampId = ahp.rampId and s.geneOrCompound = 'compound'
        where ahp.pathwayRampId = ?
          and lower(s.IDtype) in ('kegg', 'hmdb', 'chebi', 'pubchem')
        """,
        (pathway_id,),
    ).fetchall()
    return choose_best_ids(rows)


def query_noise_pool(con: sqlite3.Connection) -> list[dict[str, str]]:
    rows = con.execute(
        """
        select distinct a.rampId, s.sourceId, s.IDtype, coalesce(s.commonName, a.common_name)
        from analyte a
        join source s on s.rampId = a.rampId and s.geneOrCompound = 'compound'
        where a.type = 'compound'
          and lower(s.IDtype) in ('kegg', 'hmdb')
          and s.pathwayCount > 0
        """
    ).fetchall()
    return choose_best_ids(rows)


def metabolites_from_compounds(compounds: list[dict[str, str]]) -> list[dict[str, str]]:
    metabolites = []
    seen = set()
    for compound in compounds:
        key = (compound["id_type"], compound["id"])
        if key in seen:
            continue
        seen.add(key)
        item = {"id": compound["id"], "id_type": compound["id_type"]}
        if compound.get("name"):
            item["name"] = compound["name"]
        metabolites.append(item)
    return metabolites


def select_pathways(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    tasks_by_source = Counter()
    pathways_by_source = Counter()
    for source_type, task_target in SOURCE_TASK_TARGETS.items():
        pathway_target = task_target // TASKS_PER_PATHWAY
        for candidate in [row for row in candidates if row["source_type"] == source_type]:
            if pathways_by_source[source_type] >= pathway_target:
                break
            selected.append(candidate)
            pathways_by_source[source_type] += 1
            tasks_by_source[source_type] += TASKS_PER_PATHWAY
    return selected


def build_tasks() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(SEED)
    existing_tasks = read_jsonl(EASY_V2_PATH)
    existing_pathway_ids = load_existing_pathway_ids(existing_tasks)

    con = sqlite3.connect(RAMP_DB)
    candidates = query_candidate_pathways(con, existing_pathway_ids)
    noise_pool = query_noise_pool(con)
    selected_pathways = select_pathways(candidates)

    tasks = []
    skipped = []
    for pathway in selected_pathways:
        members = query_pathway_members(con, pathway["pathway_id"])
        if len(members) < SIGNAL_COUNT:
            skipped.append({"pathway": pathway, "reason": "too_few_mappable_members", "mappable_members": len(members)})
            continue
        member_ramp_ids = {item["ramp_id"] for item in members}
        noise_candidates = [item for item in noise_pool if item["ramp_id"] not in member_ramp_ids]
        for replicate in range(TASKS_PER_PATHWAY):
            signal = rng.sample(members, SIGNAL_COUNT)
            noise = rng.sample(noise_candidates, NOISE_COUNT)
            mixed = signal + noise
            rng.shuffle(mixed)
            source_type = pathway["source_type"]
            task = {
                "task_id": f"hmdb_ramp_easy_{source_type}_{pathway['pathway_id']}_rep{replicate}",
                "difficulty": "easy",
                "input": {
                    "differential_metabolites": metabolites_from_compounds(mixed),
                    "context": {},
                },
                "ground_truth": {
                    "perturbed_pathway": {
                        "id": pathway["pathway_id"],
                        "ontology": f"RaMP:{normalize_pathway_ontology(source_type)}",
                        "name": pathway["name"],
                    },
                    "mechanism_evidence": {
                        "gene_or_enzyme": "not_applicable_constructed_enrichment",
                        "causal_chain": (
                            f"Constructed from {SIGNAL_COUNT} known RaMP pathway members plus "
                            f"{NOISE_COUNT} background compounds; pathway membership is the gold label, "
                            "not a real perturbation mechanism."
                        ),
                        "source_ref": (
                            f"RaMP SQLite {RAMP_DB}; pathway={pathway['pathway_id']}; "
                            f"external_id={pathway['external_id']}; source_type={source_type}; "
                            f"member_count={pathway['member_count']}; seed={SEED}; replicate={replicate}"
                        ),
                    },
                },
                "provenance": {
                    "source": "HMDB/RaMP constructed pathway-membership easy expansion",
                    "source_id": f"{pathway['pathway_id']}:{replicate}",
                    "license": "derived from local HMDB/RaMP SQLite snapshots; redistribution license requires project-level confirmation",
                },
            }
            tasks.append(task)
    con.close()
    summary = {
        "candidate_pathways": len(candidates),
        "selected_pathways": len(selected_pathways),
        "skipped_pathways": skipped,
        "noise_pool_size": len(noise_pool),
    }
    return tasks[:TARGET_TASKS], summary


def task_signature(task: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    pathway = task["ground_truth"]["perturbed_pathway"]
    pathway_key = f"{pathway['ontology']}:{pathway['id']}:{pathway['name']}"
    met_key = tuple(sorted(f"{met['id_type']}:{met['id']}" for met in task["input"]["differential_metabolites"]))
    return pathway_key, met_key


def audit(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    task_ids = Counter(task["task_id"] for task in tasks)
    sources = Counter(task["provenance"]["source"] for task in tasks)
    ontologies = Counter(task["ground_truth"]["perturbed_pathway"]["ontology"] for task in tasks)
    id_types = Counter()
    signatures = defaultdict(list)
    met_sets = defaultdict(list)
    errors = []
    for task in tasks:
        if task["difficulty"] != "easy":
            errors.append(f"{task['task_id']}: difficulty not easy")
        if task["input"].get("context") != {}:
            errors.append(f"{task['task_id']}: easy context not empty")
        if not task["input"].get("differential_metabolites"):
            errors.append(f"{task['task_id']}: empty metabolites")
        pathway_key, met_key = task_signature(task)
        signatures[(pathway_key, met_key)].append(task["task_id"])
        met_sets[met_key].append(task["task_id"])
        for met in task["input"]["differential_metabolites"]:
            if not met.get("id") or not met.get("id_type"):
                errors.append(f"{task['task_id']}: metabolite missing id/id_type")
            id_types[met["id_type"]] += 1
    return {
        "tasks": len(tasks),
        "validation_errors": len(errors),
        "errors": errors[:50],
        "duplicate_task_ids": sorted(task_id for task_id, count in task_ids.items() if count > 1),
        "duplicate_exact_pathway_metabolite_tasks": [
            ids for ids in signatures.values() if len(ids) > 1
        ],
        "duplicate_metabolite_sets": [ids for ids in met_sets.values() if len(ids) > 1],
        "sources": dict(sources),
        "pathway_ontologies": dict(ontologies),
        "metabolite_id_types": dict(id_types),
    }


def write_reports(new_tasks: list[dict[str, Any]], combined_tasks: list[dict[str, Any]], build_summary: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    new_audit = audit(new_tasks)
    combined_audit = audit(combined_tasks)
    payload = {"build_summary": build_summary, "hmdb_ramp_easy": new_audit, "combined_easy_v3": combined_audit}
    (REPORT_DIR / "hmdb_ramp_easy_build_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )
    lines = [
        "# HMDB/RaMP Easy Expansion Build Audit",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- RaMP DB: `{RAMP_DB}`",
        f"- Output tasks: `{OUTPUT_TASKS}`",
        f"- Output combined v3: `{OUTPUT_COMBINED}`",
        f"- Candidate pathways after filters: {build_summary['candidate_pathways']}",
        f"- Selected pathways: {build_summary['selected_pathways']}",
        f"- Noise pool compounds: {build_summary['noise_pool_size']}",
        "",
        "## New HMDB/RaMP Tasks",
        "",
        f"- Tasks: {new_audit['tasks']}",
        f"- Validation errors: {new_audit['validation_errors']}",
        f"- Duplicate task IDs: {len(new_audit['duplicate_task_ids'])}",
        f"- Duplicate exact pathway+metabolite tasks: {len(new_audit['duplicate_exact_pathway_metabolite_tasks'])}",
        f"- Duplicate metabolite sets ignoring pathway: {len(new_audit['duplicate_metabolite_sets'])}",
        "",
        "### New Task Ontologies",
        "",
    ]
    for ontology, count in sorted(new_audit["pathway_ontologies"].items()):
        lines.append(f"- {ontology}: {count}")
    lines.extend(["", "### New Task ID Types", ""])
    for id_type, count in sorted(new_audit["metabolite_id_types"].items()):
        lines.append(f"- {id_type}: {count}")
    lines.extend(
        [
            "",
            "## Combined Easy V3",
            "",
            f"- Tasks: {combined_audit['tasks']}",
            f"- Validation errors: {combined_audit['validation_errors']}",
            f"- Duplicate task IDs: {len(combined_audit['duplicate_task_ids'])}",
            f"- Duplicate exact pathway+metabolite tasks: {len(combined_audit['duplicate_exact_pathway_metabolite_tasks'])}",
            "",
            "### Combined Sources",
            "",
        ]
    )
    for source, count in sorted(combined_audit["sources"].items()):
        lines.append(f"- {source}: {count}")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- These are constructed pathway-membership tasks, not real perturbation tasks.",
            "- Pathways matching generic, disease, deficiency, syndrome, cancer, drug action, and broad top-level names were filtered.",
            "- Existing easy v2 RaMP pathway IDs were excluded before selecting new pathways.",
            "- Redistribution/license for HMDB/RaMP-derived tasks still requires project-level confirmation before public release.",
        ]
    )
    (REPORT_DIR / "hmdb_ramp_easy_build_audit.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    new_tasks, build_summary = build_tasks()
    easy_v2_tasks = read_jsonl(EASY_V2_PATH)
    combined_tasks = easy_v2_tasks + new_tasks
    new_audit = audit(new_tasks)
    combined_audit = audit(combined_tasks)
    blocking = []
    for label, item in [("new", new_audit), ("combined", combined_audit)]:
        if item["validation_errors"] or item["duplicate_task_ids"] or item["duplicate_exact_pathway_metabolite_tasks"]:
            blocking.append({label: item})
    if blocking:
        raise ValueError(json.dumps(blocking, ensure_ascii=False, indent=2))
    write_jsonl(OUTPUT_TASKS, new_tasks)
    write_jsonl(OUTPUT_COMBINED, combined_tasks)
    write_reports(new_tasks, combined_tasks, build_summary)
    print(
        json.dumps(
            {
                "new_tasks": len(new_tasks),
                "combined_easy_v3_tasks": len(combined_tasks),
                "new_audit": new_audit,
                "combined_audit": combined_audit,
                "build_summary": build_summary,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
