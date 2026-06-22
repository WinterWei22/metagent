#!/usr/bin/env python3
"""Full344 pathway scorecard with RateLimit contamination accounting."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from concord.agent.pathway_prediction import (
    compute_pathway_prediction_metrics,
    pathway_recall_metrics,
    driver_pr_metrics,
)


DEFAULT_OUT_DIR = ROOT / "data/metagent/full344_fullpipeline_eval"
DEFAULT_BENCHMARK = ROOT / "data/benchmark/metagent_bench_v2/metagent_bench_easy_v3.jsonl"
DEFAULT_REPORT_DIR = ROOT / "reports/reports_v2"
DEFAULT_RELEVANT_SIDECAR = ROOT / "data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json"
DEFAULT_GOLD_SIDECAR = ROOT / "data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json"
DEFAULT_RAMP_DB = Path("/data/weiwentao/llm_agent_metabolomics/ramp.sqlite")
PROMPT_COST_PER_M = 0.30
COMPLETION_COST_PER_M = 1.20


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--stem", default="2026-06-19_full344_pathway_scorecard")
    parser.add_argument("--validation-per-type", type=int, default=15)
    parser.add_argument("--llm-log", type=Path)
    parser.add_argument("--relevant-sidecar", type=Path, default=DEFAULT_RELEVANT_SIDECAR)
    parser.add_argument("--gold-sidecar", type=Path, default=DEFAULT_GOLD_SIDECAR)
    parser.add_argument("--ramp", type=Path, default=DEFAULT_RAMP_DB)
    args = parser.parse_args()

    relevant_sidecar = _load_json_file(args.relevant_sidecar)
    gold_sidecar = _load_json_file(args.gold_sidecar)
    ramp_conn = _open_ramp_conn(args.ramp)

    benchmark = load_benchmark(args.benchmark)
    rows = rows_for_full344(
        status_dir=args.out_dir / "status",
        dump_dir=args.out_dir / "path_x_full",
        benchmark=benchmark,
        relevant_sidecar=relevant_sidecar,
        gold_sidecar=gold_sidecar,
        ramp_conn=ramp_conn,
    )
    if ramp_conn is not None:
        ramp_conn.close()
    summary = summarize(rows)
    summary["llm_cost"] = llm_cost(args.llm_log or default_llm_log_path(args.out_dir))
    candidates = validation_candidates(rows, per_type=args.validation_per_type)
    write_outputs(rows, summary, candidates, args.report_dir, args.stem)
    return 0


def default_llm_log_path(out_dir: Path) -> Path:
    return ROOT / "logs/concord" / f"{out_dir.name}.jsonl"


def load_benchmark(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows[str(row["task_id"])] = row
    return rows


def rows_for_full344(
    *,
    status_dir: Path,
    dump_dir: Path,
    benchmark: dict[str, dict[str, Any]],
    relevant_sidecar: dict[str, Any] | None = None,
    gold_sidecar: dict[str, Any] | None = None,
    ramp_conn: Any = None,
) -> list[dict[str, Any]]:
    relevant_sidecar = relevant_sidecar or {}
    gold_sidecar = gold_sidecar or {}
    rows: list[dict[str, Any]] = []
    for status_path in sorted(status_dir.glob("*.json")):
        status = json.loads(status_path.read_text(encoding="utf-8"))
        task_id = str(status.get("task_id") or status_path.stem)
        task = benchmark.get(task_id, {})
        gt_id, gt_name, ontology = ground_truth_for(task)
        stratum = str(status.get("stratum") or stratum_for(task))
        dump_path = dump_dir / f"{task_id}.json"
        dump_text = dump_path.read_text(encoding="utf-8") if dump_path.exists() else ""
        dump = json.loads(dump_text) if dump_text else {}
        payload = pathway_payload(dump)
        metrics = compute_pathway_prediction_metrics(
            payload,
            ground_truth_pathway_id=gt_id,
            ground_truth_pathway_name=gt_name,
        )
        contamination_reason = contamination_reason_for(status, dump_text, dump)
        primary = payload_primary(payload)
        topk = payload_topk(payload)
        # Collect DRIVER_METABOLITE compound_ids from the dump's structured claims
        claims = payload.get("claims") or []
        driver_compound_ids = [
            str(c["compound_id"])
            for c in claims
            if isinstance(c, dict)
            and c.get("claim_type") == "DRIVER_METABOLITE"
            and c.get("compound_id")
        ]
        # Resolve to RAMP_C ids when ramp.sqlite is available
        driver_resolver_note = ""
        if ramp_conn is not None:
            from concord.agent.driver_gold import resolve_to_ramp_id
            driver_predicted_ramp_ids: set[str] = set()
            for cid in driver_compound_ids:
                resolved = resolve_to_ramp_id(ramp_conn, cid)
                if resolved:
                    driver_predicted_ramp_ids.add(resolved)
        else:
            driver_predicted_ramp_ids = set()
            if driver_compound_ids:
                driver_resolver_note = "driver_resolver_unavailable"
        prediction = payload.get("pathway_prediction") or {}
        recall_dr = recall_driver_row(
            task_id=task_id,
            prediction=prediction,
            driver_predicted_ramp_ids=driver_predicted_ramp_ids,
            relevant_sidecar=relevant_sidecar,
            gold_sidecar=gold_sidecar,
        )
        row: dict[str, Any] = {
            "task_id": task_id,
            "stratum": stratum,
            "ontology": ontology,
            "status_ok": bool(status.get("ok")),
            "contaminated": bool(contamination_reason),
            "contamination_reason": contamination_reason,
            "gt_id": gt_id,
            "gt_name": gt_name,
            "primary_id": primary.get("pathway_id", ""),
            "primary_name": primary.get("pathway_name", ""),
            "topk_ids": " | ".join(item.get("pathway_id", "") for item in topk),
            "topk_names": " | ".join(item.get("pathway_name", "") for item in topk),
            "n_claims": len(claims),
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
        row.update(recall_dr)
        if driver_resolver_note:
            row["driver_resolver_note"] = driver_resolver_note
        rows.append(row)
    return rows


def ground_truth_for(task: dict[str, Any]) -> tuple[str, str, str]:
    gt = task.get("ground_truth", {}).get("perturbed_pathway", {})
    return str(gt.get("id") or ""), str(gt.get("name") or ""), str(gt.get("ontology") or "")


def stratum_for(task: dict[str, Any]) -> str:
    ontology = str(task.get("ground_truth", {}).get("perturbed_pathway", {}).get("ontology") or "")
    if ontology == "Human1":
        return "human1"
    if ontology == "Recon2.2":
        return "recon22"
    if ontology.startswith("RaMP:"):
        return "hmdb_ramp"
    return "unknown"


def pathway_payload(dump: dict[str, Any]) -> dict[str, Any]:
    final = dump.get("final_react_result") or dump
    return {
        "pathway_prediction": final.get("pathway_prediction"),
        "narrative_text": final.get("final_narrative_text") or final.get("narrative_text") or "",
        "claims": final.get("final_claims") or final.get("claims") or [],
    }


def payload_primary(payload: dict[str, Any]) -> dict[str, Any]:
    prediction = payload.get("pathway_prediction")
    if not isinstance(prediction, dict):
        return {}
    primary = prediction.get("primary")
    return primary if isinstance(primary, dict) else {}


def payload_topk(payload: dict[str, Any]) -> list[dict[str, Any]]:
    prediction = payload.get("pathway_prediction")
    if not isinstance(prediction, dict):
        return []
    topk: list[dict[str, Any]] = []
    primary = prediction.get("primary")
    if isinstance(primary, dict):
        topk.append(primary)
    alternatives = prediction.get("alternatives")
    if isinstance(alternatives, list):
        topk.extend(item for item in alternatives if isinstance(item, dict))
    return topk


def contamination_reason_for(status: dict[str, Any], dump_text: str, dump: dict[str, Any]) -> str:
    combined = f"{status} {dump_text}"
    if "RateLimitError" in combined or "Token Plan" in combined or "用量上限" in combined:
        return "ratelimit"
    if not status.get("ok"):
        return str(status.get("invalid_reason") or "status_failed")
    final = dump.get("final_react_result") or dump
    if final.get("error") and "RateLimitError" in str(final.get("error")):
        return "ratelimit"
    return ""


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clean_rows = [row for row in rows if not row["contaminated"]]
    return {
        "all": summarize_scope(rows),
        "clean": summarize_scope(clean_rows),
        "contamination": contamination_summary(rows),
    }


def summarize_scope(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["stratum"])].append(row)
    return {
        "overall": summarize_group(rows),
        "by_stratum": {
            stratum: summarize_group(group_rows)
            for stratum, group_rows in sorted(grouped.items())
        },
    }


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    den = len(rows)
    # recall@k / mrr / hit@k averages over all rows that have the key
    recall_rows = [row for row in rows if "recall_at_k" in row]
    n_recall = len(recall_rows)
    recall_at_k_avg = round(sum(r["recall_at_k"] for r in recall_rows) / n_recall, 6) if n_recall else None
    mrr_avg = round(sum(r["mrr"] for r in recall_rows) / n_recall, 6) if n_recall else None
    hit_at_k_avg = round(sum(1 for r in recall_rows if r["hit_at_k"]) / n_recall, 6) if n_recall else None
    # driver P/R averages over rows where value is non-null
    dp_rows = [row for row in rows if row.get("driver_precision") is not None]
    dr_rows = [row for row in rows if row.get("driver_recall") is not None]
    dp_avg = round(sum(r["driver_precision"] for r in dp_rows) / len(dp_rows), 6) if dp_rows else None
    dr_avg = round(sum(r["driver_recall"] for r in dr_rows) / len(dr_rows), 6) if dr_rows else None
    return {
        "tasks": den,
        "pathway_prediction_ok": sum(1 for row in rows if row["pathway_prediction_ok"]),
        "pathway_prediction_ok_rate": ratio(sum(1 for row in rows if row["pathway_prediction_ok"]), den),
        "primary_id_exact": sum(1 for row in rows if row["primary_id_exact"]),
        "primary_id_exact_rate": ratio(sum(1 for row in rows if row["primary_id_exact"]), den),
        "primary_name_exact": sum(1 for row in rows if row["primary_name_exact"]),
        "primary_name_exact_rate": ratio(sum(1 for row in rows if row["primary_name_exact"]), den),
        "primary_semantic_match": sum(1 for row in rows if row["primary_semantic_match"]),
        "primary_semantic_match_rate": ratio(sum(1 for row in rows if row["primary_semantic_match"]), den),
        "topk_id_exact": sum(1 for row in rows if row["topk_id_exact"]),
        "topk_id_exact_rate": ratio(sum(1 for row in rows if row["topk_id_exact"]), den),
        "topk_name_exact": sum(1 for row in rows if row["topk_name_exact"]),
        "topk_name_exact_rate": ratio(sum(1 for row in rows if row["topk_name_exact"]), den),
        "topk_semantic_match": sum(1 for row in rows if row["topk_semantic_match"]),
        "topk_semantic_match_rate": ratio(sum(1 for row in rows if row["topk_semantic_match"]), den),
        "abstain": sum(1 for row in rows if row["abstain"]),
        "abstain_rate": ratio(sum(1 for row in rows if row["abstain"]), den),
        "recall_at_k": recall_at_k_avg,
        "mrr": mrr_avg,
        "hit_at_k": hit_at_k_avg,
        "driver_precision": dp_avg,
        "driver_recall": dr_avg,
    }


def contamination_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_stratum: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        reason = str(row.get("contamination_reason") or "clean")
        by_stratum[str(row["stratum"])][reason] += 1
    return {
        "overall": dict(Counter(str(row.get("contamination_reason") or "clean") for row in rows)),
        "by_stratum": {key: dict(value) for key, value in sorted(by_stratum.items())},
    }


def validation_candidates(rows: list[dict[str, Any]], *, per_type: int = 15) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for stratum in ("human1", "recon22", "hmdb_ramp"):
        clean = [row for row in rows if row["stratum"] == stratum and not row["contaminated"]]
        semantic = [row for row in clean if row["primary_semantic_match"] or row["topk_semantic_match"]]
        abstain = [row for row in clean if row["abstain"]]
        for label, group in (("semantic_match", semantic[:per_type]), ("abstain", abstain[:per_type])):
            for row in group:
                item = dict(row)
                item["validation_type"] = label
                item["rubric_verdict"] = "pending_manual_review"
                candidates.append(item)
    return candidates


def write_outputs(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    candidates: list[dict[str, Any]],
    report_dir: Path,
    stem: str,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    write_csv(report_dir / f"{stem}_rows.csv", rows)
    write_csv(report_dir / f"{stem}_validation_candidates.csv", candidates)
    (report_dir / f"{stem}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / f"{stem}.md").write_text(markdown_report(summary, candidates), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def markdown_report(summary: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    lines = [
        "# Full344 Pathway-Level Scorecard",
        "",
        "ID-exact and semantic metrics are reported separately. Semantic is the looser rubric-defined match.",
        "",
        f"LLM cost from JSONL: ${summary['llm_cost']['actual_cost_usd']:.6f}",
        "",
        "## Contamination",
        "",
        json.dumps(summary["contamination"], ensure_ascii=False, indent=2),
        "",
    ]
    for scope in ("all", "clean"):
        lines.extend([
            f"## {scope.title()} Denominator",
            "",
            "| stratum | tasks | prediction ok | primary ID-exact | primary name-exact | primary semantic | top-k ID-exact | top-k semantic | abstain |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        groups = {"overall": summary[scope]["overall"], **summary[scope]["by_stratum"]}
        for key, item in groups.items():
            lines.append(
                f"| {key} | {item['tasks']} | {item['pathway_prediction_ok_rate']:.2%} | "
                f"{item['primary_id_exact_rate']:.2%} | {item['primary_name_exact_rate']:.2%} | "
                f"{item['primary_semantic_match_rate']:.2%} | {item['topk_id_exact_rate']:.2%} | "
                f"{item['topk_semantic_match_rate']:.2%} | {item['abstain_rate']:.2%} |"
            )
        lines.append("")
    # recall@k + driver P/R block (clean denominator)
    lines.extend([
        "## Recall@k and Driver P/R (Clean Denominator)",
        "",
        "| stratum | tasks | recall@3 | hit@3 | MRR | driver P | driver R |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    clean_scope = summary["clean"]
    rd_groups = {"overall": clean_scope["overall"], **clean_scope["by_stratum"]}
    for key, item in rd_groups.items():
        def _fmt(v: Any) -> str:
            return f"{v:.4f}" if v is not None else "N/A"
        lines.append(
            f"| {key} | {item['tasks']} | {_fmt(item.get('recall_at_k'))} | "
            f"{_fmt(item.get('hit_at_k'))} | {_fmt(item.get('mrr'))} | "
            f"{_fmt(item.get('driver_precision'))} | {_fmt(item.get('driver_recall'))} |"
        )
    lines.append("")
    lines.extend([
        "## Validation Candidates",
        "",
        f"Rows selected for manual semantic/abstain review: {len(candidates)}",
        "",
    ])
    return "\n".join(lines) + "\n"


def _load_json_file(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _open_ramp_conn(path: Path) -> Any:
    if path.exists():
        import sqlite3
        return sqlite3.connect(str(path))
    return None


def _ordered_predicted_names(prediction: dict) -> list:
    entries = []
    primary = prediction.get("primary")
    if isinstance(primary, dict) and primary.get("pathway_name"):
        entries.append(primary["pathway_name"])
    for alt in prediction.get("alternatives") or []:
        if isinstance(alt, dict) and alt.get("pathway_name"):
            entries.append(alt["pathway_name"])
    return entries


def recall_driver_row(
    *,
    task_id: str,
    prediction: dict,
    driver_predicted_ramp_ids: set,
    relevant_sidecar: dict,
    gold_sidecar: dict,
    k: int = 3,
) -> dict:
    rel_entry = relevant_sidecar.get(task_id) or {}
    relevant_names = set(rel_entry.get("relevant_names") or [])
    recall = pathway_recall_metrics(
        _ordered_predicted_names(prediction), relevant_names, k=k
    )
    gold_entry = gold_sidecar.get(task_id, None)
    gold_ids = None if gold_entry is None else set(gold_entry.get("gold_ramp_ids") or [])
    driver = driver_pr_metrics(driver_predicted_ramp_ids, gold_ids)
    return {
        "recall_at_k": recall["recall_at_k"],
        "hit_at_k": recall["hit_at_k"],
        "mrr": recall["mrr"],
        "n_relevant": recall["n_relevant"],
        "driver_precision": None if driver is None else driver["precision"],
        "driver_recall": None if driver is None else driver["recall"],
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
