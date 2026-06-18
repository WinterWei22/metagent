#!/usr/bin/env python3
"""Generate second-pass pathway_prediction objects from stored Stage2 dumps."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import common.llm_client as llm_client
from concord.agent.pathway_prediction import (
    compute_pathway_prediction_metrics,
    generate_pathway_prediction_second_pass,
)
from scripts.metagent.stage2_pathway_prediction_contract_report import (
    ground_truth_for,
    load_benchmark,
)
from scripts.metagent.w22_d8_easyv3_stratified import stratum_of


BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
DUMP_DIR = ROOT / "data/metagent/w22_easyv3_stratified_paired/path_x_full"
OUT_DIR = ROOT / "data/metagent/stage2_pathway_prediction_second_pass_full163"
REPORT_DIR = ROOT / "reports/reports_v2"
LLM_LOG = ROOT / "logs/concord/pathway_prediction_second_pass_full163.jsonl"
MINIMAX_KEY_FILE = ROOT.parent / "metagent_day1_v5/api_key_minimax.txt"
MODEL = "MiniMax-M2.7-highspeed"
PROVIDER = "minimax"
PROMPT_COST_PER_M = 0.30
COMPLETION_COST_PER_M = 1.20
TARGET_STRATA = {
    "sub6_hmdb_ramp_enrichment",
    "hmdb_ramp_pathway_membership",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "score"])
    parser.add_argument("--dump-dir", type=Path, default=DUMP_DIR)
    parser.add_argument("--benchmark", type=Path, default=BENCHMARK)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--llm-log", type=Path, default=LLM_LOG)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--cost-cap-usd", type=float, default=30.0)
    parser.add_argument("--stem", default="2026-06-18_stage2_pathway_prediction_second_pass_full163")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    args.llm_log.parent.mkdir(parents=True, exist_ok=True)

    benchmark = load_benchmark(args.benchmark)
    if args.command == "run":
        configure_llm(args.llm_log)
        return run_predictions(
            dump_dir=args.dump_dir,
            benchmark=benchmark,
            out_dir=args.out_dir,
            llm_log=args.llm_log,
            limit=args.limit,
            cost_cap_usd=args.cost_cap_usd,
        )
    write_scorecard(
        rows=score_rows(args.out_dir, benchmark),
        out_dir=args.report_dir,
        stem=args.stem,
        llm_log=args.llm_log,
    )
    return 0


def configure_llm(log_path: Path) -> None:
    if not os.environ.get("MINIMAX_API_KEY") and MINIMAX_KEY_FILE.exists():
        os.environ["MINIMAX_API_KEY"] = MINIMAX_KEY_FILE.read_text(encoding="utf-8").strip()
    os.environ["METAGENT_LLM_PROVIDER"] = PROVIDER
    os.environ["METAGENT_MINIMAX_MODEL"] = MODEL
    os.environ["METAGENT_LLM_LOG_PATH"] = str(log_path)
    llm_client.set_log_path(log_path)


def selected_tasks(benchmark: dict[str, dict[str, Any]]) -> list[str]:
    task_ids = [
        task_id
        for task_id, task in benchmark.items()
        if stratum_of(task) in TARGET_STRATA
    ]
    return sorted(task_ids)


def run_predictions(
    *,
    dump_dir: Path,
    benchmark: dict[str, dict[str, Any]],
    out_dir: Path,
    llm_log: Path,
    limit: int,
    cost_cap_usd: float,
) -> int:
    prediction_dir = out_dir / "predictions"
    prediction_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "prediction_manifest.jsonl"
    task_ids = selected_tasks(benchmark)
    if limit:
        task_ids = task_ids[:limit]

    for task_id in task_ids:
        if llm_cost(llm_log)["actual_cost_usd"] >= cost_cap_usd:
            print(f"STOP cost cap reached before {task_id}")
            return 2
        out_path = prediction_dir / f"{task_id}.json"
        if out_path.exists():
            continue
        dump_path = dump_dir / f"{task_id}.json"
        row = {
            "task_id": task_id,
            "ok": False,
            "error": "",
            "n_claims": 0,
            "primary_present": False,
            "abstain": False,
            "pathway_prediction": None,
        }
        if not dump_path.exists():
            row["error"] = "missing_dump"
            write_prediction(out_path, row, manifest_path)
            continue
        claims, narrative = load_fixed_claims(dump_path)
        row["n_claims"] = len(claims)
        if not claims:
            row["error"] = "no_claims"
            write_prediction(out_path, row, manifest_path)
            continue
        pred = generate_pathway_prediction_second_pass(
            claims=claims,
            narrative_text=narrative,
            chat_fn=llm_client.chat,
            model=MODEL,
            provider=PROVIDER,
            trace_id=f"stage2.pathway_prediction.second_pass.{task_id}",
        )
        if pred is None:
            row["error"] = "prediction_parse_failed"
        else:
            row["ok"] = True
            row["pathway_prediction"] = pred
            row["primary_present"] = bool(pred.get("primary"))
            row["abstain"] = bool(pred.get("abstain"))
        write_prediction(out_path, row, manifest_path)
        print(json.dumps({
            "task_id": task_id,
            "ok": row["ok"],
            "primary_present": row["primary_present"],
            "cost": llm_cost(llm_log)["actual_cost_usd"],
        }, ensure_ascii=False))
    return 0


def load_fixed_claims(path: Path) -> tuple[list[dict[str, Any]], str]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    final = obj.get("final_react_result") or obj
    claims = final.get("final_claims") or final.get("claims") or []
    narrative = final.get("final_narrative_text") or final.get("narrative_text") or ""
    if not claims and final.get("final_narrative_json"):
        try:
            payload = json.loads(final["final_narrative_json"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        claims = payload.get("claims") or []
        narrative = payload.get("narrative_text") or narrative
    return claims if isinstance(claims, list) else [], narrative


def write_prediction(out_path: Path, row: dict[str, Any], manifest_path: Path) -> None:
    out_path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with manifest_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def score_rows(out_dir: Path, benchmark: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task_id in selected_tasks(benchmark):
        task = benchmark[task_id]
        gt_id, gt_name, ontology = ground_truth_for(task)
        pred_path = out_dir / "predictions" / f"{task_id}.json"
        if pred_path.exists():
            pred_row = json.loads(pred_path.read_text(encoding="utf-8"))
        else:
            pred_row = {"pathway_prediction": None, "ok": False, "error": "missing_prediction"}
        payload = {
            "pathway_prediction": pred_row.get("pathway_prediction"),
            "claims": [{} for _ in range(int(pred_row.get("n_claims") or 0))],
            "narrative_text": "",
        }
        metrics = compute_pathway_prediction_metrics(
            payload,
            ground_truth_pathway_id=gt_id,
            ground_truth_pathway_name=gt_name,
        )
        prediction = pred_row.get("pathway_prediction")
        primary = prediction.get("primary") if isinstance(prediction, dict) else None
        rows.append({
            "task_id": task_id,
            "stratum": stratum_of(task),
            "ontology": ontology,
            "gt_id": gt_id,
            "gt_name": gt_name,
            "primary_id": (primary or {}).get("pathway_id", "") if isinstance(primary, dict) else "",
            "primary_name": (primary or {}).get("pathway_name", "") if isinstance(primary, dict) else "",
            "prediction_ok": bool(pred_row.get("ok")),
            "prediction_error": pred_row.get("error", ""),
            "n_claims": pred_row.get("n_claims", 0),
            "primary_id_exact": metrics["primary_id_exact"],
            "primary_name_exact": metrics["primary_name_exact"],
            "primary_semantic_match": metrics["primary_semantic_match"],
            "topk_id_exact": metrics["topk_id_exact"],
            "topk_name_exact": metrics["topk_name_exact"],
            "topk_semantic_match": metrics["topk_semantic_match"],
            "abstain": metrics["abstain"],
        })
    return rows


def write_scorecard(
    *,
    rows: list[dict[str, Any]],
    out_dir: Path,
    stem: str,
    llm_log: Path,
) -> None:
    summary = summarize(rows)
    summary["llm_cost"] = llm_cost(llm_log)
    csv_path = out_dir / f"{stem}.csv"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Stage2 Pathway Prediction Second-Pass Scorecard",
        "",
        "Main ReAct outputs are stored dumps; only the independent second-pass pathway selector was run.",
        "",
        f"LLM cost from `{llm_log}`: ${summary['llm_cost']['actual_cost_usd']:.6f}",
        "",
        "| stratum | tasks | prediction ok | primary ID-exact | primary name-exact | primary semantic | top-k ID-exact | top-k name-exact | top-k semantic | abstain |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    groups = {"overall": summary["overall"], **summary["by_stratum"]}
    for key, item in groups.items():
        lines.append(
            f"| {key} | {item['tasks']} | {item['prediction_ok']} | "
            f"{item['primary_id_exact_rate']:.2%} | {item['primary_name_exact_rate']:.2%} | "
            f"{item['primary_semantic_match_rate']:.2%} | {item['topk_id_exact_rate']:.2%} | "
            f"{item['topk_name_exact_rate']:.2%} | {item['topk_semantic_match_rate']:.2%} | "
            f"{item['abstain_rate']:.2%} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["stratum"])].append(row)
    return {
        "overall": summarize_group(rows),
        "by_stratum": {
            key: summarize_group(group_rows)
            for key, group_rows in sorted(grouped.items())
        },
    }


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    den = len(rows)
    return {
        "tasks": den,
        "prediction_ok": sum(1 for r in rows if r["prediction_ok"]),
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


def ratio(num: int, den: int) -> float:
    return round(num / den, 6) if den else 0.0


def llm_cost(log_path: Path) -> dict[str, Any]:
    prompt_tokens = 0
    completion_tokens = 0
    rows = 0
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            prompt_tokens += int(row.get("prompt_tokens") or 0)
            completion_tokens += int(row.get("completion_tokens") or 0)
    return {
        "log_path": str(log_path),
        "rows": rows,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "actual_cost_usd": round(
            prompt_tokens / 1_000_000 * PROMPT_COST_PER_M
            + completion_tokens / 1_000_000 * COMPLETION_COST_PER_M,
            6,
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
