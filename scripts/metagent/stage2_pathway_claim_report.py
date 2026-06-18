#!/usr/bin/env python3
"""Pathway-level and claim-level summary for current Stage2 artifacts."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
W22_DIR = ROOT / "data/metagent/w22_easyv3_stratified_paired"
HUMAN1_DIR = ROOT / "data/metagent/human1_crosswalk_full117"
OUT_DIR = ROOT / "reports/reports_v2"
DETAIL_CSV = OUT_DIR / "2026-06-17_stage2_pathway_pairing_per_task.csv"
SUMMARY_JSON = OUT_DIR / "2026-06-17_stage2_pathway_claim_metrics.json"
REPORT_MD = OUT_DIR / "2026-06-17_stage2_pathway_claim_report.md"


DATASETS = [
    {
        "dataset": "sub6_hmdb_ramp_enrichment",
        "label": "Sub-6 HMDB/RaMP enrichment",
        "source_dir": W22_DIR,
        "task_filter": lambda tid, gt, stratum: stratum == "sub6_hmdb_ramp_enrichment",
        "denominator_from_benchmark": False,
    },
    {
        "dataset": "hmdb_ramp_pathway_membership",
        "label": "HMDB/RaMP pathway membership",
        "source_dir": W22_DIR,
        "task_filter": lambda tid, gt, stratum: stratum == "hmdb_ramp_pathway_membership",
        "denominator_from_benchmark": False,
    },
    {
        "dataset": "human1_crosswalk",
        "label": "Human1 crosswalk",
        "source_dir": HUMAN1_DIR,
        "task_filter": lambda tid, gt, stratum: gt.get("ontology") == "Human1",
        "denominator_from_benchmark": True,
    },
]


STOPWORDS = {
    "and",
    "of",
    "the",
    "a",
    "an",
    "in",
    "by",
    "via",
    "pathway",
    "pathways",
    "metabolism",
    "metabolic",
    "biosynthesis",
    "synthesis",
    "degradation",
    "catabolism",
    "cycle",
    "system",
    "process",
    "human",
    "homo",
    "sapiens",
}

SYNONYM_GROUPS = [
    {"arachidonic", "eicosanoid", "prostaglandin", "leukotriene", "hpgds"},
    {"folate", "b9", "one", "carbon", "tetrahydrofolate"},
    {"tca", "tricarboxylic", "citrate", "glyoxylate", "dicarboxylate"},
    {"sphingolipid", "glycosphingolipid", "ceramide"},
    {"steroid", "sterol", "bile", "cholesterol"},
    {"fatty", "acid", "beta", "oxidation", "elongation", "unsaturated"},
    {"histidine", "histamine", "urocanate"},
    {"tyrosine", "catecholamine", "dopamine", "norepinephrine"},
    {"tryptophan", "serotonin", "melatonin", "kynurenine"},
    {"arginine", "proline", "urea", "ornithine"},
    {"glycine", "serine", "threonine"},
    {"valine", "leucine", "isoleucine", "branched"},
    {"vitamin", "riboflavin", "b2"},
    {"vitamin", "pyridoxine", "pyridoxal", "b6"},
    {"vitamin", "ascorbate", "aldarate", "c"},
    {"porphyrin", "heme", "haem", "tetrapyrrole"},
    {"starch", "sucrose", "galactose", "glycan"},
]


def load_benchmark() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with BENCHMARK.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            out[row["task_id"]] = row
    return out


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def norm_name(value: str | None) -> str:
    s = (value or "").lower()
    s = re.sub(r"\b(?:kegg|map|hsa|rno|mmu|wp|reactome|smpdb|mumm):?\d*\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def tokens(value: str | None) -> set[str]:
    return {tok for tok in norm_name(value).split() if tok not in STOPWORDS and len(tok) > 1}


def exact_name_match(gt_name: str, predicted_name: str) -> bool:
    return bool(norm_name(gt_name)) and norm_name(gt_name) == norm_name(predicted_name)


def semantic_name_match(gt_name: str, predicted_name: str) -> bool:
    gt_norm = norm_name(gt_name)
    pred_norm = norm_name(predicted_name)
    if not gt_norm or not pred_norm:
        return False
    if gt_norm == pred_norm:
        return True
    if len(gt_norm) >= 8 and gt_norm in pred_norm:
        return True
    if len(pred_norm) >= 8 and pred_norm in gt_norm:
        return True

    gt_tokens = tokens(gt_name)
    pred_tokens = tokens(predicted_name)
    if not gt_tokens or not pred_tokens:
        return False
    overlap = gt_tokens & pred_tokens
    if overlap and len(overlap) / min(len(gt_tokens), len(pred_tokens)) >= 0.67:
        return True
    if len(overlap) >= 2 and len(overlap) / len(gt_tokens | pred_tokens) >= 0.4:
        return True
    for group in SYNONYM_GROUPS:
        if gt_tokens & group and pred_tokens & group:
            return True
    return False


def pathway_names_from_claims(claims: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        claim_type = str(claim.get("claim_type") or "")
        name = str(claim.get("pathway_name") or "").strip()
        pid = str(claim.get("pathway_id") or "").strip()
        if not name and not pid:
            continue
        if "PATHWAY" not in claim_type and not name:
            continue
        value = name or pid
        key = norm_name(value)
        if key and key not in seen:
            seen.add(key)
            names.append(value)
    return names


def enrichment_pathway_names_from_claims(claims: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        claim_type = str(claim.get("claim_type") or "")
        if claim_type != "PATHWAY_ENRICHMENT":
            continue
        value = str(claim.get("pathway_name") or claim.get("pathway_id") or "").strip()
        key = norm_name(value)
        if key and key not in seen:
            seen.add(key)
            names.append(value)
    return names


def load_final_claims(source_dir: Path, task_id: str) -> list[dict[str, Any]]:
    path = source_dir / "path_x_full" / f"{task_id}.json"
    if not path.exists():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    final = obj.get("final_react_result") or {}
    claims = final.get("final_claims") or []
    return claims if isinstance(claims, list) else []


def status_task_ids(source_dir: Path) -> set[str]:
    out = set()
    status_dir = source_dir / "status"
    if not status_dir.exists():
        return out
    for path in status_dir.glob("*.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if obj.get("ok"):
            out.add(str(obj.get("task_id") or path.stem))
    return out


def stratum_by_task(source_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    rows_path = source_dir / "paired_per_task.csv"
    if not rows_path.exists():
        return out
    for row in read_csv(rows_path):
        out[row["task_id"]] = row.get("stratum") or ""
    return out


def supported_pathway_names(source_dir: Path, task_ids: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    path = source_dir / "paired_per_claim.csv"
    if not path.exists():
        return out
    for row in read_csv(path):
        if row.get("arm") != "structured_method_aware":
            continue
        if row.get("verdict") != "supported":
            continue
        tid = row["task_id"]
        if tid not in task_ids:
            continue
        value = (row.get("pathway_name") or row.get("pathway_id") or "").strip()
        key = norm_name(value)
        if key and key not in seen[tid]:
            seen[tid].add(key)
            out[tid].append(value)
    return out


def claim_metrics(source_dir: Path, task_ids: set[str]) -> dict[str, Any]:
    rows = [
        row
        for row in read_csv(source_dir / "paired_per_task.csv")
        if row.get("arm") == "structured_method_aware" and row.get("task_id") in task_ids
    ]
    sums = defaultdict(int)
    for row in rows:
        for key in [
            "source_claims",
            "verified_claims",
            "dropped",
            "supported",
            "contradicted",
            "unsupported",
            "needs_human_review",
            "uv",
            "method_aware_hits",
        ]:
            sums[key] += int(float(row.get(key) or 0))
    source = sums["source_claims"]
    verified = sums["verified_claims"]
    return {
        "tasks_with_claim_rows": len(rows),
        **sums,
        "supported_rate_honest": rate(sums["supported"], source),
        "uv_rate_honest": rate(sums["uv"], source),
        "unlanded_rate_honest": rate(sums["uv"] + sums["dropped"], source),
        "verified_rate": rate(verified, source),
        "method_aware_hit_rate_verified": rate(sums["method_aware_hits"], verified),
    }


def rate(num: int | float, den: int | float) -> float:
    return round(float(num) / float(den) * 100.0, 2) if den else 0.0


def pct_cell(num: int, den: int) -> str:
    return f"{num}/{den} ({rate(num, den):.2f}%)"


def summarize_dataset(spec: dict[str, Any], benchmark: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_dir = spec["source_dir"]
    strata = stratum_by_task(source_dir)
    ok_tasks = status_task_ids(source_dir)

    all_task_ids: list[str] = []
    for tid, task in benchmark.items():
        gt = task.get("ground_truth", {}).get("perturbed_pathway", {})
        stratum = strata.get(tid, "")
        if spec["task_filter"](tid, gt, stratum):
            all_task_ids.append(tid)

    if not spec["denominator_from_benchmark"]:
        all_task_ids = [tid for tid in all_task_ids if tid in ok_tasks]

    task_ids = set(all_task_ids)
    supported_by_task = supported_pathway_names(source_dir, task_ids)
    details: list[dict[str, Any]] = []
    counters = defaultdict(int)

    for tid in sorted(all_task_ids):
        task = benchmark[tid]
        gt = task.get("ground_truth", {}).get("perturbed_pathway", {})
        gt_name = str(gt.get("name") or "")
        gt_id = str(gt.get("id") or "")
        ok = tid in ok_tasks
        final_claims = load_final_claims(source_dir, tid) if ok else []
        all_names = pathway_names_from_claims(final_claims)
        enrichment_names = enrichment_pathway_names_from_claims(final_claims)
        top_name = enrichment_names[0] if enrichment_names else (all_names[0] if all_names else "")
        supported_names = supported_by_task.get(tid, [])

        row = {
            "dataset": spec["dataset"],
            "task_id": tid,
            "ok": ok,
            "ground_truth_id": gt_id,
            "ground_truth_name": gt_name,
            "top_output_pathway": top_name,
            "all_output_pathways": " | ".join(all_names),
            "supported_pathways": " | ".join(supported_names),
            "top_exact_name": exact_name_match(gt_name, top_name),
            "any_exact_name": any(exact_name_match(gt_name, name) for name in all_names),
            "supported_exact_name": any(exact_name_match(gt_name, name) for name in supported_names),
            "top_semantic_name": semantic_name_match(gt_name, top_name),
            "any_semantic_name": any(semantic_name_match(gt_name, name) for name in all_names),
            "supported_semantic_name": any(semantic_name_match(gt_name, name) for name in supported_names),
            "n_output_pathways": len(all_names),
            "n_supported_pathways": len(supported_names),
        }
        details.append(row)
        counters["tasks"] += 1
        counters["ok_tasks"] += int(ok)
        for key in [
            "top_exact_name",
            "any_exact_name",
            "supported_exact_name",
            "top_semantic_name",
            "any_semantic_name",
            "supported_semantic_name",
        ]:
            counters[key] += int(bool(row[key]))

    claims = claim_metrics(source_dir, task_ids)
    summary = {
        "dataset": spec["dataset"],
        "label": spec["label"],
        "tasks": counters["tasks"],
        "ok_tasks": counters["ok_tasks"],
        "pathway_level": {
            "top_exact_name": counters["top_exact_name"],
            "any_exact_name": counters["any_exact_name"],
            "supported_exact_name": counters["supported_exact_name"],
            "top_semantic_name": counters["top_semantic_name"],
            "any_semantic_name": counters["any_semantic_name"],
            "supported_semantic_name": counters["supported_semantic_name"],
        },
        "claim_level": claims,
    }
    return summary, details


def write_detail_csv(rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "dataset",
        "task_id",
        "ok",
        "ground_truth_id",
        "ground_truth_name",
        "top_output_pathway",
        "all_output_pathways",
        "supported_pathways",
        "top_exact_name",
        "any_exact_name",
        "supported_exact_name",
        "top_semantic_name",
        "any_semantic_name",
        "supported_semantic_name",
        "n_output_pathways",
        "n_supported_pathways",
    ]
    with DETAIL_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(summaries: list[dict[str, Any]]) -> None:
    lines = [
        "# Stage2 Pathway and Claim-Level Result Report",
        "",
        "- Date: `2026-06-17`",
        "- Project: `MetAgent`",
        "- Scope: current saved Stage2 artifacts; no model rerun.",
        "- Pathway exact metric: normalized pathway-name equality.",
        "- Pathway semantic metric: deterministic loose name/semantic pairing using token overlap, containment, and curated metabolism synonym groups. Treat it as a screening metric, not final manual accuracy.",
        "- Claim metric arm: `structured_method_aware`.",
        "",
        "## Inputs",
        "",
        "| Dataset | Source artifacts |",
        "|---|---|",
        "| Sub-6 HMDB/RaMP enrichment | `data/metagent/w22_easyv3_stratified_paired/` |",
        "| HMDB/RaMP pathway membership | `data/metagent/w22_easyv3_stratified_paired/` |",
        "| Human1 crosswalk | `data/metagent/human1_crosswalk_full117/` |",
        "",
        "## Pathway-Level Metrics",
        "",
        "| Dataset | Tasks | OK | Top-1 exact name | Any output exact name | Supported exact name | Top-1 semantic | Any output semantic | Supported semantic |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summaries:
        p = s["pathway_level"]
        den = s["tasks"]
        lines.append(
            f"| {s['label']} | {s['tasks']} | {s['ok_tasks']} | "
            f"{pct_cell(p['top_exact_name'], den)} | {pct_cell(p['any_exact_name'], den)} | "
            f"{pct_cell(p['supported_exact_name'], den)} | {pct_cell(p['top_semantic_name'], den)} | "
            f"{pct_cell(p['any_semantic_name'], den)} | {pct_cell(p['supported_semantic_name'], den)} |"
        )
    lines.extend(
        [
            "",
            "Interpretation:",
            "",
            "- `Top-1 exact name` asks whether the first pathway-enrichment style output has the same normalized name as the ground truth.",
            "- `Any output exact name` asks whether any pathway name in the model structured output exactly matches the ground truth name.",
            "- `Supported exact name` asks whether the verifier-supported pathway names contain the exact ground truth name.",
            "- Semantic columns are looser and capture cases such as subpathways or closely related pathway families. They need manual review before being called final accuracy.",
            "",
            "## Claim-Level Metrics",
            "",
            "| Dataset | Tasks with claim rows | Source claims | Verified | Dropped | Supported | Contradicted | Unsupported | UV | Supported honest | UV honest | Unlanded honest | Method-aware hit/verified |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for s in summaries:
        c = s["claim_level"]
        lines.append(
            f"| {s['label']} | {c['tasks_with_claim_rows']} | {c['source_claims']} | "
            f"{c['verified_claims']} | {c['dropped']} | {c['supported']} | {c['contradicted']} | "
            f"{c['unsupported']} | {c['uv']} | {c['supported_rate_honest']:.2f}% | "
            f"{c['uv_rate_honest']:.2f}% | {c['unlanded_rate_honest']:.2f}% | "
            f"{c['method_aware_hit_rate_verified']:.2f}% |"
        )
    lines.extend(
        [
            "",
            "## Notes and Caveats",
            "",
            "- The Human1 denominator remains 117; the two timeout tasks are retained as non-hit tasks for pathway metrics.",
            "- ID-exact pathway matching is intentionally not reported as the headline because the task ground truth and model/tool outputs often use different namespaces. Name-exact and semantic-name pairing are more informative for these saved artifacts.",
            "- Contradicted claim counts remain caveated by the known scientific-notation parsing issue from W22 D7; supported and UV are the more reliable claim-level readouts here.",
            "- `reports/reports_v2/2026-06-17_stage2_pathway_pairing_per_task.csv` contains the per-task ground truth, top output pathway, all output pathway names, and verifier-supported pathway names.",
            "",
            "## Reproduction",
            "",
            "```bash",
            "PYTHONPATH=. /home/weiwentao/miniconda3/bin/python scripts/metagent/stage2_pathway_claim_report.py",
            "```",
        ]
    )
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    benchmark = load_benchmark()
    summaries: list[dict[str, Any]] = []
    all_details: list[dict[str, Any]] = []
    for spec in DATASETS:
        summary, details = summarize_dataset(spec, benchmark)
        summaries.append(summary)
        all_details.extend(details)
    write_detail_csv(all_details)
    SUMMARY_JSON.write_text(json.dumps({"summaries": summaries}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report(summaries)
    print(f"wrote {REPORT_MD}")
    print(f"wrote {SUMMARY_JSON}")
    print(f"wrote {DETAIL_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
