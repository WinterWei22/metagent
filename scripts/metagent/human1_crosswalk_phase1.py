#!/usr/bin/env python3
"""Offline Phase 1 POC for Human1 metabolite crosswalk cascade.

This script does not modify production verifier behavior. It validates whether
Human1 MAM identifiers can be translated into tool-accepted IDs and produce
non-empty pathway enrichment results for a fixed 5-task pilot.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.llm_client import chat, set_log_path
from concord.wrappers.fella_wrapper import run_fella_rwr
from concord.wrappers.ramp_wrapper import run_ramp_enrichment
from verifier.helpers.llm_judge_prompt import LLM_JUDGE_SYSTEM_PROMPT


REFERENCE_TSV = ROOT / "data/reference/human_gem_metabolites.tsv"
BENCHMARK = ROOT / "data/benchmark/metagent_bench/metagent_bench.jsonl"
OUT_DIR = ROOT / "data/metagent/human1_crosswalk_phase1"
LLM_LOG = ROOT / "logs/concord/human1_crosswalk_phase1_judge.jsonl"
MINIMAX_KEY_FILE = ROOT.parent / "metagent_day1_v5/api_key_minimax.txt"
TASK_IDS = [
    "s4_cooke_2025_human1_group1",
    "s4_cooke_2025_human1_group3",
    "s4_cooke_2025_human1_group8",
    "s4_cooke_2025_human1_group100",
    "s4_cooke_2025_human1_group138",
]


@dataclass(frozen=True)
class CrosswalkHit:
    mam_id: str
    chosen_namespace: str
    chosen_id: str
    kegg_id: str = ""
    hmdb_id: str = ""
    chebi_id: str = ""
    pubchem_id: str = ""
    display_name: str = ""


def _clean_cell(value: str | None) -> str:
    if value is None:
        return ""
    value = value.strip()
    if value.lower() in {"nan", "none", "null"}:
        return ""
    return value


def _split_ids(value: str) -> list[str]:
    value = _clean_cell(value)
    if not value:
        return []
    parts = re.split(r"[;,|]\s*|\s+", value)
    return [p.strip() for p in parts if p.strip()]


def _with_ns(value: str, namespace: str) -> str:
    value = value.strip()
    if not value:
        return ""
    prefix = f"{namespace}:"
    return value if value.upper().startswith(prefix) else f"{prefix}{value}"


def load_crosswalk(path: Path = REFERENCE_TSV) -> dict[str, CrosswalkHit]:
    out: dict[str, CrosswalkHit] = {}
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            mam_id = _clean_cell(row.get("metsNoComp"))
            if not mam_id or mam_id in out:
                continue
            kegg = next(iter(_split_ids(row.get("metKEGGID", ""))), "")
            hmdb = next(iter(_split_ids(row.get("metHMDBID", ""))), "")
            chebi = next(iter(_split_ids(row.get("metChEBIID", ""))), "")
            pubchem = next(iter(_split_ids(row.get("metPubChemID", ""))), "")
            display = _clean_cell(row.get("metBiGGID")) or mam_id
            cascade = [
                ("KEGG", _with_ns(kegg, "KEGG") if kegg else ""),
                ("HMDB", _with_ns(hmdb, "HMDB") if hmdb else ""),
                ("CHEBI", _with_ns(chebi, "CHEBI") if chebi else ""),
                ("PUBCHEM", pubchem),
            ]
            chosen_ns, chosen_id = next(
                ((ns, value) for ns, value in cascade if value),
                ("", ""),
            )
            if not chosen_id:
                continue
            out[mam_id] = CrosswalkHit(
                mam_id=mam_id,
                chosen_namespace=chosen_ns,
                chosen_id=chosen_id,
                kegg_id=_with_ns(kegg, "KEGG") if kegg else "",
                hmdb_id=_with_ns(hmdb, "HMDB") if hmdb else "",
                chebi_id=_with_ns(chebi, "CHEBI") if chebi else "",
                pubchem_id=pubchem,
                display_name=display,
            )
    return out


def compound_ref(hit: CrosswalkHit) -> SimpleNamespace:
    primary_id = hit.chebi_id or hit.hmdb_id or hit.kegg_id or (
        f"PUBCHEM:{hit.pubchem_id}" if hit.pubchem_id else hit.mam_id
    )
    return SimpleNamespace(
        primary_id=primary_id,
        inchikey=f"HUMAN1-{hit.mam_id}",
        display_name=hit.display_name,
        chebi_id=hit.chebi_id or None,
        hmdb_id=hit.hmdb_id or None,
        kegg_compound_id=hit.kegg_id or None,
        pubchem_cid=hit.pubchem_id or None,
    )


def load_tasks() -> dict[str, dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    with BENCHMARK.open() as fh:
        for line in fh:
            obj = json.loads(line)
            if obj.get("task_id") in TASK_IDS:
                tasks[obj["task_id"]] = obj
    missing = [task_id for task_id in TASK_IDS if task_id not in tasks]
    if missing:
        raise RuntimeError(f"missing benchmark tasks: {missing}")
    return tasks


def top_ramp_pathways(raw: dict[str, Any]) -> list[dict[str, Any]]:
    report = raw.get("report")
    pathways = getattr(report, "top_pathways", None) if report is not None else None
    result: list[dict[str, Any]] = []
    for item in pathways or []:
        if hasattr(item, "__dict__"):
            result.append(dict(item.__dict__))
        elif isinstance(item, dict):
            result.append(item)
        else:
            result.append({"value": str(item)})
    return result


def top_fella_pathways(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return list(raw.get("raw") or [])


def pathway_name(item: dict[str, Any]) -> str:
    for key in [
        "pathway_name",
        "name",
        "pathway",
        "pathwayName",
        "description",
        "label",
    ]:
        value = item.get(key)
        if value:
            return str(value)
    return json.dumps(item, ensure_ascii=False)[:200]


def judge_pathway_match(*, task_id: str, gt_name: str, predicted_name: str) -> dict[str, Any]:
    prompt = (
        "Judge whether a pathway prediction semantically matches the Human1 ground truth pathway name.\n"
        "Return only JSON with verdict, confidence, evidence_pointer, rationale.\n"
        "verdict must be one of: SUPPORTED, CONTRADICTED, UNVERIFIABLE_V0, HEDGED.\n"
        "Use SUPPORTED when the predicted pathway name is the same pathway or a clearly equivalent subpathway/parent pathway.\n"
        "Use UNVERIFIABLE_V0 when the relationship cannot be established from names alone.\n"
        f"task_id: {task_id}\n"
        f"ground_truth_name: {gt_name}\n"
        f"predicted_pathway_name: {predicted_name}\n"
        'Output example: {"verdict":"SUPPORTED","confidence":0.91,"evidence_pointer":"predicted_pathway_name","rationale":"..."}'
    )
    raw = chat(
        [
            {"role": "system", "content": LLM_JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=600,
        provider="minimax",
        model="MiniMax-M2.7-highspeed",
        trace_id=f"human1.crosswalk.phase1.{task_id}",
        caller="scripts.metagent.human1_crosswalk_phase1",
        response_format={"type": "json_object"},
        max_retries=1,
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "verdict": "UNVERIFIABLE_V0",
            "confidence": 0.0,
            "evidence_pointer": "",
            "rationale": f"judge parse failed: {raw[:200]}",
        }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LLM_LOG.parent.mkdir(parents=True, exist_ok=True)
    set_log_path(LLM_LOG)
    os.environ.setdefault("METAGENT_LLM_PROVIDER", "minimax")
    os.environ.setdefault("METAGENT_MINIMAX_MODEL", "MiniMax-M2.7-highspeed")
    if not os.environ.get("MINIMAX_API_KEY") and MINIMAX_KEY_FILE.exists():
        os.environ["MINIMAX_API_KEY"] = MINIMAX_KEY_FILE.read_text(encoding="utf-8").strip()

    crosswalk = load_crosswalk()
    tasks = load_tasks()
    summary: list[dict[str, Any]] = []

    for task_id in TASK_IDS:
        task = tasks[task_id]
        gt = task["ground_truth"]["perturbed_pathway"]
        mam_ids = [m["id"] for m in task["input"]["differential_metabolites"]]
        hits = [crosswalk[mam_id] for mam_id in mam_ids if mam_id in crosswalk]
        refs = [compound_ref(hit) for hit in hits]
        ramp = run_ramp_enrichment(refs, top_n=10, id_type="kegg")
        fella = run_fella_rwr(refs, organism="hsa", timeout=90)
        ramp_paths = top_ramp_pathways(ramp)
        fella_paths = top_fella_pathways(fella)
        candidates = [
            {"source": "ramp", "name": pathway_name(p), "raw": p}
            for p in ramp_paths[:5]
        ] + [
            {"source": "fella", "name": pathway_name(p), "raw": p}
            for p in fella_paths[:5]
        ]
        # Deduplicate by lowercase name while preserving source order.
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for candidate in candidates:
            key = candidate["name"].lower()
            if key not in seen:
                seen.add(key)
                deduped.append(candidate)
        judged: list[dict[str, Any]] = []
        for candidate in deduped[:5]:
            judged.append({
                **candidate,
                "judge": judge_pathway_match(
                    task_id=task_id,
                    gt_name=gt["name"],
                    predicted_name=candidate["name"],
                ),
            })
        row = {
            "task_id": task_id,
            "ground_truth_id": gt["id"],
            "ground_truth_name": gt["name"],
            "n_mam": len(mam_ids),
            "n_crosswalked": len(hits),
            "crosswalk_rate": len(hits) / len(mam_ids) if mam_ids else 0.0,
            "namespace_counts": {
                ns: sum(1 for hit in hits if hit.chosen_namespace == ns)
                for ns in ["KEGG", "HMDB", "CHEBI", "PUBCHEM"]
            },
            "ramp_n_input": ramp.get("n_input"),
            "ramp_n_input_resolved": ramp.get("n_input_resolved"),
            "ramp_n_pathways": len(ramp_paths),
            "ramp_id_type_used": ramp.get("id_type_used"),
            "fella_n_input": fella.get("n_input"),
            "fella_n_input_resolved": fella.get("n_input_resolved"),
            "fella_n_pathways": len(fella_paths),
            "top_candidates": judged,
            "has_nonempty_enrichment": bool(ramp_paths or fella_paths),
            "has_supported_name_match": any(
                j.get("judge", {}).get("verdict") == "SUPPORTED" for j in judged
            ),
        }
        summary.append(row)
        (OUT_DIR / f"{task_id}.json").write_text(
            json.dumps(row, indent=2, ensure_ascii=False) + "\n"
        )

    gate_pass = any(r["has_nonempty_enrichment"] and r["has_supported_name_match"] for r in summary)
    result = {
        "task_ids": TASK_IDS,
        "gate_pass": gate_pass,
        "n_tasks": len(summary),
        "n_nonempty_enrichment": sum(1 for r in summary if r["has_nonempty_enrichment"]),
        "n_supported_name_match": sum(1 for r in summary if r["has_supported_name_match"]),
        "rows": summary,
    }
    (OUT_DIR / "phase1_summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    )
    with (OUT_DIR / "phase1_summary.md").open("w") as fh:
        fh.write("# Human1 crosswalk Phase 1 POC\n\n")
        fh.write(f"- Gate pass: `{gate_pass}`\n")
        fh.write(f"- Non-empty enrichment tasks: `{result['n_nonempty_enrichment']}/{len(summary)}`\n")
        fh.write(f"- Supported name-match tasks (loose): `{result['n_supported_name_match']}/{len(summary)}`\n\n")
        fh.write("| task_id | GT name | mapped | RaMP paths | FELLA paths | supported name-match (loose) |\n")
        fh.write("|---|---|---:|---:|---:|---:|\n")
        for row in summary:
            fh.write(
                f"| {row['task_id']} | {row['ground_truth_name']} | "
                f"{row['n_crosswalked']}/{row['n_mam']} | {row['ramp_n_pathways']} | "
                f"{row['fella_n_pathways']} | {row['has_supported_name_match']} |\n"
            )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
