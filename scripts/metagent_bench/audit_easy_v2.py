#!/usr/bin/env python3
"""Audit MetAgent-Bench easy v2 for duplicates and schema-level issues."""

from __future__ import annotations

import json
import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_PATH = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v2.jsonl"
REPORT_DIR = ROOT / "reports/benchmark/metagent_bench_v2"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"{path}:{line_no}: expected object")
            rows.append(item)
    return rows


def metabolite_signature(task: dict[str, Any]) -> tuple[str, ...]:
    mets = task["input"]["differential_metabolites"]
    return tuple(sorted(f"{met['id_type']}:{met['id']}" for met in mets))


def pathway_signature(task: dict[str, Any]) -> str:
    pathway = task["ground_truth"]["perturbed_pathway"]
    return f"{pathway.get('ontology', '')}:{pathway.get('id', '')}:{pathway.get('name', '')}"


def validate_easy_task(task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if task.get("difficulty") != "easy":
        errors.append("difficulty is not easy")
    inp = task.get("input")
    if not isinstance(inp, dict):
        errors.append("input missing")
        return errors
    if inp.get("context") != {}:
        errors.append("easy task context is not empty object")
    mets = inp.get("differential_metabolites")
    if not isinstance(mets, list) or not mets:
        errors.append("differential_metabolites is empty or not list")
    else:
        seen = set()
        for index, met in enumerate(mets):
            if not isinstance(met, dict):
                errors.append(f"metabolite {index} is not object")
                continue
            if not met.get("id") or not met.get("id_type"):
                errors.append(f"metabolite {index} missing id/id_type")
            key = (met.get("id_type"), met.get("id"))
            if key in seen:
                errors.append(f"duplicate metabolite in task: {key}")
            seen.add(key)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--label", default="easy_v2")
    args = parser.parse_args()
    dataset_path = args.dataset if args.dataset.is_absolute() else ROOT / args.dataset
    tasks = read_jsonl(dataset_path)
    errors: list[dict[str, Any]] = []
    task_ids = Counter()
    sources = Counter()
    ontologies = Counter()
    id_types = Counter()
    licenses = Counter()
    source_id_pairs = Counter()
    signature_to_tasks: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
    metabolite_set_to_tasks: dict[tuple[str, ...], list[str]] = defaultdict(list)
    pathway_to_tasks: dict[str, list[str]] = defaultdict(list)
    cross_source_identical_metabolites = []
    met_counts = []

    for line_no, task in enumerate(tasks, start=1):
        task_id = task.get("task_id", "")
        task_ids[task_id] += 1
        task_errors = validate_easy_task(task)
        if task_errors:
            errors.append({"line": line_no, "task_id": task_id, "errors": task_errors})

        source = task["provenance"]["source"]
        sources[source] += 1
        licenses[task["provenance"]["license"]] += 1
        source_id_pairs[(source, task["provenance"]["source_id"])] += 1

        pathway_key = pathway_signature(task)
        ontologies[task["ground_truth"]["perturbed_pathway"]["ontology"]] += 1
        pathway_to_tasks[pathway_key].append(task_id)

        met_sig = metabolite_signature(task)
        signature_to_tasks[(pathway_key, met_sig)].append(task_id)
        metabolite_set_to_tasks[met_sig].append(task_id)
        met_counts.append(len(met_sig))
        for met in task["input"]["differential_metabolites"]:
            id_types[met["id_type"]] += 1

    duplicate_task_ids = sorted(task_id for task_id, count in task_ids.items() if count > 1)
    duplicate_source_ids = [
        {"source": source, "source_id": source_id, "count": count}
        for (source, source_id), count in sorted(source_id_pairs.items())
        if count > 1
    ]
    duplicate_exact_tasks = [
        {"pathway_and_metabolites": pathway_key, "task_ids": ids}
        for (pathway_key, _), ids in signature_to_tasks.items()
        if len(ids) > 1
    ]
    duplicate_metabolite_sets = [
        {"task_ids": ids, "count": len(ids)}
        for ids in metabolite_set_to_tasks.values()
        if len(ids) > 1
    ]
    for ids in metabolite_set_to_tasks.values():
        if len(ids) <= 1:
            continue
        id_to_source = {task["task_id"]: task["provenance"]["source"] for task in tasks if task["task_id"] in ids}
        if len(set(id_to_source.values())) > 1:
            cross_source_identical_metabolites.append({"task_ids": ids, "sources": id_to_source})

    summary = {
        "dataset": str(dataset_path),
        "tasks": len(tasks),
        "validation_errors": len(errors),
        "errors": errors[:50],
        "duplicate_task_ids": duplicate_task_ids,
        "duplicate_source_ids": duplicate_source_ids,
        "duplicate_exact_pathway_metabolite_tasks": duplicate_exact_tasks,
        "duplicate_metabolite_sets": duplicate_metabolite_sets,
        "cross_source_identical_metabolite_sets": cross_source_identical_metabolites,
        "sources": dict(sources),
        "pathway_ontologies": dict(ontologies),
        "metabolite_id_types": dict(id_types),
        "licenses": dict(licenses),
        "metabolites_per_task": {
            "min": min(met_counts) if met_counts else 0,
            "mean": round(sum(met_counts) / len(met_counts), 2) if met_counts else 0,
            "max": max(met_counts) if met_counts else 0,
        },
        "pathway_task_count_top10": dict(Counter({key: len(value) for key, value in pathway_to_tasks.items()}).most_common(10)),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / f"{args.label}_duplicate_audit.json"
    md_path = REPORT_DIR / f"{args.label}_duplicate_audit.md"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    )
    lines = [
        f"# {args.label} Duplicate Audit",
        "",
        f"- Dataset: `{dataset_path}`",
        f"- Tasks: {summary['tasks']}",
        f"- Validation errors: {summary['validation_errors']}",
        f"- Duplicate task IDs: {len(duplicate_task_ids)}",
        f"- Duplicate provenance source IDs: {len(duplicate_source_ids)}",
        f"- Duplicate exact pathway+metabolite tasks: {len(duplicate_exact_tasks)}",
        f"- Duplicate metabolite sets ignoring pathway: {len(duplicate_metabolite_sets)}",
        f"- Cross-source identical metabolite sets: {len(cross_source_identical_metabolites)}",
        f"- Metabolites per task: min={summary['metabolites_per_task']['min']}, mean={summary['metabolites_per_task']['mean']}, max={summary['metabolites_per_task']['max']}",
        "",
        "## Sources",
        "",
    ]
    for source, count in sorted(sources.items()):
        lines.append(f"- {source}: {count}")
    lines.extend(["", "## Pathway Ontologies", ""])
    for ontology, count in sorted(ontologies.items()):
        lines.append(f"- {ontology}: {count}")
    lines.extend(["", "## Metabolite ID Types", ""])
    for id_type, count in sorted(id_types.items()):
        lines.append(f"- {id_type}: {count}")
    lines.extend(["", "## Interpretation", ""])
    if errors or duplicate_task_ids or duplicate_exact_tasks or cross_source_identical_metabolites:
        lines.append("- Audit found issues that should be reviewed before release; see JSON report for details.")
    else:
        lines.append("- No schema errors, duplicate task IDs, exact duplicate tasks, or cross-source identical metabolite sets were found.")
    if duplicate_metabolite_sets:
        lines.append("- Some metabolite sets repeat across tasks ignoring pathway; review JSON if this count is non-zero.")
    md_path.write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if errors or duplicate_task_ids or duplicate_exact_tasks or cross_source_identical_metabolites:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
