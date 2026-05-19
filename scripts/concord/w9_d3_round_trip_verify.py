"""W9 D3 — round-trip integration verify: 5-task × 5-wrapper table.

Runs the W8 D5 stratified sample's 5 tasks through each of the 5 PA
wrapper tools via the dispatcher (the D2-three-axis-fixed dispatcher,
not the LLM ReAct loop). For each (task, tool) cell captures:

  - envelope.ok / error / reason
  - envelope._n_pathways
  - first pathway's pathway_id + pathway_name (when present)
  - envelope size in bytes (for D5 LLM context-budget projection)

Per W9 D3 acceptance criteria:
  - 3/5 wrapper (ramp / psea / mummichog) should produce
    _n_pathways > 0 with correct namespace prefix on all 5 tasks.
  - 2/5 wrapper (sspa / fella) should xfail cleanly via D2c
    wrapper_runtime_error / wrapper_unavailable envelope — NOT
    intermittently ok / error.

Run via:
    PYTHONPATH=. python scripts/concord/w9_d3_round_trip_verify.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from concord.agent.tool_dispatcher import dispatch, reset_call_cache


_BENCHMARK = Path("data/benchmark/sub6/sub6b_mammalian_tasks_v3.jsonl")
_OUTPUT_JSON = Path("data/concord/w9_d3_verify/round_trip_table.json")

# Same stratified 5 from W8 D5 Path X
TASK_IDS: tuple[str, ...] = (
    "compound_only_enrich_mammalian_lm_pathway_WP167_seed3",
    "compound_only_enrich_mammalian_lm_pathway_WP167_seed7",
    "compound_only_enrich_mammalian_RAMP_P_000000421_seed1",
    "compound_only_enrich_mammalian_RAMP_P_000000141_seed0",
    "compound_only_enrich_mammalian_RAMP_P_000000398_seed0",
)

TOOL_NAMES: tuple[str, ...] = (
    "run_sspa_ora",
    "run_ramp_enrichment",
    "run_metaboanalystr_psea",
    "run_mummichog",
    "run_fella_rwr",
)


def _load_tasks(benchmark: Path, task_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    wanted = set(task_ids)
    out: list[dict[str, Any]] = []
    with benchmark.open() as f:
        for line in f:
            row = json.loads(line)
            if row.get("task_id") in wanted:
                out.append(row)
    found = {r["task_id"] for r in out}
    missing = wanted - found
    if missing:
        raise KeyError(f"benchmark missing task_ids: {sorted(missing)}")
    # Preserve the order in TASK_IDS for readable output
    by_id = {r["task_id"]: r for r in out}
    return [by_id[tid] for tid in task_ids]


def _summarise_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Compress an envelope to a one-line cell summary."""
    ok = envelope.get("ok", False)
    error = envelope.get("error")
    reason = envelope.get("reason")
    n_paths = envelope.get("_n_pathways", 0)
    first_pid = first_name = None
    if ok:
        result = envelope.get("result") or {}
        pathways = (result.get("pathways") or [])
        if pathways:
            first_pid = pathways[0].get("pathway_id")
            first_name = pathways[0].get("pathway_name")
    size_bytes = len(json.dumps(envelope, default=str))
    return {
        "ok": ok,
        "error": error,
        "reason_excerpt": (reason or "")[:80] if reason else None,
        "_n_pathways": n_paths,
        "first_pathway_id": first_pid,
        "first_pathway_name": first_name,
        "envelope_bytes": size_bytes,
    }


def _format_cell(s: dict[str, Any]) -> str:
    if s["ok"]:
        pid = s["first_pathway_id"] or "?"
        ns = pid.split(":", 1)[0] if pid and ":" in pid else "?"
        return f"ok / n={s['_n_pathways']:2d} / ns={ns:6s} / size={s['envelope_bytes']:5d}B"
    return f"🟡 {s['error'] or 'unknown'}: {(s['reason_excerpt'] or '')[:50]}"


def main() -> int:
    print(f"=== W9 D3 round-trip verify — {len(TASK_IDS)} tasks × {len(TOOL_NAMES)} wrappers ===")
    tasks = _load_tasks(_BENCHMARK, TASK_IDS)

    results: dict[str, dict[str, dict[str, Any]]] = {}
    overall_started = time.time()
    for task in tasks:
        tid = task["task_id"]
        diffs = task.get("differential_metabolites") or []
        # Extract KEGG IDs from differential metabolites (sub6b-v3 schema)
        compound_ids = [m["kegg_id"] for m in diffs if m.get("kegg_id")]
        gt = task.get("ground_truth_pathway") or {}
        print(f"\n=== {tid} ===")
        print(f"   gt: {gt.get('pathway_name')!r} ({gt.get('pathway_id')!r})")
        print(f"   n_input_kegg_ids: {len(compound_ids)}")
        results[tid] = {
            "gt_pathway_name": gt.get("pathway_name"),
            "gt_pathway_id": gt.get("pathway_id"),
            "gt_external_id": gt.get("external_id"),
            "n_input_kegg_ids": len(compound_ids),
            "compound_ids": compound_ids,
            "tools": {},
        }
        for tool_name in TOOL_NAMES:
            reset_call_cache()
            t0 = time.time()
            envelope = dispatch({
                "name": tool_name,
                "arguments": {"compound_ids": compound_ids, "top_n": 10},
            }).payload
            wall = time.time() - t0
            summary = _summarise_envelope(envelope)
            summary["wall_seconds"] = round(wall, 2)
            results[tid]["tools"][tool_name] = summary
            print(f"   {tool_name:30s} {_format_cell(summary)}  ({wall:5.1f}s)")
    overall_wall = time.time() - overall_started

    # Quick health-check summary
    print(f"\n=== aggregate (total wall {overall_wall:.1f}s) ===")
    counts = {t: {"ok": 0, "err": 0, "wrapper_unavailable": 0,
                   "wrapper_runtime_error": 0} for t in TOOL_NAMES}
    for tid, tres in results.items():
        for tn, s in tres["tools"].items():
            if s["ok"]:
                counts[tn]["ok"] += 1
            else:
                counts[tn]["err"] += 1
                e = s.get("error") or "?"
                if e in counts[tn]:
                    counts[tn][e] += 1
    for tn in TOOL_NAMES:
        c = counts[tn]
        print(f"  {tn:30s} ok={c['ok']}/5  unavail={c['wrapper_unavailable']}/5  runtime_err={c['wrapper_runtime_error']}/5")

    _OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_JSON.write_text(json.dumps({
        "tasks": results,
        "tool_aggregate_counts": counts,
        "total_wall_seconds": round(overall_wall, 2),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, indent=2, default=str))
    print(f"\n=> table saved {_OUTPUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
