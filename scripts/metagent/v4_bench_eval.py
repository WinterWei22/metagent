"""V4 benchmark evaluation driver — SMILES/name input (no database IDs).

Runs MetAgent Stage 2 on metagent_bench_easy_v4.jsonl where each metabolite
is identified only by name + SMILES + InChIKey (no KEGG/HMDB IDs exposed).
The agent must resolve structure → database IDs itself via lookup_chebi or
by passing InChIKey strings directly to PA tools (which already support it).

Key difference from v3_bench_eval.py:
  - Input format: {name, smiles?, inchikey?} — no id/id_type
  - No 2A ID enrichment step (IDs were stripped at benchmark generation time)
  - render_metabolite_line shows SMILES + InChIKey instead of KEGG ID

Usage:
    MINIMAX_API_KEY=<key> METAGENT_LLM_PROVIDER=minimax \\
    PYTHONPATH=. python scripts/metagent/v4_bench_eval.py \\
        --stratum hmdb_ramp --limit 10 \\
        --out data/metagent/v4_bench_eval
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_KEY_FILE = Path(__file__).resolve().parents[3] / "metagent_day1_v5/api_key_minimax.txt"


def _bootstrap_llm_env() -> None:
    if not os.environ.get("MINIMAX_API_KEY") and _KEY_FILE.exists():
        os.environ["MINIMAX_API_KEY"] = _KEY_FILE.read_text(encoding="utf-8").strip()
    if not os.environ.get("METAGENT_LLM_PROVIDER"):
        if os.environ.get("MINIMAX_API_KEY"):
            os.environ["METAGENT_LLM_PROVIDER"] = "minimax"
        elif os.environ.get("METAGENT_OPENAI_API_KEY"):
            os.environ["METAGENT_LLM_PROVIDER"] = "openai"


_bootstrap_llm_env()

from common.llm_client import chat_with_tools as _llm_chat
from verifier.helpers.judge_cost_cap import reset_run_level_tracker
from verifier.agent import verify_sub6 as _b1_verify_sub6
from concord.agent.react_runner import ConcordReactRunner

_BENCHMARK = Path("data/benchmark/metagent_bench_v2/metagent_bench_easy_v4.jsonl")
_TRACE_PREFIX = "v4_bench_eval"
_write_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)


def _stratum_of_task_id(task_id: str) -> str:
    if "human1" in task_id:
        return "human1"
    if "recon2" in task_id:
        return "recon22"
    if "sub6_easy" in task_id:
        return "sub6"
    return "hmdb_ramp"


def _normalize_task(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert v4 task to runner-compatible format.

    v4 metabolites already have {name, smiles?, inchikey?} — no ID enrichment
    needed.  We pass them through as-is; render_metabolite_line will show
    SMILES + InChIKey in the LLM prompt.
    """
    return {
        "task_id": raw["task_id"],
        "differential_metabolites": raw.get("input", {}).get("differential_metabolites", []),
        # Preserve ground_truth + input so the v4 verifier adapter can run:
        # _is_v4_task detects task["ground_truth"]["perturbed_pathway"], and
        # v4_task_to_subsix_source_report reads that plus
        # task["input"]["differential_metabolites"]. Without these the runner
        # falls back to the v3 adapter and every task fails with a
        # SubsixSourceReport ValidationError. _strip_task_for_llm strips the
        # task down to {task_id, differential_metabolites} before the LLM sees
        # it, so ground_truth never leaks into the agent prompt.
        "ground_truth": raw.get("ground_truth", {}),
        "input": raw.get("input", {}),
    }


def _write_status(status_dir: Path, task_id: str, row: dict[str, Any]) -> None:
    (status_dir / f"{task_id}.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def _make_status(
    task: dict[str, Any],
    fb: Any | None,
    *,
    wall: float,
    crash_msg: str | None = None,
) -> dict[str, Any]:
    task_id = task.get("task_id", "unknown")
    stratum = _stratum_of_task_id(task_id)
    row: dict[str, Any] = {
        "task_id": task_id,
        "stratum": stratum,
        "ok": crash_msg is None,
        "wall_seconds": round(wall, 1),
    }
    if crash_msg:
        row["error"] = crash_msg
        return row
    if fb is None:
        row["ok"] = False
        row["error"] = "no result"
        return row
    fr = fb.final_react_result
    fv = fb.final_verdict
    signals: dict[str, Any] = {
        "task_id": task_id,
        "final_iter_idx": fb.final_iter_idx,
        "rollback_reason": fb.rollback_reason,
        "n_feedback_iterations": fb.n_feedback_iterations,
        "n_tool_calls": fr.n_distinct_tools_called,
        "tools_called": fr.tools_called,
        "termination_reason": fr.termination_reason,
        "error": fr.error,
    }
    if fv and fv.ok and fv.verdict and fv.verdict.claim_metrics:
        cm = fv.verdict.claim_metrics
        signals["n_supported"] = cm.supported_claims
        signals["n_unsupported"] = cm.unsupported_claims
        signals["n_contradicted"] = cm.contradicted_claims
        signals["n_unverifiable_v0"] = cm.unverifiable_claims
        signals["n_insufficient_evidence"] = cm.insufficient_evidence_claims
        signals["n_dropped"] = cm.dropped_by_grammar
    row["signals"] = signals
    return row


def _run_one(
    raw_task: dict[str, Any],
    runner: ConcordReactRunner,
    status_dir: Path,
    full_dir: Path,
    progress_lock: threading.Lock,
    counter: dict[str, int],
    n_tasks: int,
) -> dict[str, Any]:
    tid = raw_task.get("task_id", "unknown")
    done_path = status_dir / f"{tid}.json"
    if done_path.exists():
        with progress_lock:
            counter["done"] += 1
            done = counter["done"]
        logging.info("[%d/%d] %s SKIP (already done)", done, n_tasks, tid)
        return json.loads(done_path.read_text(encoding="utf-8"))

    t0 = time.time()
    trace_id = f"{_TRACE_PREFIX}.{tid}"

    task = _normalize_task(raw_task)
    fb = None
    crash_msg = None
    try:
        fb = runner.run_task_with_feedback(task, trace_id=trace_id)
    except Exception as exc:
        crash_msg = f"{type(exc).__name__}: {exc}"
        logging.exception("[%s] crashed: %s", tid, exc)

    wall = time.time() - t0
    status = _make_status(task, fb, wall=wall, crash_msg=crash_msg)
    _write_status(status_dir, tid, status)

    if fb is not None:
        dump = dataclasses.asdict(fb)
        dump["_v4_metabolites"] = task["differential_metabolites"]
        (full_dir / f"{tid}.json").write_text(
            json.dumps(dump, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    with progress_lock:
        counter["done"] += 1
        if crash_msg:
            counter["crash"] += 1
        done = counter["done"]
    logging.info(
        "[%d/%d] %s %.0fs ok=%s tools=%s",
        done, n_tasks, tid, wall, not crash_msg,
        status.get("signals", {}).get("n_tool_calls", "?"),
    )
    return status


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="V4 benchmark eval — SMILES/name input")
    p.add_argument("--benchmark", default=str(_BENCHMARK))
    p.add_argument(
        "--stratum",
        choices=["hmdb_ramp", "sub6", "human1", "recon22", "all"],
        default="hmdb_ramp",
    )
    p.add_argument(
        "--strata",
        nargs="+",
        choices=["hmdb_ramp", "sub6", "human1", "recon22"],
        default=None,
        help="Run multiple strata (overrides --stratum). E.g. --strata sub6 hmdb_ramp",
    )
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--task-ids", nargs="*")
    p.add_argument("--out", default="data/metagent/v4_bench_eval")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--max-react-turns", type=int, default=8)
    p.add_argument("--max-feedback-iters", type=int, default=1)
    p.add_argument("--llm-model", default=None)
    p.add_argument("--llm-provider", default=None)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    bench_path = Path(args.benchmark)
    all_tasks = [json.loads(l) for l in bench_path.read_text().splitlines() if l.strip()]
    logging.info("Loaded %d tasks from %s", len(all_tasks), bench_path)

    if args.task_ids:
        tasks = [t for t in all_tasks if t["task_id"] in set(args.task_ids)]
    elif args.strata:
        strata_set = set(args.strata)
        tasks = [t for t in all_tasks if _stratum_of_task_id(t["task_id"]) in strata_set]
    elif args.stratum == "all":
        tasks = all_tasks[: args.limit]
    else:
        tasks = [
            t for t in all_tasks if _stratum_of_task_id(t["task_id"]) == args.stratum
        ][: args.limit]

    label = ",".join(args.strata) if args.strata else args.stratum
    logging.info("Running %d tasks (stratum=%s limit=%d)", len(tasks), label, args.limit)

    out_root = Path(args.out)
    status_dir = out_root / "status"
    full_dir = out_root / "path_x_full"
    status_dir.mkdir(parents=True, exist_ok=True)
    full_dir.mkdir(parents=True, exist_ok=True)

    _prov = args.llm_provider or os.environ.get("METAGENT_LLM_PROVIDER", "openai")
    _model = args.llm_model or (
        os.environ.get("METAGENT_MINIMAX_MODEL", "MiniMax-M2.7-highspeed")
        if _prov == "minimax"
        else os.environ.get("METAGENT_OPENAI_MODEL", "gpt-5.5")
    )
    logging.info("LLM provider=%s model=%s", _prov, _model)

    runner = ConcordReactRunner(
        chat_with_tools=_llm_chat,
        verifier_fn=_b1_verify_sub6,
        max_react_turns=args.max_react_turns,
        max_feedback_iters=args.max_feedback_iters,
        llm_provider=_prov,
        llm_model=_model,
    )
    reset_run_level_tracker()

    n_tasks = len(tasks)
    progress_lock = threading.Lock()
    counter = {"done": 0, "crash": 0}
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=args.k) as pool:
        futures = {
            pool.submit(
                _run_one, t, runner, status_dir, full_dir,
                progress_lock, counter, n_tasks,
            ): t["task_id"]
            for t in tasks
        }
        for fut in as_completed(futures):
            fut.result()

    wall_total = time.time() - t_start
    n_ok = n_tasks - counter["crash"]
    logging.info("Done: %d/%d ok | %d crash | %.0fs total", n_ok, n_tasks, counter["crash"], wall_total)
    logging.info(
        "\nScore with:\n"
        "  PYTHONPATH=. python3 scripts/metagent/full344_pathway_scorecard.py \\\n"
        "    --out-dir %s \\\n"
        "    --benchmark data/benchmark/metagent_bench_v2/metagent_bench_easy_v4.jsonl \\\n"
        "    --relevant-sidecar data/benchmark/metagent_bench_v2/relevant_sets_easy_v3.json \\\n"
        "    --gold-sidecar data/benchmark/metagent_bench_v2/gold_drivers_easy_v3.json \\\n"
        "    --ramp /data/weiwentao/llm_agent_metabolomics/ramp.sqlite",
        out_root,
    )


if __name__ == "__main__":
    main()
