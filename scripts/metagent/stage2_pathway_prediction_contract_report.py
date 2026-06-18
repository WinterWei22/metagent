#!/usr/bin/env python3
"""Report Stage2 pathway metrics from explicit pathway_prediction fields.

This script intentionally does not infer a prediction from claims[] order. Old
dumps without pathway_prediction are reported as degraded for pathway-level
metrics while claim-level metrics remain separate.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from concord.agent.pathway_prediction import compute_pathway_prediction_metrics


BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
DEFAULT_OUT_DIR = ROOT / "reports/reports_v2"


def load_benchmark(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                out[str(row["task_id"])] = row
    return out


def load_dump_payload(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    final = obj.get("final_react_result") or obj
    if "pathway_prediction" in final or "final_claims" in final:
        return {
            "pathway_prediction": final.get("pathway_prediction"),
            "narrative_text": final.get("final_narrative_text") or final.get("narrative_text") or "",
            "claims": final.get("final_claims") or final.get("claims") or [],
        }
    return obj


def ground_truth_for(task: dict[str, Any]) -> tuple[str, str, str]:
    gt = task.get("ground_truth", {}).get("perturbed_pathway", {})
    return str(gt.get("id") or ""), str(gt.get("name") or ""), str(gt.get("ontology") or "")


def stratum_for(task: dict[str, Any]) -> str:
    gt = task.get("ground_truth", {}).get("perturbed_pathway", {})
    ontology = str(gt.get("ontology") or "")
    if ontology in {"Human1", "Recon2.2"}:
        return ontology
    return str(task.get("stratum") or ontology or "other")


def ratio(num: int, den: int) -> float:
    return round(num / den, 6) if den else 0.0


def rows_for_dump_dir(dump_dir: Path, benchmark: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(dump_dir.glob("*.json")):
        task_id = path.stem
        task = benchmark.get(task_id)
        if not task:
            continue
        gt_id, gt_name, ontology = ground_truth_for(task)
        payload = load_dump_payload(path)
        metrics = compute_pathway_prediction_metrics(
            payload,
            ground_truth_pathway_id=gt_id,
            ground_truth_pathway_name=gt_name,
        )
        primary = (payload.get("pathway_prediction") or {}).get("primary") if isinstance(payload.get("pathway_prediction"), dict) else None
        rows.append(
            {
                "task_id": task_id,
                "stratum": stratum_for(task),
                "ontology": ontology,
                "gt_id": gt_id,
                "gt_name": gt_name,
                "primary_id": (primary or {}).get("pathway_id", "") if isinstance(primary, dict) else "",
                "primary_name": (primary or {}).get("pathway_name", "") if isinstance(primary, dict) else "",
                "pathway_prediction_ok": metrics["pathway_prediction_ok"],
                "pathway_prediction_error": metrics["pathway_prediction_error"],
                "primary_id_exact": metrics["primary_id_exact"],
                "primary_name_exact": metrics["primary_name_exact"],
                "primary_semantic_match": metrics["primary_semantic_match"],
                "topk_id_exact": metrics["topk_id_exact"],
                "topk_name_exact": metrics["topk_name_exact"],
                "topk_semantic_match": metrics["topk_semantic_match"],
                "abstain": metrics["abstain"],
            }
        )
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["stratum"])].append(row)
    out = {"overall": summarize_group(rows), "by_stratum": {}}
    for key, group_rows in sorted(grouped.items()):
        out["by_stratum"][key] = summarize_group(group_rows)
    return out


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    den = len(rows)
    return {
        "tasks": den,
        "pathway_prediction_ok": sum(1 for r in rows if r["pathway_prediction_ok"]),
        "primary_id_exact": sum(1 for r in rows if r["primary_id_exact"]),
        "primary_id_exact_rate": ratio(sum(1 for r in rows if r["primary_id_exact"]), den),
        "primary_name_exact": sum(1 for r in rows if r["primary_name_exact"]),
        "primary_name_exact_rate": ratio(sum(1 for r in rows if r["primary_name_exact"]), den),
        "primary_semantic_match": sum(1 for r in rows if r["primary_semantic_match"]),
        "primary_semantic_match_rate": ratio(sum(1 for r in rows if r["primary_semantic_match"]), den),
        "topk_id_exact": sum(1 for r in rows if r["topk_id_exact"]),
        "topk_id_exact_rate": ratio(sum(1 for r in rows if r["topk_id_exact"]), den),
        "topk_name_exact": sum(1 for r in rows if r["topk_name_exact"]),
        "topk_name_exact_rate": ratio(sum(1 for r in rows if r["topk_name_exact"]), den),
        "topk_semantic_match": sum(1 for r in rows if r["topk_semantic_match"]),
        "topk_semantic_match_rate": ratio(sum(1 for r in rows if r["topk_semantic_match"]), den),
        "abstain": sum(1 for r in rows if r["abstain"]),
        "abstain_rate": ratio(sum(1 for r in rows if r["abstain"]), den),
    }


def write_outputs(rows: list[dict[str, Any]], summary: dict[str, Any], out_dir: Path, stem: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{stem}.csv"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Stage2 Pathway Prediction Contract Metrics",
        "",
        "Metrics are computed from `pathway_prediction.primary` and alternatives only. Claim order is not used as a pathway prediction.",
        "",
        "| stratum | tasks | ok | primary ID-exact | primary name-exact | primary semantic | top-k ID-exact | top-k name-exact | top-k semantic | abstain |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    groups = {"overall": summary["overall"], **summary["by_stratum"]}
    for key, item in groups.items():
        lines.append(
            f"| {key} | {item['tasks']} | {item['pathway_prediction_ok']} | "
            f"{item['primary_id_exact_rate']:.2%} | {item['primary_name_exact_rate']:.2%} | "
            f"{item['primary_semantic_match_rate']:.2%} | {item['topk_id_exact_rate']:.2%} | "
            f"{item['topk_name_exact_rate']:.2%} | {item['topk_semantic_match_rate']:.2%} | "
            f"{item['abstain_rate']:.2%} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump-dir", required=True, type=Path)
    parser.add_argument("--benchmark", default=BENCHMARK, type=Path)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, type=Path)
    parser.add_argument("--stem", default="stage2_pathway_prediction_contract_metrics")
    args = parser.parse_args()
    rows = rows_for_dump_dir(args.dump_dir, load_benchmark(args.benchmark))
    write_outputs(rows, summarize(rows), args.out_dir, args.stem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
