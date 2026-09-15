from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROMPT_RATE_PER_MILLION = 0.30
COMPLETION_RATE_PER_MILLION = 1.20

W14 = {
    "uv_rate_pct": 44.25,
    "pathway_bridge_count": 54,
    "pathway_accuracy_pct": 85.7,
    "iter2_trigger_count": 0,
    "iter2_degraded_count": 0,
    "cost_usd": 6.83,
    "wall_human": "64.2 min",
}

W16 = {
    "uv_rate_pct": 47.67,
    "pathway_bridge_count": 51,
    "pathway_accuracy_pct": 81.0,
    "iter2_trigger_count": 0,
    "iter2_degraded_count": 0,
    "cost_usd": 7.0502,
    "wall_human": "47.9 min",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def compute_minimax_cost(prompt_tokens: int, completion_tokens: int) -> float:
    cost = (
        prompt_tokens / 1_000_000 * PROMPT_RATE_PER_MILLION
        + completion_tokens / 1_000_000 * COMPLETION_RATE_PER_MILLION
    )
    return round(cost, 4)


def compute_metrics(rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    uv_count = 0
    supported_count = 0
    unsupported_count = 0
    contradicted_count = 0
    claim_denominator = 0
    for row in rows:
        per_iter = row.get("per_iter") or []
        if not per_iter:
            continue
        final_idx = int(row.get("final_iter_idx") or 0)
        final_idx = max(0, min(final_idx, len(per_iter) - 1))
        final_iter = per_iter[final_idx]
        supported = int(final_iter.get("n_supported") or 0)
        unsupported = int(final_iter.get("n_unsupported") or 0)
        contradicted = int(final_iter.get("n_contradicted") or 0)
        uv = int(final_iter.get("n_unverifiable_v0") or 0)
        supported_count += supported
        unsupported_count += unsupported
        contradicted_count += contradicted
        uv_count += uv
        claim_denominator += supported + unsupported + contradicted + uv

    n_tasks = int(summary.get("n_tasks") or len(rows))
    pathway_bridge_count = sum(1 for row in rows if row.get("framework_signal_bridge_in_iters"))
    return {
        "n_tasks": n_tasks,
        "n_valid": int(summary.get("n_valid") or 0),
        "n_crash": int(summary.get("n_crash") or 0),
        "supported_count": supported_count,
        "unsupported_count": unsupported_count,
        "contradicted_count": contradicted_count,
        "uv_count": uv_count,
        "claim_denominator": claim_denominator,
        "uv_rate_pct": round(100.0 * uv_count / claim_denominator, 2) if claim_denominator else 0.0,
        "supported_rate_pct": round(100.0 * supported_count / claim_denominator, 2) if claim_denominator else 0.0,
        "pathway_bridge_count": pathway_bridge_count,
        "pathway_accuracy_pct": round(100.0 * pathway_bridge_count / n_tasks, 1) if n_tasks else 0.0,
        "iter2_trigger_count": int(summary.get("n_feedback_iter2") or 0),
        "iter2_degraded_count": int(summary.get("rollback_iter2_degraded") or 0),
        "wall_human": str(summary.get("wall_human") or "unknown"),
        "wall_seconds": float(summary.get("total_wall_seconds") or 0.0),
        "llm_calls": int((summary.get("token_usage") or {}).get("n_calls_total") or 0),
        "prompt_tokens": int((summary.get("token_usage") or {}).get("per_task_prompt_total") or 0),
        "completion_tokens": int((summary.get("token_usage") or {}).get("per_task_completion_total") or 0),
    }


def serialization_round_trip(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    round_tripped = json.loads(json.dumps(loaded, ensure_ascii=False, default=str))
    carriers = (
        (round_tripped.get("final_react_result") or {}).get("enrichment_carriers")
        or {}
    )
    return {
        "path": str(path),
        "present": "enrichment_carriers" in (round_tripped.get("final_react_result") or {}),
        "round_trip_ok": isinstance(carriers, dict),
        "carrier_keys": sorted(carriers.keys()),
    }


def hard_gates(metrics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "HG-5": {
            "target": "UV within +/-1pp of 44.25%",
            "observed": f"{metrics['uv_rate_pct']:.2f}%",
            "pass": abs(metrics["uv_rate_pct"] - 44.25) <= 1.0,
        },
        "HG-6": {
            "target": "Pathway >=84%",
            "observed": f"{metrics['pathway_bridge_count']} / {metrics['n_tasks']} = {metrics['pathway_accuracy_pct']:.1f}%",
            "pass": metrics["pathway_accuracy_pct"] >= 84.0,
        },
        "HG-7": {
            "target": "iter-2 deg = 0%",
            "observed": f"{metrics['iter2_trigger_count']} iter-2, {metrics['iter2_degraded_count']} degraded",
            "pass": metrics["iter2_trigger_count"] == 0 and metrics["iter2_degraded_count"] == 0,
        },
        "HG-8": {
            "target": "Cost <= $15",
            "observed": f"${metrics['cost_usd']:.4f}",
            "pass": metrics["cost_usd"] <= 15.0,
        },
    }


def render_summary(metrics: dict[str, Any], gates: dict[str, dict[str, Any]], serial: dict[str, Any]) -> str:
    lines = [
        "# W17 D4 Path X Post Schema Extend",
        "",
        "## Aggregate",
        "",
        f"- Tasks: {metrics['n_tasks']}.",
        f"- Crashes: {metrics['n_crash']}.",
        f"- Valid: {metrics['n_valid']}.",
        f"- Wall: {metrics['wall_human']}.",
        f"- LLM calls: {metrics['llm_calls']}.",
        f"- Prompt tokens: {metrics['prompt_tokens']:,}.",
        f"- Completion tokens: {metrics['completion_tokens']:,}.",
        f"- Cost: ${metrics['cost_usd']:.4f} using MiniMax rate ${PROMPT_RATE_PER_MILLION:.2f}/M prompt + ${COMPLETION_RATE_PER_MILLION:.2f}/M completion.",
        "",
        "## Metrics",
        "",
        "| Metric | W14 baseline | W16 D4 | W17 D4 | Target | Verdict |",
        "|---|---:|---:|---:|---:|---|",
        _metric_row("UV claim rate", f"{W14['uv_rate_pct']:.2f}%", f"{W16['uv_rate_pct']:.2f}%", f"{metrics['uv_rate_pct']:.2f}%", "43.25-45.25%", gates["HG-5"]["pass"]),
        _metric_row("UV count / denominator", "901 / 2036", "880 / 1846", f"{metrics['uv_count']} / {metrics['claim_denominator']}", "within +/-1pp", gates["HG-5"]["pass"]),
        _metric_row("Supported claim rate", "34.48%", "26.38%", f"{metrics['supported_rate_pct']:.2f}%", "report", True),
        _metric_row("Pathway bridge accuracy", "54 / 63 = 85.7%", "51 / 63 = 81.0%", f"{metrics['pathway_bridge_count']} / {metrics['n_tasks']} = {metrics['pathway_accuracy_pct']:.1f}%", ">=84%", gates["HG-6"]["pass"]),
        _metric_row("iter-2 trigger count", "0 / 63", "0 / 63", f"{metrics['iter2_trigger_count']} / {metrics['n_tasks']}", "0 / 63", gates["HG-7"]["pass"]),
        _metric_row("iter-2 degraded rollback", "0 / 63", "0 / 63", f"{metrics['iter2_degraded_count']} / {metrics['n_tasks']}", "0 / 63", gates["HG-7"]["pass"]),
        _metric_row("Cost", f"${W14['cost_usd']:.2f}", f"${W16['cost_usd']:.4f}", f"${metrics['cost_usd']:.4f}", "<= $15", gates["HG-8"]["pass"]),
        _metric_row("Wall", W14["wall_human"], W16["wall_human"], metrics["wall_human"], "report", True),
        "",
        "## Hard Gates",
        "",
        "| Gate | Target | Observed | Verdict |",
        "|---|---|---|---|",
    ]
    for gate, result in gates.items():
        lines.append(f"| {gate} | {result['target']} | {result['observed']} | {'PASS' if result['pass'] else 'FAIL'} |")
    lines.extend([
        "",
        "## Serialization Round-Trip Check",
        "",
        f"- File: `{serial['path']}`",
        f"- `enrichment_carriers` present: {serial['present']}",
        f"- Round-trip dict: {serial['round_trip_ok']}",
        f"- Carrier keys: {', '.join(serial['carrier_keys']) if serial['carrier_keys'] else '(empty)'}",
        "",
    ])
    return "\n".join(lines)


def _metric_row(name: str, w14: str, w16: str, w17: str, target: str, passed: bool) -> str:
    return f"| {name} | {w14} | {w16} | {w17} | {target} | {'PASS' if passed else 'FAIL'} |"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--full-dir", type=Path, required=True)
    parser.add_argument("--summary-md", type=Path, required=True)
    args = parser.parse_args()

    rows = read_jsonl(args.results)
    summary = json.loads(args.summary_json.read_text(encoding="utf-8"))
    metrics = compute_metrics(rows, summary)
    metrics["cost_usd"] = compute_minimax_cost(metrics["prompt_tokens"], metrics["completion_tokens"])
    gates = hard_gates(metrics)

    first_task = rows[0]["task_id"]
    serial = serialization_round_trip(args.full_dir / f"{first_task}.json")
    if not (serial["present"] and serial["round_trip_ok"]):
        gates["HG-serialization"] = {
            "target": "enrichment_carriers present and JSON round-trips",
            "observed": f"present={serial['present']} round_trip_ok={serial['round_trip_ok']}",
            "pass": False,
        }

    args.summary_md.write_text(render_summary(metrics, gates, serial), encoding="utf-8")
    print(json.dumps({"metrics": metrics, "gates": gates, "serialization": serial}, indent=2))
    return 0 if all(gate["pass"] for gate in gates.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
